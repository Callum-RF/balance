"""Shared non-UI pieces: currency, settings, modules, nav, periods, helpers."""
import csv
import inspect
import io
import json
import statistics
from datetime import date, timedelta

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    AppSettings,
    Category,
)
from backend.modules import MODULES, MODULES_SENTINEL
from backend.routers.stats import period_bounds

from .theme import (
    AMBER,
    EMERALD,
    INDIGO,
    RED,
    TEXT_DIM,
    apply_theme,
)


# Display currency, loaded from AppSettings at each shell render so a change
# on the Settings page applies immediately. Module-level because it's read
# inside f-strings all over this file at render time.
class _Currency:
    """The display currency symbol. Settings can change it at runtime, and
    pages across several modules read it inside f-strings -- so it's one
    shared object that formats as the current symbol, not a string that each
    importing module would copy (and freeze) at import time."""
    symbol = "£"

    def __str__(self):
        return self.symbol

    def __format__(self, spec):
        return format(self.symbol, spec)


CUR = _Currency()
CURRENCY_OPTIONS = ["£", "$", "€", "¥", "zł", "kr", "CHF", "A$", "C$", "₹"]


def load_app_settings():
    """Refresh the module-level currency from the DB; returns the row."""
    with Session(engine) as session:
        settings = session.exec(select(AppSettings)).first()
        if not settings:
            settings = AppSettings()
            session.add(settings)
            session.commit()
            session.refresh(settings)
    CUR.symbol = settings.currency or "£"
    apply_theme(settings.theme or "dark")
    return settings


# Modernize every form field app-wide in one place: use Quasar's "outlined"
# variant -- which the theme styles as a dark, rounded, filled box -- instead
# of the default underline/floating-label look, so inputs match the rest of the
# UI without repeating props at every call site.
for _field_cls in (ui.input, ui.number, ui.select, ui.textarea):
    _field_cls.default_props("outlined dense")

# --- Feature modules -------------------------------------------------------
# The MODULES / MODULE_TIERS registry lives in backend.modules (shared with the
# DB backfill). Core nav items (module key = None) are always shown; optional
# modules ship OFF for a fresh install (lean defaults) and are toggled in
# Settings > Modules. Existing installs are backfilled to all-on on upgrade.
#
# NAV_ITEMS / BOTTOM_NAV_ITEMS: (label, route, icon, module_key). module_key None
# = core (always shown); otherwise the item appears only when that module is on.
NAV_ITEMS = [
    ("Dashboard", "/", "space_dashboard", None),
    ("Transactions", "/transactions", "receipt_long", None),
    ("Income", "/income", "payments", "income"),
    ("Accounts", "/accounts", "account_balance", "networth"),
    ("Import Statement", "/import", "upload_file", "import"),
    ("Food Log", "/food-log", "restaurant", None),
    ("Recipes", "/recipes", "menu_book", "recipes"),
    ("Pantry", "/pantry", "kitchen", "pantry"),
    ("Shopping", "/shopping", "shopping_cart", "shopping"),
    ("Subscriptions", "/subscriptions", "autorenew", "subscriptions"),
    ("Scheduled", "/scheduled", "event_repeat", "scheduled"),
    ("Prices", "/prices", "trending_up", "prices"),
    ("Forecast", "/forecast", "insights", "forecast"),
    ("Savings Goals", "/savings", "savings", "savings"),
    ("Monthly Report", "/reports", "summarize", "reports"),
    ("Profile & Goals", "/profile", "person", None),
    ("Settings", "/settings", "settings", None),
]

# The handful of most-used destinations shown in the mobile bottom nav bar;
# everything else stays one tap away behind "More" (which opens the drawer).
BOTTOM_NAV_ITEMS = [
    ("Dashboard", "/", "space_dashboard", None),
    ("Transactions", "/transactions", "receipt_long", None),
    ("Food Log", "/food-log", "restaurant", None),
    ("Pantry", "/pantry", "kitchen", "pantry"),
]

