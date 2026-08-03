"""Scheduled / recurring transactions.

A ScheduledTransaction is a template that produces a real Transaction or Income
on a cadence. Auto-post items are created automatically by a background thread
(which catches up any periods missed while the app was down); manual items
surface on the Scheduled page for the user to confirm or skip. Runs in-process
off the always-on service -- no OS scheduler or admin needed, same pattern as
backup.py.
"""
import calendar
import threading
import time
from datetime import date, timedelta

from sqlmodel import Session, select

from backend.database import engine
from backend.models import Income, ScheduledTransaction, Transaction

INTERVAL_SECONDS = 3600  # re-check hourly; the catch-up loop handles missed days


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])  # clamp to month length
    return date(year, month, day)


def advance(d: date, cadence: str) -> date:
    """The next occurrence date after ``d`` for the given cadence."""
    if cadence == "weekly":
        return d + timedelta(days=7)
    if cadence == "yearly":
        return _add_months(d, 12)
    return _add_months(d, 1)  # monthly (default)


def _post(item: ScheduledTransaction, session: Session, on_date: date) -> None:
    if item.kind == "income":
        session.add(Income(date=on_date, amount=item.amount, source=item.source or "Other",
                           payer=item.description, tag=item.tag, notes=item.notes))
    else:
        session.add(Transaction(date=on_date, amount=item.amount, merchant=item.description,
                               category_id=item.category_id, tag=item.tag, notes=item.notes))


def post_now(item_id: int) -> bool:
    """Post the next due occurrence immediately and advance (used by 'Post now')."""
    with Session(engine) as session:
        item = session.get(ScheduledTransaction, item_id)
        if not item:
            return False
        _post(item, session, item.next_date)
        item.last_posted = date.today()
        item.next_date = advance(item.next_date, item.cadence)
        session.add(item)
        session.commit()
    return True


def skip_next(item_id: int) -> bool:
    """Advance past the next occurrence without posting it (used by 'Skip')."""
    with Session(engine) as session:
        item = session.get(ScheduledTransaction, item_id)
        if not item:
            return False
        item.next_date = advance(item.next_date, item.cadence)
        session.add(item)
        session.commit()
    return True


def process_due_auto(today: date = None) -> int:
    """Auto-post every due occurrence of active auto-post items, catching up any
    periods missed while the app was down. Idempotent per day."""
    today = today or date.today()
    posted = 0
    with Session(engine) as session:
        items = session.exec(
            select(ScheduledTransaction).where(
                ScheduledTransaction.active == True,      # noqa: E712
                ScheduledTransaction.auto_post == True,   # noqa: E712
            )
        ).all()
        for item in items:
            guard = 0
            while item.next_date <= today and guard < 1000:  # guard against runaway
                _post(item, session, item.next_date)
                item.last_posted = item.next_date
                item.next_date = advance(item.next_date, item.cadence)
                posted += 1
                guard += 1
            session.add(item)
        session.commit()
    if posted:
        print(f"[recurring] auto-posted {posted} scheduled transaction(s)")
    return posted


def _loop() -> None:
    while True:
        try:
            process_due_auto()
        except Exception as exc:
            print(f"[recurring] error: {exc}")
        time.sleep(INTERVAL_SECONDS)


def start_scheduler() -> None:
    """Start the background auto-post thread. Safe to call once per process."""
    threading.Thread(target=_loop, daemon=True, name="balance-recurring").start()
