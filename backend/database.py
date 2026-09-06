"""
SQLite engine + session management, schema auto-migration, and
default-category seeding.
"""
import json
import os
from typing import Generator

from sqlalchemy import inspect, text, Boolean, event
from sqlmodel import SQLModel, Session, create_engine, select

from backend.models import Category, UserProfile, NutrientGoals, AppSettings
from backend.modules import MODULES, MODULES_SENTINEL

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")

RECEIPTS_DIR = os.path.join(DATA_DIR, "receipts")
os.makedirs(RECEIPTS_DIR, exist_ok=True)

# check_same_thread=False is needed because FastAPI can use different
# threads for different requests; SQLite handles this fine for our
# single-user, low-concurrency use case.
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    """Apply per-connection SQLite settings on every new connection.

    WAL is far more crash-resilient than the default rollback journal (it keeps
    the main DB file valid even if the process dies mid-write -- directly
    relevant on a machine that has crashed mid-write), synchronous=NORMAL is the
    safe, fast companion to WAL, and busy_timeout makes a briefly-locked DB wait
    rather than raise 'database is locked'.

    foreign_keys is intentionally left OFF for now: the app already manages
    referential integrity in code (see delete_category, which reassigns
    references before removing a category). Turning enforcement on is a
    behaviour change that interacts with SQLAlchemy's flush ordering, so it
    belongs in its own separately-tested change, not here.
    """
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


DEFAULT_CATEGORIES = {
    "Food": ["Groceries", "Dining Out", "Coffee/Snacks", "Supplements"],
    "Entertainment": ["Books", "Games", "Streaming", "Hobbies"],
    "Transport": ["Fuel", "Public Transport", "Vehicle Maintenance"],
    "Bills": ["Rent/Mortgage", "Utilities", "Phone/Mobile", "Subscriptions", "Insurance"],
    "Health": ["Pharmacy", "Medical", "Fitness"],
    "Shopping": ["Clothing", "Household", "Personal Care", "Gifts"],
    "Education": [],
    "Travel/Holidays": [],
    "Miscellaneous": [],
}


def create_db_and_tables() -> None:
    _check_integrity()                    # surface any crash corruption loudly
    SQLModel.metadata.create_all(engine)  # creates any brand-new tables
    _migrate_missing_columns()            # adds any new columns on tables that already existed
    _seed_default_categories()
    _seed_singleton_rows()
    _backfill_modules_defaults()          # keep existing installs all-on; fresh installs stay lean


def _check_integrity() -> None:
    """Log the result of PRAGMA integrity_check at startup so a crash-corrupted
    database is surfaced in the logs rather than silently serving bad data."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA integrity_check")).scalar()
        if result == "ok":
            print("[db] integrity_check: ok")
        else:
            print(f"[db] WARNING: integrity_check failed: {result}")
    except Exception as exc:  # pragma: no cover -- never let the check crash startup
        print(f"[db] integrity_check could not run: {exc}")


def _migrate_missing_columns() -> None:
    """
    Lightweight auto-migration: for every table SQLModel knows about that
    already exists in the DB, add any columns present in the model but
    missing from the actual table (SQLite supports ADD COLUMN directly).
    Safe to run on every startup -- it's a no-op once columns exist.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.connect() as conn:
        for table_name, table in SQLModel.metadata.tables.items():
            if table_name not in existing_tables:
                continue  # brand-new table, already handled by create_all
            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(engine.dialect)
                # SQLite requires a DEFAULT when adding a NOT NULL column,
                # and we want existing rows to get a sane value either way.
                if isinstance(column.type, Boolean):
                    default_sql = " DEFAULT 0"
                elif not column.nullable:
                    default_sql = " DEFAULT 0"
                else:
                    default_sql = ""
                stmt = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {col_type}{default_sql}'
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception as exc:  # pragma: no cover -- defensive, logged not raised
                    print(f"[migration] could not add {table_name}.{column.name}: {exc}")


def _seed_singleton_rows() -> None:
    with Session(engine) as session:
        if not session.exec(select(UserProfile)).first():
            session.add(UserProfile())
        if not session.exec(select(NutrientGoals)).first():
            session.add(NutrientGoals())
        if not session.exec(select(AppSettings)).first():
            # Fresh install: stamp the sentinel so no module keys are set and the
            # lean registry defaults apply (backfill will then skip this row).
            session.add(AppSettings(modules_json=json.dumps({MODULES_SENTINEL: True})))
        session.commit()


def _backfill_modules_defaults() -> None:
    """One-time: on an install that predates lean module defaults, make every
    module explicitly enabled so upgrading never hides a section that was on.
    Fresh installs are seeded already stamped, so this skips them and they keep
    the lean defaults. Idempotent via the sentinel key."""
    with Session(engine) as session:
        settings = session.exec(select(AppSettings)).first()
        if not settings:
            return
        try:
            data = json.loads(settings.modules_json) if settings.modules_json else {}
        except (ValueError, TypeError):
            data = {}
        if data.get(MODULES_SENTINEL):
            return  # already processed (fresh-seeded or previously backfilled)
        for key in MODULES:
            data.setdefault(key, True)  # preserve pre-lean all-on
        data[MODULES_SENTINEL] = True
        settings.modules_json = json.dumps(data)
        session.add(settings)
        session.commit()


def _seed_default_categories() -> None:
    with Session(engine) as session:
        existing = session.exec(select(Category)).first()
        if existing:
            return  # already seeded
        for parent_name, children in DEFAULT_CATEGORIES.items():
            parent = Category(name=parent_name, parent_id=None)
            session.add(parent)
            session.commit()
            session.refresh(parent)
            for child_name in children:
                session.add(Category(name=child_name, parent_id=parent.id))
        session.commit()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