# Spending that's a "want" rather than a "need" -- the flexible money a savings
# goal can realistically be funded from. Used by the goal-coaching on /savings.
DISCRETIONARY_CATEGORIES = {
    "Eating Out", "Entertainment", "Subscriptions", "Travel",
}


def load_enabled_modules() -> dict:
    """Effective {module_key: bool} -- a persisted override, else the registry default."""
    with Session(engine) as session:
        settings = session.exec(select(AppSettings)).first()
    overrides = {}
    raw = getattr(settings, "modules_json", None) if settings else None
    if raw:
        try:
            overrides = json.loads(raw) or {}
        except (ValueError, TypeError):
            overrides = {}
    return {key: bool(overrides.get(key, meta[2])) for key, meta in MODULES.items()}


def module_enabled(module_key, enabled=None) -> bool:
    """Whether a nav item should render. Core items (module_key=None) are always shown."""
    if module_key is None:
        return True
    if enabled is None:
        enabled = load_enabled_modules()
    return enabled.get(module_key, True)


def set_module_enabled(module_key: str, value: bool) -> None:
    """Persist a single module on/off override into AppSettings.modules_json."""
    with Session(engine) as session:
        settings = session.exec(select(AppSettings)).first()
        overrides = {}
        if settings.modules_json:
            try:
                overrides = json.loads(settings.modules_json) or {}
            except (ValueError, TypeError):
                overrides = {}
        overrides[module_key] = bool(value)
        settings.modules_json = json.dumps(overrides)
        session.add(settings)
        session.commit()


def set_all_modules(value: bool) -> None:
    """Preset: enable every module (value=True) or reset to the lean defaults
    (value=False -> only the sentinel is kept, so registry defaults apply)."""
    data = {MODULES_SENTINEL: True}
    if value:
        for key in MODULES:
            data[key] = True
    with Session(engine) as session:
        settings = session.exec(select(AppSettings)).first()
        settings.modules_json = json.dumps(data)
        session.add(settings)
        session.commit()


def friendly_range(start, end, period):
    """Human-readable label for a period window, e.g. 'July 2026' or
    '20 – 26 Jul 2026', instead of a raw ISO date pair."""
    if period == "daily":
        return start.strftime("%A, %d %b %Y")
    if period == "weekly":
        return f"{start:%d %b} – {end:%d %b %Y}"
    if period == "monthly":
        return start.strftime("%B %Y")
    if period == "yearly":
        return start.strftime("%Y")
    return f"{start:%d %b %Y} – {end:%d %b %Y}"


def _period_total(model, amount_field, date_field, start, end):
    """Sum of `amount_field` over rows of `model` whose `date_field` falls in
    [start, end] -- used to compute the previous-period comparison total."""
    with Session(engine) as session:
        rows = session.exec(select(model).where(date_field >= start, date_field <= end)).all()
    return sum(getattr(r, amount_field) or 0 for r in rows)


def resolve_window(period, ref_date, model=None, date_col=None, custom_range=None):
    """Resolve a period into (start, end) inclusive dates. 'custom' uses the
    given (start, end); 'all_time' spans from the earliest row of `model` to
    today; everything else defers to period_bounds. Reversed custom dates are
    tolerated (swapped), so a user can pick either order."""
    if period == "custom":
        if custom_range and custom_range[0] and custom_range[1]:
            s, e = custom_range
            return (s, e) if s <= e else (e, s)  # tolerate reversed input
        return period_bounds("monthly", ref_date)  # safe fallback until dates are picked
    if period == "all_time":
        end = date.today()
        if model is not None and date_col is not None:
            with Session(engine) as session:
                earliest = session.exec(select(model).order_by(date_col)).first()
            return (earliest.date if earliest else end), end
        return end, end
    return period_bounds(period, ref_date)


def previous_window(period, start, num_days):
    """(prev_start, prev_end) for the equivalent window immediately before
    `start`, used for the 'vs previous period' comparison -- or None when
    there's nothing sensible to compare against ('all_time')."""
    if period == "all_time":
        return None
    if period == "custom":
        prev_end = start - timedelta(days=1)
        return prev_end - timedelta(days=num_days - 1), prev_end
    return period_bounds(period, start - timedelta(days=1))


def _category_label(category: Category, all_categories) -> str:
    if category.parent_id is None:
        return category.name
    parent = next((c for c in all_categories if c.id == category.parent_id), None)
    return f"{parent.name} > {category.name}" if parent else category.name


TAG_OPTIONS = ["", "Alone", "With friends", "With family", "Work", "Other"]

# Stored values (used by the Forecast page's ACTIVITY_MULTIPLIERS lookup)
# stay the same plain words; only the displayed label is more descriptive,
# since "light" vs "moderate" on their own don't tell you what to pick.
ACTIVITY_LEVEL_OPTIONS = {
    "sedentary": "Sedentary — little to no exercise, desk job",
    "light": "Light — light exercise 1–3 days/week",
    "moderate": "Moderate — moderate exercise 3–5 days/week",
    "active": "Active — hard exercise 6–7 days/week",
    "very_active": "Very active — very hard exercise or physical job, training twice a day",
}

MEAL_ICONS = {
    "breakfast": ("free_breakfast", "#F59E0B"),
    "lunch": ("lunch_dining", EMERALD),
    "dinner": ("dinner_dining", INDIGO),
    "snack": ("fastfood", "#38BDF8"),
}
PAYMENT_ICONS = {
    "Card": "credit_card",
    "Cash": "payments",
    "Bank Transfer": "account_balance",
    "Other": "more_horiz",
}
INCOME_ICONS = {
    "Salary": "work",
    "Freelance": "laptop_mac",
    "Gift": "card_giftcard",
    "Refund": "replay",
    "Investment": "trending_up",
    "Interest": "savings",
    "Other": "attach_money",
}
LOCATION_ICONS = {
    "fridge": ("kitchen", "#38BDF8"),
    "freezer": ("ac_unit", "#818CF8"),
    "pantry": ("shelves", "#F59E0B"),
}
MACRO_GROUP_ICONS = {
    "protein": "egg",
    "carbs": "bakery_dining",
    "fat": "water_drop",
    "produce": "eco",
    "dairy": "icecream",
    "other": "label",
}


def expiry_meta(exp_date):
    """(short_label, color) describing how close a pantry item is to expiry,
    or None if it has no expiration date. Green = comfortable, amber = this
    week, red = gone or nearly gone."""
    if not exp_date:
        return None
    days = (exp_date - date.today()).days
    if days < 0:
        return (f"expired {-days}d ago", RED)
    if days == 0:
        return ("expires today", RED)
    if days <= 2:
        return (f"{days}d left", RED)
    if days <= 7:
        return (f"{days}d left", AMBER)
    if days <= 30:
        return (f"{days}d left", EMERALD)
    return (exp_date.strftime("exp %d %b %Y"), TEXT_DIM)


async def _read_upload_bytes(e) -> bytes:
    """NiceGUI's upload event API has changed across versions -- older
    versions expose `e.name`/`e.content` directly, newer ones wrap the
    file in `e.file` (e.g. `e.file.name`/`e.file.content`), and `.read()`
    is sync on some versions but async (returns a coroutine) on others.
    Handle all of it rather than betting on one shape."""
    file_obj = getattr(e, "file", None) or e
    content = getattr(file_obj, "content", None)
    target = content if content is not None else (file_obj if hasattr(file_obj, "read") else None)
    if target is None:
        raise RuntimeError("Could not read the uploaded file (unrecognized NiceGUI upload API).")
    if not hasattr(target, "read"):
        return bytes(target)
    result = target.read()
    if inspect.isawaitable(result):
        result = await result
    return result


def format_date_header(d: date) -> str:
    """'Today' / 'Yesterday' for recent dates, otherwise a compact weekday
    + date -- avoids repeating the raw ISO date on every single row."""
    today = date.today()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%a, %d %b")


def group_by_date(entries):
    """Groups already-date-descending-sorted entries into (date, [entries]) pairs."""
    groups = []
    current_date, current_group = None, []
    for entry in entries:
        if entry.date != current_date:
            if current_group:
                groups.append((current_date, current_group))
            current_date, current_group = entry.date, []
        current_group.append(entry)
    if current_group:
        groups.append((current_date, current_group))
    return groups


def download_csv(headers, rows, filename):
    """Serialize rows to CSV and push it to the browser as a file download.
    `headers` is a list of column names; `rows` a list of row-sequences."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    ui.download.content(buffer.getvalue().encode("utf-8-sig"), filename, "text/csv")
    ui.notify(f"Exported {len(rows)} row(s) to {filename}", type="positive")


# ---------------------------------------------------------------------------
# Recurring-payment detection: spot merchants you're charged by on a regular
# cadence but haven't set up as a subscription, so they can be formalized
# (and thus show up in the monthly-total / installment tracking).
# ---------------------------------------------------------------------------
def _classify_cadence(median_gap_days):
    """Map a median inter-payment gap to a billing cycle, or None if it
    doesn't look like a recurring cadence we track."""
    if 25 <= median_gap_days <= 35:
        return "monthly"
    if 350 <= median_gap_days <= 380:
        return "yearly"
    return None


# Everyday-spend categories where regular-ish purchases (a weekly shop, a
# monthly-ish fuel stop) coincidentally mimic a subscription's cadence --
# excluded from recurring detection to avoid nonsense suggestions.
NON_SUBSCRIPTION_CATEGORIES = {"Groceries", "Eating Out", "Transport"}


def detect_recurring_transactions(transactions, existing_sub_names, exclude_category_ids=frozenset()):
    """Given all transactions, return a list of detected recurring-payment
    candidates the user hasn't already captured as a subscription.

    A candidate needs: >=3 charges from the same merchant, a roughly
    regular (monthly/yearly) cadence, and near-constant amounts (real
    recurring bills barely vary). Subscription-generated transactions,
    merchants already matching a subscription name, and everyday-spend
    categories (see NON_SUBSCRIPTION_CATEGORIES) are excluded."""
    existing = {name.strip().lower() for name in existing_sub_names if name}

    by_merchant = {}
    for t in transactions:
        if t.is_subscription_payment:
            continue  # these were created *by* a subscription; not a discovery
        if t.category_id in exclude_category_ids:
            continue  # groceries/fuel etc. that just happen to look monthly
        name = (t.merchant or "").strip()
        if not name or name.lower() in existing:
            continue
        by_merchant.setdefault(name, []).append(t)

    candidates = []
    for merchant, txns in by_merchant.items():
        if len(txns) < 3:
            continue
        txns = sorted(txns, key=lambda t: t.date)
        gaps = [(txns[i + 1].date - txns[i].date).days for i in range(len(txns) - 1)]
        gaps = [g for g in gaps if g > 0]
        if not gaps:
            continue
        median_gap = statistics.median(gaps)
        cadence = _classify_cadence(median_gap)
        if not cadence:
            continue
        amounts = [t.amount for t in txns]
        mean_amount = statistics.mean(amounts)
        # near-constant amounts: coefficient of variation under 15%
        if mean_amount <= 0:
            continue
        stdev = statistics.pstdev(amounts)
        if stdev / mean_amount > 0.15:
            continue
        candidates.append({
            "merchant": merchant,
            "cadence": cadence,
            "typical_amount": round(mean_amount, 2),
            "count": len(txns),
            "last_seen": txns[-1].date,
            "category_id": txns[-1].category_id,
        })

    candidates.sort(key=lambda c: (-c["count"], -c["typical_amount"]))
    return candidates
