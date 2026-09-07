"""
NiceGUI frontend for Balance. Talks directly to the database via SQLModel
sessions (same process as the FastAPI backend). Dark, Linear-inspired
shell: responsive header + drawer nav (persistent sidebar on desktop,
collapsible overlay on mobile), flat cards, minimal chrome.
"""
import csv
import hashlib
import inspect
import io
import json
import os
import secrets
import statistics
import uuid
from collections import Counter
from datetime import date, datetime, timedelta

from nicegui import app, ui
from sqlmodel import Session, select

from backend.database import engine, RECEIPTS_DIR
from backend.modules import MODULES, MODULE_TIERS, MODULES_SENTINEL
from backend.models import (
    Category, Transaction, FoodLog, WaterLog, WaterLogCreate,
    UserProfile, NutrientGoals, BudgetTarget, PantryItem, Subscription,
    PriceObservation, WeightLog, Income, INCOME_SOURCES, AppSettings,
    ScheduledTransaction, Recipe, RecipeItem, ShoppingListItem, SavingsGoal,
    Account, NetWorthSnapshot,
)
from backend.services.openfoodfacts import lookup_barcode
from backend.services.categorize import build_history_map, guess_category_id
from backend.services.statement_import import (
    parse_csv, parse_date_with_format, parse_amount, extract_pdf_text,
    parse_pdf_lines, DATE_FORMATS, StatementImportError,
)
from backend.routers.stats import period_bounds, NUTRIENT_FIELDS
from backend.routers.profile import calculate_age, compute_weight_trend, WEIGHT_TREND_WINDOWS
from backend.routers.forecast import compute_forecast, estimate_bmr, ACTIVITY_MULTIPLIERS
from backend.nutrient_info import NUTRIENT_INFO, CAFFEINE_LIKE_SUBSTANCES

# ---------------------------------------------------------------------------
# Design tokens & themes. Every color in the app flows from these module-level
# tokens, which are read inside f-strings at render time -- so apply_theme()
# can swap the entire look by reassigning them. Light themes also swap the
# accent set for darker variants that keep contrast on pale surfaces.
# ---------------------------------------------------------------------------
_TOKEN_KEYS = ("BG", "SURFACE", "SURFACE_2", "BORDER", "TEXT", "TEXT_DIM",
               "INDIGO", "EMERALD", "AMBER", "RED", "SKY", "VIOLET")

THEMES = {
    "midnight": dict(label="Midnight", dark=True,
                     BG="#0B0B0F", SURFACE="#151519", SURFACE_2="#1C1C22", BORDER="#26262E",
                     TEXT="#E4E4E7", TEXT_DIM="#8A8A93",
                     INDIGO="#6366F1", EMERALD="#34D399", AMBER="#F59E0B",
                     RED="#F87171", SKY="#38BDF8", VIOLET="#A78BFA"),
    "ocean": dict(label="Ocean", dark=True,
                  BG="#0A1017", SURFACE="#101823", SURFACE_2="#17222F", BORDER="#233240",
                  TEXT="#E2E8F0", TEXT_DIM="#8496AB",
                  INDIGO="#38BDF8", EMERALD="#34D399", AMBER="#FBBF24",
                  RED="#F87171", SKY="#7DD3FC", VIOLET="#A5B4FC"),
    "cream": dict(label="Cream", dark=False,
                  BG="#F4EFE6", SURFACE="#FDFBF6", SURFACE_2="#EDE7DA", BORDER="#DCD3C2",
                  TEXT="#2A2419", TEXT_DIM="#6E6350",  # darkened: #877C68 was 3.6:1, below AA
                  INDIGO="#4F46E5", EMERALD="#047857", AMBER="#B45309",
                  RED="#DC2626", SKY="#0369A1", VIOLET="#6D28D9"),
    "lavender": dict(label="Lavender", dark=False,
                     BG="#F2EEFA", SURFACE="#FCFAFF", SURFACE_2="#EAE3F6", BORDER="#D8CCEC",
                     TEXT="#2C2340", TEXT_DIM="#6E6187",  # darkened: #83769F was 3.6:1, below AA
                     INDIGO="#6D28D9", EMERALD="#047857", AMBER="#B45309",
                     RED="#DC2626", SKY="#0369A1", VIOLET="#7C3AED"),
}

ACTIVE_THEME = "midnight"
THEME_DARK = True
BG = SURFACE = SURFACE_2 = BORDER = TEXT = TEXT_DIM = ""
INDIGO = EMERALD = AMBER = RED = SKY = VIOLET = ""
CARD = LIST_GROUP = CARD_ACCENT = ""
CHART_PALETTE: list = []
PAGE = "w-full max-w-5xl mx-auto p-3 sm:p-6 gap-4 sm:gap-6"


def apply_theme(name: str):
    """Point every design token at the named theme and rebuild the derived
    class strings. Takes effect on the next page render."""
    global ACTIVE_THEME, THEME_DARK, CARD, LIST_GROUP, CARD_ACCENT, CHART_PALETTE
    theme = THEMES.get(name, THEMES["midnight"])
    ACTIVE_THEME = name if name in THEMES else "midnight"
    THEME_DARK = theme["dark"]
    for key in _TOKEN_KEYS:
        globals()[key] = theme[key]
    CARD = f"surface-card bg-[{SURFACE}] border border-[{BORDER}] rounded-2xl p-4 sm:p-5 gap-3 w-full"
    # Hero/accent variant of CARD: faint accent wash + a touch more lift, for the
    # single "look here first" card on a screen (dashboard attention / welcome).
    CARD_ACCENT = f"surface-card surface-card-accent border rounded-2xl p-4 sm:p-5 gap-3 w-full"
    # A bordered surface holding a day's list rows with hairline dividers --
    # the "grouped list" look used by Transactions / Food Log / Settings.
    LIST_GROUP = f"bg-[{SURFACE}] border border-[{BORDER}] rounded-2xl w-full overflow-hidden gap-0 p-0"
    CHART_PALETTE = [INDIGO, EMERALD, AMBER, SKY, RED, VIOLET, "#FB923C", "#2DD4BF"]


apply_theme("midnight")

# Display currency, loaded from AppSettings at each shell render so a change
# on the Settings page applies immediately. Module-level because it's read
# inside f-strings all over this file at render time.
CUR = "£"
CURRENCY_OPTIONS = ["£", "$", "€", "¥", "zł", "kr", "CHF", "A$", "C$", "₹"]


def load_app_settings():
    """Refresh the module-level currency from the DB; returns the row."""
    global CUR
    with Session(engine) as session:
        settings = session.exec(select(AppSettings)).first()
        if not settings:
            settings = AppSettings()
            session.add(settings)
            session.commit()
            session.refresh(settings)
    CUR = settings.currency or "£"
    apply_theme(settings.theme or "midnight")
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


def _render_module_disabled() -> None:
    """Placeholder shown when a disabled module's page is reached by direct URL."""
    with ui.column().classes("w-full items-center gap-2 mt-16 text-center"):
        ui.icon("visibility_off").classes("text-5xl").style(f"color:{TEXT_DIM}")
        ui.label("This section is turned off").classes("text-lg font-semibold")
        ui.label("Enable it under Settings → Modules.").classes("text-sm").style(f"color:{TEXT_DIM}")
        ui.button("Open Settings", icon="settings",
                  on_click=lambda: ui.navigate.to("/settings")).props("unelevated no-caps color=primary").classes("mt-1")


def _module_guard(page_fn, module_key):
    """Wrap a page so it renders a 'turned off' notice when its module is disabled."""
    def wrapped():
        if not module_enabled(module_key):
            _render_module_disabled()
            return
        return page_fn()
    return wrapped


def inject_theme():
    (ui.dark_mode().enable() if THEME_DARK else ui.dark_mode().disable())
    # Make Quasar's *brand* primary the theme accent too. The CSS --q-primary
    # override below only reaches components that read that var; components that
    # bake the brand colour into an inline style (q-uploader header, q-loading-bar,
    # ripples, spinners) stay NiceGUI-default blue unless we set the brand here.
    ui.colors(primary=INDIGO)
    ui.add_head_html(f"""
    <link rel="icon" type="image/png" href="/icon-assets/icon.png">
    <link rel="apple-touch-icon" href="/icon-assets/icon.png">
    <link rel="manifest" href="/icon-assets/manifest.json">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Balance">
    <script src="https://unpkg.com/[email protected]/html5-qrcode.min.js"></script>
    <script>
      if ('serviceWorker' in navigator) {{
        window.addEventListener('load', function () {{
          navigator.serviceWorker.register('/sw.js').catch(function () {{}});
        }});
      }}
    </script>
    """)
    ui.add_head_html(_APP_SWITCH_JS)
    ui.add_head_html(f"""<meta name="theme-color" content="{BG}">
    <style>
        body {{ background-color: {BG} !important; color: {TEXT}; }}
        ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
        ::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 4px; }}

        /* Brand color for every Quasar component that reads --q-primary
           (selects, dates, switches, radios, focus rings, etc.) */
        :root, .q-dark {{
            --q-primary: {INDIGO};
        }}

        /* Cards float with soft depth instead of reading as hard outlined boxes. */
        .surface-card {{
            box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 8px 22px -12px rgba(0,0,0,.16);
        }}
        /* Hero/accent card: a faint accent wash + slightly stronger lift, for the
           one "look here first" card on a screen. */
        .surface-card-accent {{
            background: linear-gradient(180deg, {INDIGO}14, {INDIGO}0a) !important;
            border-color: {INDIGO}40 !important;
            box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 12px 28px -14px {INDIGO}59;
        }}
        /* Softer, rounder buttons (leave round/fab buttons circular). */
        .q-btn:not(.q-btn--round):not(.q-btn--fab) {{ border-radius: 12px; }}
        /* Sentence-case buttons and tabs app-wide instead of Quasar's shouting UPPERCASE. */
        .q-btn, .q-tab {{ text-transform: none; }}

        /* Dropdowns, text inputs, number inputs, date fields -- consistent
           dark, rounded, filled fields instead of Quasar's default underline */
        .q-field__label {{ color: {TEXT_DIM} !important; }}
        .q-field--outlined .q-field__control {{
            background: transparent;
            border-radius: 12px;
        }}
        .q-field--outlined .q-field__control:before {{
            border-color: {BORDER};
            border-radius: 12px;
            transition: border-color .15s ease;
        }}
        .q-field--outlined .q-field__control:hover:before {{
            border-color: {TEXT_DIM};
        }}
        .q-field--outlined.q-field--focused .q-field__control:before {{
            border-color: {INDIGO};
            border-width: 2px;
            box-shadow: 0 0 0 3px {INDIGO}22;
        }}
        .q-field__native, .q-field__input {{ color: {TEXT} !important; }}
        .q-field__append .q-icon, .q-field__prepend .q-icon {{ color: {TEXT_DIM}; }}
        /* headline fields (large amount/calories) sit a touch taller & bolder */
        .q-field--outlined .q-field__control input.text-2xl {{ padding-top: 4px; }}

        /* Dropdown option lists (select menus) and the date-picker popup */
        .q-menu {{
            background: {SURFACE} !important;
            border: 1px solid {BORDER};
            border-radius: 14px;
            overflow-y: auto;
        }}
        .q-item {{ color: {TEXT}; }}
        .q-item.q-router-link--active, .q-item--active {{ color: {INDIGO}; }}
        .q-item:hover {{ background: {SURFACE_2}; }}
        .q-item--active, .q-manual-focusable--focused > .q-focus-helper {{
            background: {INDIGO}26 !important;
        }}

        /* Calendar popup (date_field's ui.date) */
        .q-date {{
            background: {SURFACE} !important;
            color: {TEXT};
            border-radius: 14px;
        }}
        .q-date__header {{ background: {INDIGO} !important; }}
        .q-date__calendar-item .q-btn {{ color: {TEXT}; }}
        .q-date__calendar-item--out {{ color: {TEXT_DIM}; opacity: 0.5; }}
        .q-date__navigation .q-btn {{ color: {TEXT}; }}

        /* Mobile bottom navigation bar */
        .bottom-nav {{
            background: {SURFACE};
            border-top: 1px solid {BORDER};
            padding-bottom: env(safe-area-inset-bottom);
        }}
        .bottom-nav-item {{ color: {TEXT_DIM}; transition: color .15s; }}
        .bottom-nav-item:hover {{ color: {TEXT}; }}
        .bottom-nav-item.nav-active {{ color: {INDIGO}; }}

        /* Active-page highlight in the drawer / sidebar (desktop + mobile), so
           the current page is indicated consistently with the bottom nav. */
        .drawer-nav-item {{ transition: color .15s, background .15s; }}
        .drawer-nav-item:hover {{ color: {TEXT} !important; background: {SURFACE_2}; }}
        .drawer-nav-item.nav-active {{ color: {TEXT} !important; background: {INDIGO}22; }}

        /* Segmented toggles (meal / type selectors) -- theme-aware; replaces
           Quasar's fixed dark/grey-5, which rendered dark boxes on light themes.
           Inactive: transparent over the SURFACE_2 track with dim text; active:
           the app's primary fill (via toggle-color) with white text. */
        .seg-toggle .q-btn {{ color: {TEXT_DIM} !important; background: transparent !important; }}
        .seg-toggle .q-btn.bg-primary {{ color: #fff !important; }}
    </style>
    <script>
      // Keep the nav highlight in sync with the current sub_pages route, across
      // the bottom nav, the drawer/sidebar, and the "More" button. sub_pages
      // navigates via history.pushState (no reload), so we patch it to fire an
      // update, plus popstate (back/forward) and initial load.
      (function () {{
        function updateNav() {{
          var path = window.location.pathname;
          document.querySelectorAll('.bottom-nav a[href], a.drawer-nav-item[href]').forEach(function (a) {{
            a.classList.toggle('nav-active', a.getAttribute('href') === path);
          }});
          // Light up "More" whenever the current page isn't one of the primary
          // bottom-nav destinations (i.e. it lives behind the drawer).
          var primary = Array.prototype.map.call(
            document.querySelectorAll('.bottom-nav a[href]'),
            function (a) {{ return a.getAttribute('href'); }});
          var more = document.querySelector('.more-nav-item');
          if (more) more.classList.toggle('nav-active', primary.indexOf(path) === -1);
        }}
        var _push = history.pushState;
        history.pushState = function () {{ _push.apply(this, arguments); setTimeout(updateNav, 0); }};
        window.addEventListener('popstate', function () {{ setTimeout(updateNav, 0); }});
        window.addEventListener('load', function () {{ setTimeout(updateNav, 100); }});
        setTimeout(updateNav, 400);
      }})();
    </script>
    """)


# Sibling apps served from this same tailnet node, for the header app-switcher.
THIS_APP = "balance"
APPS = [
    ("balance", "Balance", "account_balance_wallet"),
    ("medley", "Medley", "video_library"),
    ("cadence", "Cadence", "graphic_eq"),
    ("crescendo", "Crescendo", "fitness_center"),
]

# The apps share a hostname but sit on different ports, and those ports differ
# between the tailnet (Balance :8444, Medley :8443, launcher at the root) and
# local dev (:8000 / :8100, no launcher). Resolving from location at click time
# means the switcher works in both places with no server-side config.
_APP_SWITCH_JS = """
<script>
window.__appUrl = function (app) {
  var h = location.hostname;
  var isLocal = (h === 'localhost' || h === '127.0.0.1');
  if (app === 'home') { return isLocal ? null : 'https://' + h + '/'; }
  // Crescendo is the odd one out: a path on the root origin rather than its own
  // port, which is what lets it install inside Ensemble's scope and work offline.
  if (app === 'crescendo') {
    return isLocal ? 'http://' + h + ':8300/crescendo/' : 'https://' + h + '/crescendo/';
  }
  var ports = isLocal ? {balance: 8000, medley: 8100, cadence: 8200}
                      : {balance: 8444, medley: 8443, cadence: 8445};
  return (isLocal ? 'http:' : 'https:') + '//' + h + ':' + ports[app] + '/';
};
window.__goApp = function (app) {
  var u = window.__appUrl(app);
  if (u) { location.href = u; }
};
</script>
"""


def app_switcher():
    """Grid button that jumps to the sibling apps, or back to the Home launcher.
    Targets resolve client-side so the same menu works over the tailnet and in
    local dev, where the ports differ."""
    with ui.button(icon="apps").props("flat round dense").style(
        f"color:{TEXT} !important"
    ):
        with ui.menu().classes("p-1"):
            with ui.row().classes("items-center gap-2 no-wrap px-3 py-1"):
                ui.icon("check").classes("text-sm").style(f"color:{INDIGO}")
                ui.label(f"You're in {dict((a[0], a[1]) for a in APPS)[THIS_APP]}") \
                    .classes("text-xs").style(f"color:{TEXT_DIM}")
            ui.separator().style(f"background:{BORDER}")
            for key, label, icon in APPS:
                if key == THIS_APP:
                    continue
                with ui.menu_item(
                    on_click=lambda k=key: ui.run_javascript(f"window.__goApp('{k}')")
                ):
                    with ui.row().classes("items-center gap-3 no-wrap w-full"):
                        ui.icon(icon).style(f"color:{INDIGO}")
                        ui.label(label)
            ui.separator().style(f"background:{BORDER}")
            with ui.menu_item(
                on_click=lambda: ui.run_javascript("window.__goApp('home')")
            ):
                with ui.row().classes("items-center gap-3 no-wrap w-full"):
                    ui.icon("apps").style(f"color:{INDIGO}")
                    ui.label("Ensemble")


def shell():
    """Responsive header + drawer nav. Persistent sidebar above the
    breakpoint (desktop), collapsible overlay drawer below it (mobile) --
    handled by Quasar's drawer 'default' behavior, not hand-rolled CSS.
    Returns the main content column."""
    load_app_settings()  # refresh currency so Settings changes apply immediately
    inject_theme()

    with ui.header().classes("items-center justify-between px-3 py-2").style(
        f"background:{SURFACE}; border-bottom:1px solid {BORDER};"
    ):
        with ui.row().classes("items-center gap-1"):
            # NiceGUI defaults buttons to Quasar's text-primary class, whose
            # !important beats a plain inline color -- so ours needs one too.
            ui.button(on_click=lambda: drawer.toggle(), icon="menu").props("flat round dense").style(f"color:{TEXT} !important")
            ui.label("bal=nce").classes("text-lg font-bold").style(f"color:{TEXT}")
        # Right side of the header: jump to the other apps on this node.
        app_switcher()

    with ui.left_drawer().props("bordered breakpoint=1024 width=216").classes("p-3 gap-0.5").style(
        f"background:{SURFACE}"
    ) as drawer:
        async def _close_drawer_on_mobile():
            # Below the breakpoint the drawer is an overlay; after picking a page
            # it should get out of the way. On desktop it's the persistent
            # sidebar, so leave it open there.
            if await ui.context.client.run_javascript("window.innerWidth < 1024"):
                drawer.hide()

        enabled_modules = load_enabled_modules()

        def _nav_item(label, target, icon):
            with ui.link(target=target).classes(
                "drawer-nav-item flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg no-underline"
            ).style(f"color:{TEXT_DIM}").on("click", _close_drawer_on_mobile):
                ui.icon(icon).classes("text-base")
                ui.label(label).classes("text-sm")

        def _section_label(text):
            ui.label(text).classes("text-[10px] uppercase tracking-wider mt-3 mb-1 px-2.5").style(f"color:{TEXT_DIM}")

        # Grouped, compact nav: core up top, optional areas under small section
        # headers, Profile/Settings pinned below a divider. Sections with no
        # enabled items are omitted, so a lean install just shows the essentials.
        _bottom_routes = {"/profile", "/settings"}
        _core = [it for it in NAV_ITEMS if it[3] is None and it[1] not in _bottom_routes]
        _by_tier = {"money": [], "health": [], "power": []}
        for it in NAV_ITEMS:
            if it[3] and module_enabled(it[3], enabled_modules):
                _by_tier[MODULES[it[3]][1]].append(it)

        for label, target, icon, _mod in _core:
            _nav_item(label, target, icon)
        for _title, _key in [("Money", "money"), ("Health", "health"), ("More", "power")]:
            if not _by_tier[_key]:
                continue
            _section_label(_title)
            for label, target, icon, _mod in _by_tier[_key]:
                _nav_item(label, target, icon)
        ui.separator().classes("my-2 opacity-50")
        for it in NAV_ITEMS:
            if it[1] in _bottom_routes:
                _nav_item(it[0], it[1], it[2])

    async def _sync_drawer_to_screen_width():
        # NiceGUI's own open-on-desktop auto-detection (which the drawer's
        # default value=None normally relies on) checks a Quasar-internal CSS
        # class on connect, and that check can race with Quasar's own screen-
        # width detection, occasionally leaving the drawer collapsed on a
        # desktop-width first load. window.innerWidth has no such race.
        width = await ui.context.client.run_javascript("window.innerWidth")
        if width >= 1024:
            drawer.show()
        else:
            drawer.hide()

    ui.context.client.on_connect(_sync_drawer_to_screen_width)

    # --- mobile bottom navigation bar (hidden on desktop, where the sidebar
    # is persistent). Primary destinations get one-tap thumb access; "More"
    # opens the drawer for the full list. ---
    with ui.element("nav").classes(
        "bottom-nav fixed bottom-0 left-0 right-0 z-40 flex justify-around items-stretch lg:hidden"
    ):
        for label, target, icon, mod in BOTTOM_NAV_ITEMS:
            if not module_enabled(mod, enabled_modules):
                continue
            with ui.link(target=target).classes(
                "bottom-nav-item flex flex-col items-center justify-center flex-1 py-2 gap-0.5 no-underline"
            ):
                ui.icon(icon).classes("text-xl")
                ui.label(label).classes("text-[10px] leading-none")
        with ui.element("div").classes(
            "bottom-nav-item more-nav-item flex flex-col items-center justify-center flex-1 py-2 gap-0.5 cursor-pointer"
        ).on("click", lambda: drawer.toggle()):
            ui.icon("menu").classes("text-xl")
            ui.label("More").classes("text-[10px] leading-none")

    # extra bottom padding on mobile so the fixed bar never covers content
    content = ui.column().classes(f"{PAGE} pb-24 lg:pb-6")
    return content


def goal_row(label: str, value, info_key: str, unit: str, color: str = None, last: bool = False):
    """One nutrient target as a tidy settings-list row: a colour dot, the name,
    then a slim right-aligned editable value with its unit and the info popover.
    Reads as a list, not a grid of chunky boxes -- and the colour dots give the
    section some variety instead of another wall of identical fields."""
    color = color or INDIGO
    row = ui.row().classes("w-full items-center gap-3 no-wrap py-1.5")
    if not last:
        row.classes(f"border-b border-[{BORDER}]")
    with row:
        ui.element("div").classes("rounded-full shrink-0").style(f"width:7px;height:7px;background:{color}")
        ui.label(label).classes("text-sm flex-1 min-w-0 truncate")
        field = ui.number(value=value).props(
            'dense outlined input-class="text-right"').classes("w-24 shrink-0")
        ui.label(unit).classes("text-xs shrink-0 w-8 text-right").style(f"color:{TEXT_DIM}")
        with ui.element("div").classes("shrink-0"):
            nutrient_info_icon(info_key)
    return field


def card_box():
    return ui.column().classes(CARD)


def card_box_accent():
    """Accent 'hero' card -- same as card_box() but with a faint accent wash and
    a touch more lift, for the one 'look here first' card on a screen."""
    return ui.column().classes(CARD_ACCENT)


def page_header(title: str, subtitle: str = None, icon: str = None):
    """A designed page header: a circular accent chip + title (+ subtitle) and a
    short accent underline -- a bit of identity beyond plain bold text, and a
    deliberate round element to break up the rounded-rectangle grid."""
    with ui.row().classes("w-full items-center gap-3"):
        if icon:
            with ui.element("div").classes("flex items-center justify-center rounded-full shrink-0").style(
                    f"width:2.5rem;height:2.5rem;background:{INDIGO}1f;"):
                ui.icon(icon).classes("text-xl").style(f"color:{INDIGO}")
        with ui.column().classes("gap-0"):
            ui.label(title).classes("text-2xl font-bold leading-tight")
            if subtitle:
                ui.label(subtitle).classes("text-sm").style(f"color:{TEXT_DIM}")
    ui.element("div").classes("h-1 rounded-full mt-2 mb-1").style(f"width:2.75rem;background:{INDIGO}")


def summary_strip(stats, width_class: str = ""):
    """Unboxed headline figures sitting directly on the page (colour dot + small
    label + bold value), the airy top-of-page read introduced on Profile.
    `stats` is a list of (label, value, colour) tuples; falsy rows are skipped
    so callers can conditionally include figures inline."""
    stats = [s for s in stats if s]
    if not stats:
        return
    with ui.row().classes(f"w-full {width_class} items-center gap-x-8 gap-y-3 flex-wrap mb-3 mt-1"):
        for lbl, val, col in stats:
            with ui.row().classes("items-center gap-2"):
                ui.element("div").classes("rounded-full shrink-0").style(f"width:9px;height:9px;background:{col}")
                with ui.column().classes("gap-0"):
                    ui.label(lbl).classes("text-xs").style(f"color:{TEXT_DIM}")
                    ui.label(str(val)).classes("text-lg font-bold leading-tight")


def date_field(label_text: str = None, value=None):
    """
    Compact, Linear-style date field: a small text input showing the date,
    with a calendar icon that opens a popup date picker on demand -- rather
    than a permanently-expanded inline calendar grid. Returns the ui.input
    element; `.value` holds the ISO date string, same as a plain ui.date.
    """
    with ui.column().classes("gap-1"):
        if label_text:
            ui.label(label_text).classes("text-xs").style(f"color:{TEXT_DIM}")
        with ui.input(value=value).props("dense outlined").classes("w-full") as date_input:
            with ui.menu().props("no-parent-event").classes(f"bg-[{SURFACE}] border border-[{BORDER}] rounded-xl p-1") as menu:
                with ui.date(value=value).bind_value(date_input).props("color=primary").classes("rounded-xl") as picker:
                    with ui.row().classes("justify-between w-full px-2 pb-1"):
                        ui.button("Today", on_click=lambda: picker.set_value(date.today().isoformat())).props("flat dense no-caps").style(f"color:{TEXT_DIM}")
                        ui.button("Done", on_click=menu.close).props("flat dense no-caps").style(f"color:{INDIGO}")
            with date_input.add_slot("append"):
                ui.icon("calendar_today").classes("cursor-pointer text-sm").style(f"color:{TEXT_DIM}").on(
                    "click", menu.open
                )
    return date_input


def nutrient_tooltip(key: str) -> str:
    """Builds a fuller tooltip from NUTRIENT_INFO: summary plus the relevant
    too-little/too-much (for targets) or short/long-term (for limits) detail."""
    info = NUTRIENT_INFO.get(key)
    if not info:
        return ""
    parts = [info["summary"]]
    if info["kind"] == "target":
        parts.append(f"Too little: {info['too_little']}")
        parts.append(f"Too much: {info['too_much']}")
    else:
        parts.append(f"Short-term: {info['short_term']}")
        parts.append(f"Long-term: {info['long_term']}")
    return "  ".join(parts)


def nutrient_info_icon(key: str):
    """A small ⓘ that opens a compact, structured popover (tap or hover) with
    the nutrient's summary and its two labeled facts -- replacing the single
    bulky tooltip blob. Works on touch since it opens on click."""
    info = NUTRIENT_INFO.get(key)
    if not info:
        return
    icon = ui.icon("info").classes("text-sm cursor-pointer").style(f"color:{TEXT_DIM}")
    if info["kind"] == "target":
        facts = [("Too little", info["too_little"], AMBER), ("Too much", info["too_much"], RED)]
    else:
        facts = [("Short-term", info["short_term"], AMBER), ("Long-term", info["long_term"], RED)]
    with icon:
        with ui.menu().props("anchor='bottom middle' self='top middle'"):
            with ui.column().classes("p-3 gap-2").style("max-width:16rem"):
                ui.label(info["label"]).classes("text-sm font-semibold").style(f"color:{TEXT}")
                ui.label(info["summary"]).classes("text-xs leading-snug").style(f"color:{TEXT_DIM}")
                for lbl, text, col in facts:
                    with ui.row().classes("items-start gap-2 no-wrap"):
                        badge(lbl, col)
                        ui.label(text).classes("text-xs leading-snug").style(f"color:{TEXT_DIM}")


def progress_row(label: str, current: float, goal: float, unit: str, is_limit: bool = False,
                 info: str = None, info_key: str = None):
    """A labeled progress bar; for limits, going over goal turns red.
    Pass `info_key` (a NUTRIENT_INFO key) for the structured info popover, or
    `info` for a plain-text tooltip (legacy)."""
    current = current or 0
    goal = goal or 0
    pct = min((current / goal) * 100, 999) if goal else 0
    if is_limit:
        color = RED if current > goal else (AMBER if pct > 80 else EMERALD)
    else:
        color = EMERALD if pct >= 90 else (INDIGO if pct >= 40 else TEXT_DIM)

    with ui.column().classes("w-full gap-1"):
        with ui.row().classes("w-full justify-between items-center"):
            with ui.row().classes("items-center gap-1"):
                ui.label(label).classes("text-sm").style(f"color:{TEXT}")
                if info_key:
                    nutrient_info_icon(info_key)
                elif info:
                    ui.icon("info").classes("text-xs cursor-pointer").style(f"color:{TEXT_DIM}").tooltip(info)
            ui.label(f"{current:,.0f} / {goal:,.0f}{unit}").classes("text-xs").style(f"color:{TEXT_DIM}")
        with ui.element("div").classes("w-full rounded-full h-2").style(f"background:{SURFACE_2}"):
            ui.element("div").classes("rounded-full h-2").style(
                f"background:{color}; width:{min(pct,100)}%"
            )


def stat_card(title: str, value: str, subtitle: str = "", accent: str = None, icon: str = None):
    # accent defaults to the *live* INDIGO token (resolved here, not baked into
    # the signature at import time -- otherwise it freezes to the midnight theme).
    if accent is None:
        accent = INDIGO
    with card_box().classes("flex-1 min-w-[180px]"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            if icon:
                icon_chip(icon, accent, size="text-base")
            ui.label(title).classes("text-xs uppercase tracking-wide").style(f"color:{TEXT_DIM}")
        ui.label(value).classes("text-3xl font-bold").style(f"color:{accent}")
        if subtitle:
            ui.label(subtitle).classes("text-xs").style(f"color:{TEXT_DIM}")


# ---------------------------------------------------------------------------
# Shared design-system components. These define the app's visual language --
# icon-led headers, status pills, KPI tiles, thin meters, empty states -- so
# every page can be built from the same vocabulary rather than hand-styled.
# ---------------------------------------------------------------------------
def badge(text: str, color: str = None):
    """A small rounded status pill: colored text on a translucent tint of the
    same color. Used for statuses, urgency, counts, cadence labels, etc."""
    if color is None:  # resolve the live token, not the one baked at import
        color = TEXT_DIM
    ui.label(text).classes("text-xs px-2 py-0.5 rounded-full whitespace-nowrap font-medium").style(
        f"background:{color}22; color:{color};"
    )


def icon_chip(icon: str, color: str = None, size: str = "text-xl"):
    """A rounded, tinted square holding a single icon -- the leading glyph on
    section headers and KPI tiles."""
    if color is None:  # resolve the live token, not the one baked at import
        color = INDIGO
    with ui.element("div").classes("flex items-center justify-center rounded-xl shrink-0").style(
        f"background:{color}1f; width:2.25rem; height:2.25rem;"
    ):
        ui.icon(icon).classes(size).style(f"color:{color}")


def section_header(title: str, icon: str = None, icon_color: str = None,
                   count=None, subtitle: str = None, accent: str = None):
    """Standard card/section heading: optional icon chip, title (+ optional
    count pill and subtitle), and a right-aligned slot returned for callers
    that want to drop a control or figure on the far side. Use inside a card;
    add trailing content with `with section_header(...): ...`."""
    # Resolve tokens to their *live* values here. Baking them into the default
    # args freezes them to whatever theme was active at import (midnight), which
    # renders the title near-white on the light themes (cream/lavender).
    if icon_color is None:
        icon_color = INDIGO
    if accent is None:
        accent = TEXT
    with ui.row().classes("w-full items-center gap-3 no-wrap"):
        if icon:
            icon_chip(icon, icon_color)
        # min-w-0 + truncate so a long title/subtitle ellipsizes within the
        # space it has rather than growing and shoving the trailing controls
        # (which made the dashboard day-nav chevrons drift on narrow screens).
        with ui.column().classes("gap-0 min-w-0 flex-1"):
            with ui.row().classes("items-center gap-2 min-w-0 no-wrap w-full"):
                ui.label(title).classes("text-lg font-semibold leading-tight truncate").style(f"color:{accent}")
                if count is not None:
                    with ui.element("div").classes("shrink-0"):
                        badge(str(count), TEXT_DIM)
            if subtitle:
                ui.label(subtitle).classes("text-xs truncate w-full").style(f"color:{TEXT_DIM}")
        # trailing slot: the flex-1 title column above fills the space and
        # truncates, so this sits at the right with a fixed width. (No ml-auto --
        # an auto margin eats the free space before flex-grow, which stops the
        # title from truncating and lets it overlap this slot on narrow screens.)
        trailing = ui.row().classes("items-center gap-2 shrink-0")
    return trailing


def thin_meter(current: float, goal: float, color: str, height: str = "h-1.5"):
    """A slim rounded progress bar with no label -- for KPI tiles and compact
    inline meters. Caps the fill at 100% width."""
    current = current or 0
    goal = goal or 0
    pct = min((current / goal) * 100, 100) if goal else 0
    with ui.element("div").classes(f"w-full rounded-full {height} mt-1").style(f"background:{SURFACE_2}"):
        ui.element("div").classes(f"rounded-full {height}").style(f"background:{color}; width:{pct}%")


def ring_gauge(label: str, current: float, goal: float, unit: str, color: str, size: int = 108):
    """A donut gauge -- a coloured arc of current/goal around a faint track with
    the value in the centre and label + goal beneath. The dashboard's headline
    health read: rings rather than flat bars, and the round shape is a
    deliberate break from the app's rectangles."""
    current = current or 0
    goal = goal or 0
    pct = min(current / goal, 1.0) if goal else 0.0
    r = 42
    circ = 2 * 3.141592653589793 * r
    dash = circ * pct
    val = f"{current:,.0f}"
    goal_txt = f"of {goal:,.0f} {unit}" if goal else f"{unit} (no goal)"
    svg = f'''
      <svg viewBox="0 0 100 100" style="width:{size}px;height:{size}px">
        <circle cx="50" cy="50" r="{r}" fill="none" stroke="{BORDER}" stroke-width="8"/>
        <circle cx="50" cy="50" r="{r}" fill="none" stroke="{color}" stroke-width="8"
                stroke-linecap="round" stroke-dasharray="{dash:.2f} {circ - dash:.2f}"
                transform="rotate(-90 50 50)"/>
        <text x="50" y="47" text-anchor="middle" font-size="20" font-weight="700" fill="{TEXT}">{val}</text>
        <text x="50" y="64" text-anchor="middle" font-size="10" fill="{TEXT_DIM}">{unit}</text>
      </svg>'''
    with ui.column().classes("items-center gap-0.5"):
        ui.html(svg)
        ui.label(label).classes("text-sm font-semibold leading-tight")
        ui.label(goal_txt).classes("text-xs").style(f"color:{TEXT_DIM}")


def kpi_tile(label: str, value: str, icon: str, accent: str = None,
             sub: str = None, meter=None):
    """Compact headline metric: icon chip, small label, big value, optional
    sub-line and thin meter. `meter` is an optional (current, goal) tuple."""
    if accent is None:  # resolve the live token, not the one baked at import
        accent = INDIGO
    with ui.element("div").classes(
        f"surface-card flex-1 min-w-[150px] rounded-2xl p-3 sm:p-4 flex flex-col gap-1"
    ).style(f"background:{SURFACE}; border:1px solid {BORDER};"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            icon_chip(icon, accent, size="text-base")
            ui.label(label).classes("text-xs uppercase tracking-wide").style(f"color:{TEXT_DIM}")
        ui.label(value).classes("text-2xl sm:text-3xl font-bold leading-tight").style(f"color:{accent}")
        if sub:
            ui.label(sub).classes("text-xs").style(f"color:{TEXT_DIM}")
        if meter is not None:
            thin_meter(meter[0], meter[1], accent)


def empty_state(text: str, icon: str = "inbox"):
    """Consistent centered empty-state for lists with nothing to show."""
    with ui.column().classes("w-full items-center justify-center py-8 gap-2"):
        ui.icon(icon).classes("text-4xl").style(f"color:{BORDER}")
        ui.label(text).classes("text-sm text-center max-w-sm").style(f"color:{TEXT_DIM}")


def undo_banner(container, message: str, on_undo):
    """Show a dismissible 'deleted -- undo' bar in `container`.

    Quasar notification actions are serialized to JSON, so they cannot carry a
    Python callback; this renders a real element with a working button instead.
    """
    container.clear()
    with container:
        with ui.row().classes("w-full items-center gap-2 px-3 py-2 rounded-xl").style(
            f"background:{SURFACE_2}; border:1px solid {BORDER};"
        ):
            ui.icon("delete_outline").classes("text-base").style(f"color:{TEXT_DIM}")
            ui.label(message).classes("text-xs").style(f"color:{TEXT_DIM}")
            ui.space()

            def do_undo():
                on_undo()
                container.clear()

            ui.button("Undo", on_click=do_undo).props("flat dense no-caps").classes("text-xs")
            ui.button(icon="close", on_click=container.clear).props("flat round dense size=sm")


def segmented(label: str, options, value):
    """A labeled segmented (chip) selector for small fixed choice sets -- one
    tap with every option visible, instead of a dropdown you open and scroll.
    `options` is a list or a {value: label} dict; returns the toggle whose
    `.value` reads exactly like the ui.select it replaces."""
    with ui.column().classes("gap-1 w-full"):
        if label:
            ui.label(label).classes("text-xs").style(f"color:{TEXT_DIM}")
        toggle = ui.toggle(options, value=value).props(
            "no-caps unelevated spread dense toggle-color=primary"
        ).classes("seg-toggle w-full text-xs").style(
            f"border:1px solid {BORDER}; border-radius:10px; background:{SURFACE_2};"
        )
    return toggle


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def dashboard():
    today = date.today()
    now = datetime.now()
    yesterday = today - timedelta(days=1)

    # Time-aware greeting -- a reason to open at any hour. Morning gives a
    # yesterday recap + a nudge to start the day; midday a protein/lunch check;
    # evening a today recap. Keeps the dashboard current instead of a static title.
    with Session(engine) as session:
        _g = session.exec(select(NutrientGoals)).first() or NutrientGoals()
        _t_food = session.exec(select(FoodLog).where(FoodLog.date == today)).all()
        _t_spend = sum(t.amount for t in session.exec(select(Transaction).where(Transaction.date == today)).all())
        _y_food = session.exec(select(FoodLog).where(FoodLog.date == yesterday)).all()
        _y_spend = sum(t.amount for t in session.exec(select(Transaction).where(Transaction.date == yesterday)).all())
    _t_cal = sum(f.calories or 0 for f in _t_food)
    _y_cal = sum(f.calories or 0 for f in _y_food)
    _protein_now = sum(f.protein_g or 0 for f in _t_food)
    _h = now.hour
    if 5 <= _h < 12:
        greeting = "Good morning"
        if _y_spend or _y_cal:
            focus = f"Yesterday: {CUR}{_y_spend:,.0f} spent · {_y_cal:,.0f} kcal. Log breakfast to start the day."
        else:
            focus = "A fresh day — log a meal or an expense to get going."
    elif 12 <= _h < 18:
        greeting = "Good afternoon"
        if _g.protein_g and _protein_now < _g.protein_g:
            focus = f"{_protein_now:,.0f}g protein so far — {_g.protein_g - _protein_now:,.0f}g to go. Logged lunch?"
        elif _g.protein_g:
            focus = f"Protein goal already hit ({_protein_now:,.0f}g) — nice. {CUR}{_t_spend:,.0f} spent so far."
        else:
            focus = f"{CUR}{_t_spend:,.0f} spent so far today."
    else:
        greeting = "Good evening"
        focus = f"Today: {CUR}{_t_spend:,.0f} spent · {_t_cal:,.0f} kcal. Round off dinner and tomorrow's plan."
    with ui.column().classes("gap-0"):
        ui.label(greeting).classes("text-2xl font-bold leading-tight")
        ui.label(focus).classes("text-sm").style(f"color:{TEXT_DIM}")

    with Session(engine) as session:
        goals = session.exec(select(NutrientGoals)).first() or NutrientGoals()
        food_today = session.exec(select(FoodLog).where(FoodLog.date == today)).all()
        month_start, month_end = period_bounds("monthly", today)
        month_transactions = session.exec(
            select(Transaction).where(Transaction.date >= month_start, Transaction.date <= month_end)
        ).all()
        month_income = session.exec(
            select(Income).where(Income.date >= month_start, Income.date <= month_end)
        ).all()
        overall_budget = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711
        category_budgets = session.exec(select(BudgetTarget).where(BudgetTarget.category_id != None)).all()  # noqa: E711
        categories = {c.id: c.name for c in session.exec(select(Category)).all()}
        # "First run" = a genuinely fresh install (nothing logged yet). Drives the
        # welcome card below; auto-clears the moment anything is logged.
        first_run = (session.exec(select(Transaction)).first() is None
                     and session.exec(select(FoodLog)).first() is None)

    month_spend_by_category: dict = {}
    for t in month_transactions:
        month_spend_by_category[t.category_id] = month_spend_by_category.get(t.category_id, 0) + t.amount

    calories_today = sum(f.calories or 0 for f in food_today)  # KPI tile only; Today card recomputes per selected day
    spent_this_month = sum(t.amount for t in month_transactions)
    income_this_month = sum(i.amount for i in month_income)
    net_this_month = income_this_month - spent_this_month
    income_module = module_enabled("income")

    # --- First-run welcome: state the "why" and offer the first win, so a new
    # user understands the app before entering any data. Auto-hides once anything
    # is logged, so it never nags an established user. ---
    if first_run:
        with card_box_accent().classes("w-full"):
            ui.label("Welcome to Balance").classes("text-xl font-bold")
            ui.label("Track what you spend and what it does to your body — in one place.").classes(
                "text-sm").style(f"color:{TEXT_DIM}")
            ui.label(
                "Log one expense and one meal and the dashboard comes alive — you'll see how "
                "your money and your health line up. No lengthy setup: targets have sensible "
                "defaults you can tweak any time."
            ).classes("text-sm mt-2")
            with ui.row().classes("gap-2 flex-wrap mt-3"):
                ui.button("Add your first expense", icon="add",
                          on_click=lambda: ui.navigate.to("/add-transaction")).props("unelevated no-caps color=primary")
                ui.button("Log your first meal", icon="restaurant",
                          on_click=lambda: ui.navigate.to("/add-food")).props("unelevated no-caps color=primary")
            ui.label("This welcome disappears once you start logging.").classes(
                "text-xs mt-2").style(f"color:{TEXT_DIM}")

    # --- Quick actions: the primary "what do I do next" ---
    with ui.row().classes("w-full gap-2 flex-wrap mt-1 mb-1"):
        ui.button("Add expense", icon="add",
                  on_click=lambda: ui.navigate.to("/add-transaction")).props("unelevated no-caps color=primary")
        ui.button("Log meal", icon="restaurant",
                  on_click=lambda: ui.navigate.to("/add-food")).props("unelevated no-caps color=primary")
        if income_module:
            ui.button("Add income", icon="payments",
                      on_click=lambda: ui.navigate.to("/add-income")).props("outline no-caps color=primary")

    # --- Needs your attention: computed, verb-driven nudges (the actionable core) ---
    protein_today = sum(f.protein_g or 0 for f in food_today)
    days_left = max((month_end - today).days, 0)
    groceries_id = next((cid for cid, n in categories.items() if n == "Groceries"), None)
    grocery_budget = next((b for b in category_budgets if groceries_id and b.category_id == groceries_id), None)

    nudges = []  # (icon, text, color, cta_label|None, route|None)

    def _budget_nudge(label, spent, target, route):
        if not target:
            return
        if spent > target:
            nudges.append(("account_balance_wallet",
                           f"{label} {CUR}{spent:,.0f}/{CUR}{target:,.0f} — {CUR}{spent - target:,.0f} over budget",
                           RED, "Review", route))
        else:
            per_day = (target - spent) / max(days_left, 1)
            tail = (f", {days_left} days left — {CUR}{per_day:,.0f}/day to stay under"
                    if days_left else " — last day of the month")
            nudges.append(("account_balance_wallet", f"{label} {CUR}{spent:,.0f}/{CUR}{target:,.0f}{tail}",
                           AMBER if spent / target >= 0.8 else EMERALD, "Review", route))

    if grocery_budget:
        _budget_nudge("Groceries", month_spend_by_category.get(groceries_id, 0), grocery_budget.monthly_amount, "/transactions")
    elif overall_budget and overall_budget.monthly_amount:
        _budget_nudge("Budget", spent_this_month, overall_budget.monthly_amount, "/transactions")
    else:
        nudges.append(("savings", "Set a monthly budget to track your spending", INDIGO, "Set budget", "/profile"))

    if not food_today:
        nudges.append(("restaurant", "No meals logged today", INDIGO, "Log meal", "/add-food"))
    elif goals.protein_g and (goals.protein_g - protein_today) > 10:
        nudges.append(("fitness_center",
                       f"Protein {goals.protein_g - protein_today:,.0f}g short today "
                       f"({protein_today:,.0f}/{goals.protein_g:,.0f}g)",
                       AMBER, "Log meal", "/add-food"))

    _eat_out_ids = [cid for cid, n in categories.items() if n == "Eating Out"]
    _eat_out = sum(month_spend_by_category.get(cid, 0) for cid in _eat_out_ids)
    if _eat_out >= 20:
        with Session(engine) as session:
            _eat_out_cal = sum(f.calories or 0 for f in session.exec(
                select(FoodLog).where(FoodLog.date >= month_start, FoodLog.date <= month_end,
                                      FoodLog.eaten_out == True)).all())  # noqa: E712
        _cal_bit = f" ≈ {_eat_out_cal:,.0f} kcal from meals out" if _eat_out_cal > 0 else ""
        nudges.append(("restaurant_menu",
                       f"{CUR}{_eat_out:,.0f} on eating out this month{_cal_bit} — cooking more saves both",
                       AMBER, "See", "/transactions"))

    if module_enabled("subscriptions"):
        with Session(engine) as session:
            _subs = session.exec(select(Subscription).where(Subscription.active == True)).all()  # noqa: E712
        _due = [s for s in _subs if s.next_payment_date and today <= s.next_payment_date <= today + timedelta(days=7)]
        if _due:
            nudges.append(("autorenew",
                           f"{len(_due)} subscription(s) renew this week ({CUR}{sum(s.amount for s in _due):,.0f})",
                           AMBER, "View", "/subscriptions"))

    with card_box_accent().classes("w-full"):
        section_header("Needs your attention", icon="notifications_active", icon_color=AMBER)
        if not nudges:
            with ui.row().classes("items-center gap-2"):
                ui.icon("check_circle").classes("text-lg").style(f"color:{EMERALD}")
                ui.label("You're on track — nothing needs your attention.").classes("text-sm")
        for _icon, _text, _color, _cta, _route in nudges[:5]:
            with ui.row().classes("w-full items-center gap-3 py-1"):
                ui.icon(_icon).classes("text-lg shrink-0").style(f"color:{_color}")
                ui.label(_text).classes("text-sm flex-grow")
                if _cta and _route:
                    ui.button(_cta, on_click=lambda _, r=_route: ui.navigate.to(r)).props("flat dense no-caps color=primary")

    # Budget state used by the "This month" card below. (The old KPI headline
    # row was removed -- Calories duplicated the Today gauge, and Spent/Net
    # duplicated the "This month" card.)
    over_budget = bool(overall_budget and overall_budget.monthly_amount and spent_this_month > overall_budget.monthly_amount)
    has_budget = bool(overall_budget and overall_budget.monthly_amount)

    # --- Today: nutrition, what to watch, and water -- navigable day by day ---
    LIMIT_FIELDS = [
        ("Added sugar", "added_sugar_g", "sugar_limit_g", "g"),
        ("Saturated fat", "saturated_fat_g", "saturated_fat_limit_g", "g"),
        ("Trans fat", "trans_fat_g", "trans_fat_limit_g", "g"),
        ("Sodium", "sodium_mg", "sodium_limit_mg", "mg"),
        ("Alcohol", "alcohol_g", "alcohol_limit_g", "g"),
        ("Caffeine", "caffeine_mg", "caffeine_limit_mg", "mg"),
    ]
    view_state = {"date": today}
    today_card = card_box().classes("w-full")

    def shift_day(delta):
        new_date = view_state["date"] + timedelta(days=delta)
        if new_date <= today:  # never navigate into the future
            view_state["date"] = new_date
            render_today()

    def render_today():
        today_card.clear()
        sel = view_state["date"]
        is_today = sel == today
        with Session(engine) as session:
            foods = session.exec(select(FoodLog).where(FoodLog.date == sel)).all()
            waters = session.exec(select(WaterLog).where(WaterLog.date == sel)).all()

        cals = sum(f.calories or 0 for f in foods)
        protein = sum(f.protein_g or 0 for f in foods)
        carbs = sum(f.carbs_g or 0 for f in foods)
        fat = sum(f.fat_g or 0 for f in foods)
        limit_totals = {field: sum(getattr(f, field) or 0 for f in foods) for _, field, _, _ in LIMIT_FIELDS}
        water_ml = sum(w.amount_ml for w in waters)

        flagged = []
        for name, field, limit_key, unit in LIMIT_FIELDS:
            lim = getattr(goals, limit_key)
            cur = limit_totals[field]
            if not lim:
                continue
            if cur > lim:
                flagged.append((f"{name} {cur:,.0f}/{lim:,.0f}{unit}", RED))
            elif cur / lim >= 0.8:
                flagged.append((f"{name} {cur:,.0f}/{lim:,.0f}{unit}", AMBER))

        with today_card:
            hdr = section_header(
                format_date_header(sel), icon="wb_sunny", icon_color=INDIGO,
                subtitle=sel.strftime("%A, %d %B"),
            )
            with hdr:
                # Fixed control group so nothing shifts as you page days: the
                # "Today" shortcut always occupies its slot (just hidden when
                # you're already on today), and the chevrons stay put.
                today_btn = ui.button("Today", on_click=lambda: (view_state.update(date=today), render_today())).props("flat dense no-caps").classes("text-xs")
                ui.button(icon="chevron_left", on_click=lambda: shift_day(-1)).props("flat round dense").tooltip("Previous day")
                nxt = ui.button(icon="chevron_right", on_click=lambda: shift_day(1)).props("flat round dense")
                if is_today:
                    today_btn.style("visibility:hidden")
                    nxt.props("disable")
                else:
                    nxt.tooltip("Next day")

            with ui.grid().classes("w-full grid-cols-2 sm:grid-cols-4 gap-2 gap-y-4 mt-1 justify-items-center"):
                ring_gauge("Calories", cals, goals.calories, "kcal", INDIGO)
                ring_gauge("Protein", protein, goals.protein_g, "g", EMERALD)
                ring_gauge("Carbs", carbs, goals.carbs_g, "g", AMBER)
                ring_gauge("Fat", fat, goals.fat_g, "g", VIOLET)

            # Surface only the limits actually worth watching as pills, rather
            # than burying every limit in an always-collapsed expansion.
            ui.label("Things to watch").classes("text-xs uppercase tracking-wide mt-2").style(f"color:{TEXT_DIM}")
            if flagged:
                with ui.row().classes("w-full gap-2 flex-wrap"):
                    for text, color in flagged:
                        badge(text, color)
            else:
                with ui.row().classes("items-center gap-1"):
                    ui.icon("check_circle").classes("text-sm").style(f"color:{EMERALD}")
                    ui.label("Nothing over the limits." if not is_today else "Nothing over your limits today.").classes("text-xs").style(f"color:{TEXT_DIM}")
            with ui.expansion("All limits & caffeine-like substances").classes("w-full mt-1"):
                for name, field, limit_key, unit in LIMIT_FIELDS:
                    progress_row(name, limit_totals[field], getattr(goals, limit_key), unit, is_limit=True, info_key=limit_key)
                ui.separator().classes("my-2")
                ui.label(
                    "Not tracked with a daily total (no standard serving data), but worth being "
                    "mindful of if you consume them regularly:"
                ).classes("text-xs mb-1").style(f"color:{TEXT_DIM}")
                for sub in CAFFEINE_LIKE_SUBSTANCES:
                    with ui.row().classes("w-full gap-2 items-start py-1"):
                        ui.label(sub["name"]).classes("text-sm font-semibold w-24 shrink-0")
                        ui.label(sub["note"]).classes("text-xs").style(f"color:{TEXT_DIM}")

            ui.separator().classes("my-2")

            # --- water: log for today, read-only when reviewing a past day ---
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("water_drop").classes("text-lg").style(f"color:{SKY}")
                ui.label("Water").classes("text-sm font-semibold")
                ui.label(f"{water_ml:,.0f} / {(goals.water_ml or 0):,.0f} ml").classes("text-xs ml-auto").style(f"color:{TEXT_DIM}")
            thin_meter(water_ml, goals.water_ml, SKY)
            if is_today:
                with ui.grid().classes("w-full grid-cols-2 sm:grid-cols-4 gap-2 mt-1"):
                    for amount in [200, 330, 500, 750]:
                        ui.button(f"{amount}ml", icon="water_drop", on_click=lambda e, amt=amount: add_water(amt)).props(
                            "stack outline no-caps"
                        ).classes("py-2 text-xs").style(f"color:{SKY}; border-color:{SKY};")
                if waters:
                    ui.button("Undo last", icon="undo", on_click=undo_water).props("flat dense no-caps").classes("self-start")

    def add_water(amount_ml):
        with Session(engine) as session:
            session.add(WaterLog(date=today, amount_ml=amount_ml))
            session.commit()
        render_today()

    def undo_water():
        with Session(engine) as session:
            last = session.exec(
                select(WaterLog).where(WaterLog.date == today).order_by(WaterLog.id.desc())
            ).first()
            if last:
                session.delete(last)
                session.commit()
        render_today()

    render_today()

    # --- This month: income/spend breakdown and budget tracking ---
    with card_box().classes("w-full"):
        section_header("This month", icon="account_balance_wallet", icon_color=EMERALD,
                       subtitle=today.strftime("%B %Y"))
        _month_rows = []
        if income_module:
            _month_rows.append(("Income", f"{CUR}{income_this_month:,.2f}", EMERALD))
        _month_rows.append(("Spent", f"{CUR}{spent_this_month:,.2f}", AMBER))
        if income_module:
            _month_rows.append(("Net", f"{'+' if net_this_month >= 0 else '−'}{CUR}{abs(net_this_month):,.2f}",
                                EMERALD if net_this_month >= 0 else RED))
        with ui.row().classes("w-full gap-3 flex-wrap"):
            for lbl, val, col in _month_rows:
                with ui.column().classes("gap-0 flex-1 min-w-[90px]"):
                    ui.label(lbl).classes("text-xs").style(f"color:{TEXT_DIM}")
                    ui.label(val).classes("text-xl font-bold").style(f"color:{col}")
        if has_budget:
            ui.separator().classes("my-1")
            progress_row("Overall budget", spent_this_month, overall_budget.monthly_amount, f" {CUR}", is_limit=True)
            if category_budgets:
                with ui.expansion("Budget by category").classes("w-full mt-1"):
                    for cb in sorted(category_budgets, key=lambda b: categories.get(b.category_id, "")):
                        progress_row(
                            categories.get(cb.category_id, "Uncategorized"),
                            month_spend_by_category.get(cb.category_id, 0),
                            cb.monthly_amount, f" {CUR}", is_limit=True,
                        )

    # --- Cost per macro: the signature money x health crossover. Pantry items
    # carry both price and protein, so we can rank what gives the most protein
    # per pound -- the "eat well on a budget" insight no single-purpose app has.
    # Shown only when there's enough priced pantry data to rank. ---
    with Session(engine) as session:
        _pantry = session.exec(select(PantryItem)).all()
    protein_value = [
        (it.protein_g / it.price, it.name, it.calories)
        for it in _pantry
        if it.price and it.price > 0 and it.protein_g and it.protein_g > 0
    ]
    if len(protein_value) >= 2:
        protein_value.sort(key=lambda x: -x[0])
        best = protein_value[:3]
        worst = protein_value[-1]
        with card_box().classes("w-full"):
            section_header("Best value protein", icon="fitness_center", icon_color=EMERALD,
                           subtitle=f"Most protein per {CUR}1 in your pantry — handy for a budget-friendly bulk")
            for score, name, _cals in best:
                with ui.row().classes("w-full items-center gap-2 py-1"):
                    ui.label(name).classes("text-sm font-semibold flex-grow")
                    ui.label(f"{score:,.0f}g protein / {CUR}1").classes("text-sm").style(f"color:{EMERALD}")
            if worst not in best:
                ui.separator().classes("my-1")
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label(f"Worst value: {worst[1]}").classes("text-xs flex-grow").style(f"color:{TEXT_DIM}")
                    ui.label(f"{worst[0]:,.0f}g / {CUR}1").classes("text-xs").style(f"color:{AMBER}")

    # --- Insights: notable this-month-vs-last-month changes, computed not curated ---
    prev_month_start, prev_month_end = period_bounds("monthly", month_start - timedelta(days=1))
    with Session(engine) as session:
        prev_transactions = session.exec(
            select(Transaction).where(Transaction.date >= prev_month_start, Transaction.date <= prev_month_end)
        ).all()
    prev_spend_by_category: dict = {}
    for t in prev_transactions:
        prev_spend_by_category[t.category_id] = prev_spend_by_category.get(t.category_id, 0) + t.amount

    # pro-rate last month to the same number of elapsed days so mid-month
    # comparisons aren't automatically "down vs last month"
    elapsed = (today - month_start).days + 1
    prev_days = (prev_month_end - prev_month_start).days + 1
    prorate = min(elapsed / prev_days, 1.0)

    insights = []
    for cat_id, cur_amt in month_spend_by_category.items():
        prev_amt = prev_spend_by_category.get(cat_id, 0) * prorate
        if prev_amt < 10 and cur_amt < 10:
            continue
        delta = cur_amt - prev_amt
        if prev_amt > 0 and abs(delta) >= 15 and abs(delta) / prev_amt >= 0.25:
            name = categories.get(cat_id, "Uncategorized")
            pct = delta / prev_amt * 100
            if prev_amt < 25 or abs(pct) > 300:
                # tiny base makes percentages absurd ("up 1351%") -- use absolute phrasing
                text = (f"{name} {CUR}{abs(delta):,.0f} {'more' if delta > 0 else 'less'} than last month "
                        f"({CUR}{cur_amt:,.0f} vs {CUR}{prev_amt:,.0f})")
            else:
                text = (f"{name} {'up' if delta > 0 else 'down'} {abs(pct):.0f}% vs last month "
                        f"({CUR}{cur_amt:,.0f} vs {CUR}{prev_amt:,.0f})")
            insights.append((abs(delta), text, AMBER if delta > 0 else EMERALD))
    prev_total_prorated = sum(prev_spend_by_category.values()) * prorate
    if prev_total_prorated > 0:
        total_delta = spent_this_month - prev_total_prorated
        if abs(total_delta) / prev_total_prorated >= 0.15 and abs(total_delta) >= 30:
            pct = total_delta / prev_total_prorated * 100
            insights.append((abs(total_delta) * 10,  # weight overall change to the top
                             f"Overall spending {'up' if total_delta > 0 else 'down'} {abs(pct):.0f}% "
                             f"vs the same point last month", AMBER if total_delta > 0 else EMERALD))
    insights.sort(key=lambda x: -x[0])

    if insights:
        with card_box().classes("w-full"):
            section_header("Insights", icon="tips_and_updates", icon_color=AMBER,
                           subtitle="Notable changes vs the same point last month")
            for _, text, color in insights[:3]:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("trending_up" if color == AMBER else "trending_down").classes("text-base").style(f"color:{color}")
                    ui.label(text).classes("text-sm")

    # --- Savings: monthly net (income − spending) for the trailing 6 months ---
    month_keys = []
    y, m = today.year, today.month
    for _ in range(6):
        month_keys.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    month_keys.reverse()
    six_start = date(month_keys[0][0], month_keys[0][1], 1)
    with Session(engine) as session:
        tx6 = session.exec(select(Transaction).where(Transaction.date >= six_start)).all()
        inc6 = session.exec(select(Income).where(Income.date >= six_start)).all()
    spend_by_m, inc_by_m = {}, {}
    for t in tx6:
        spend_by_m[(t.date.year, t.date.month)] = spend_by_m.get((t.date.year, t.date.month), 0) + t.amount
    for i in inc6:
        inc_by_m[(i.date.year, i.date.month)] = inc_by_m.get((i.date.year, i.date.month), 0) + i.amount
    net_series = [round(inc_by_m.get(k, 0) - spend_by_m.get(k, 0), 2) for k in month_keys]

    if any(inc_by_m.values()) or any(spend_by_m.values()):
        saved_total = sum(net_series)
        cumulative, _run = [], 0.0
        for v in net_series:
            _run += v
            cumulative.append(round(_run, 2))
        with card_box().classes("w-full"):
            hdr = section_header("Savings", icon="savings", icon_color=EMERALD,
                                 subtitle="Monthly net (bars) and how it adds up (line), last 6 months")
            with hdr:
                badge(f"{'+' if saved_total >= 0 else '−'}{CUR}{abs(saved_total):,.0f} over 6 months",
                      EMERALD if saved_total >= 0 else RED)
            ui.echart({
                "backgroundColor": "transparent",
                "grid": {"left": 55, "right": 55, "top": 30, "bottom": 28},
                "legend": {"top": 0, "textStyle": {"color": TEXT_DIM, "fontSize": 10},
                           "itemWidth": 14, "itemHeight": 8},
                "xAxis": {
                    "type": "category",
                    "data": [date(k[0], k[1], 1).strftime("%b") for k in month_keys],
                    "axisLine": {"lineStyle": {"color": BORDER}},
                    "axisLabel": {"color": TEXT_DIM, "fontSize": 10},
                },
                "yAxis": [
                    {"type": "value", "axisLine": {"show": False},
                     "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                     "splitLine": {"lineStyle": {"color": BORDER}}},
                    {"type": "value", "axisLine": {"show": False},
                     "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                     "splitLine": {"show": False}},
                ],
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "series": [
                    {
                        "name": "Monthly net", "type": "bar",
                        "data": [
                            {"value": v, "itemStyle": {"color": EMERALD if v >= 0 else RED, "borderRadius": [3, 3, 0, 0]}}
                            for v in net_series
                        ],
                        "markLine": {
                            "silent": True, "symbol": "none",
                            "lineStyle": {"color": TEXT_DIM, "type": "dashed"},
                            "label": {"show": False},
                            "data": [{"yAxis": 0}],
                        },
                    },
                    {
                        "name": "Total saved", "type": "line", "yAxisIndex": 1,
                        "data": cumulative, "smooth": True, "symbolSize": 5,
                        "lineStyle": {"color": INDIGO, "width": 3},
                        "itemStyle": {"color": INDIGO},
                        "areaStyle": {"color": "rgba(99,102,241,0.08)"},
                    },
                ],
            }).classes("w-full h-52")

    # --- habit streaks ---
    from backend.streaks import compute_streaks
    streaks = compute_streaks(today)
    if any(s["streak"] > 0 for s in streaks):
        with card_box().classes("w-full"):
            section_header("Streaks", icon="local_fire_department", icon_color=AMBER,
                           subtitle="Consecutive days hitting your goals -- keep them going")
            with ui.row().classes("w-full gap-3 flex-wrap"):
                for s in streaks:
                    if s["streak"] <= 0:
                        continue
                    with ui.column().classes("items-center gap-0 px-4 py-2 rounded-xl").style(f"background:{SURFACE_2}"):
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("local_fire_department").classes("text-base").style(f"color:{AMBER}")
                            ui.label(str(s["streak"])).classes("text-xl font-bold leading-none").style(f"color:{TEXT}")
                        ui.label(f"day{'s' if s['streak'] != 1 else ''}").classes("text-[10px]").style(f"color:{TEXT_DIM}")
                        ui.label(s["label"]).classes("text-xs").style(f"color:{TEXT_DIM}")

    # --- Overview: spending & nutrition over a chosen window (centerpiece) ---
    with card_box().classes("w-full"):
        section_header("Overview", icon="insights", icon_color=VIOLET,
                       subtitle="Spending & nutrition over your chosen window")
        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            period_select = ui.select(
                {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "6month": "6 Months",
                 "yearly": "1 Year", "custom": "Custom range…"},
                value="monthly", label="Period",
            ).props("dense options-dense").classes("w-40")
            date_input = date_field(value=today.isoformat())
            with ui.row().classes("items-center gap-3 flex-wrap") as custom_row:
                from_input = date_field("From", value=(today - timedelta(days=30)).isoformat())
                to_input = date_field("To", value=today.isoformat())
            custom_row.set_visibility(False)

        inner_card = f"bg-[{SURFACE_2}] border border-[{BORDER}] rounded-2xl p-3 sm:p-4 gap-3 w-full"
        trend_card = ui.column().classes(inner_card + " mt-1")
        with ui.grid().classes("w-full grid-cols-1 lg:grid-cols-2 gap-4"):
            expense_card = ui.column().classes(inner_card)
            nutrition_card = ui.column().classes(inner_card)

        def refresh():
            period = period_select.value
            ref_date = date.fromisoformat(date_input.value)
            is_custom = period == "custom"
            custom_row.set_visibility(is_custom)
            date_input.set_visibility(not is_custom)
            custom_range = None
            if is_custom and from_input.value and to_input.value:
                custom_range = (date.fromisoformat(from_input.value), date.fromisoformat(to_input.value))
            render_amount_trend(trend_card, Transaction, Transaction.date, "Spending trend",
                                "show_chart", AMBER, period, ref_date,
                                empty_hint="No spending recorded in this period.", custom_range=custom_range)
            render_expenses(expense_card, period, ref_date, custom_range=custom_range)
            render_nutrition(nutrition_card, period, ref_date, goals, custom_range=custom_range)

        period_select.on_value_change(lambda e: refresh())
        date_input.on_value_change(lambda e: refresh())
        from_input.on_value_change(lambda e: refresh())
        to_input.on_value_change(lambda e: refresh())
        refresh()


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


def period_delta_badge(current, previous, higher_is_worse=True, neutral=False):
    """Render a small 'vs previous period' change pill next to a headline
    figure. Coloring reflects whether the direction is good or bad for that
    metric (spending up = bad; income up = good); pass neutral=True for
    metrics where neither direction is inherently good or bad (e.g. calories)."""
    if not previous:
        return
    change = (current - previous) / previous * 100
    if abs(change) < 0.5:
        badge("≈ same as previous", TEXT_DIM)
        return
    up = change > 0
    arrow = "▲" if up else "▼"
    if neutral:
        color = TEXT_DIM
    else:
        is_bad = up if higher_is_worse else not up
        color = AMBER if is_bad else EMERALD
    badge(f"{arrow} {abs(change):.0f}% vs previous", color)


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


def render_expenses(container, period, ref_date, custom_range=None):
    container.clear()
    start, end = resolve_window(period, ref_date, Transaction, Transaction.date, custom_range)
    with Session(engine) as session:
        transactions = session.exec(
            select(Transaction).where(Transaction.date >= start, Transaction.date <= end)
        ).all()
        categories = {c.id: c.name for c in session.exec(select(Category)).all()}

    total = sum(t.amount for t in transactions)
    num_days = (end - start).days + 1
    daily_avg = total / num_days

    prev_total = None
    pw = previous_window(period, start, num_days)
    if pw:
        prev_total = _period_total(Transaction, "amount", Transaction.date, *pw)

    by_category: dict = {}
    for t in transactions:
        name = categories.get(t.category_id, "Uncategorized")
        by_category[name] = by_category.get(name, 0) + t.amount

    with container:
        section_header("Expenses", icon="shopping_cart", icon_color=AMBER,
                       subtitle=friendly_range(start, end, period))
        with ui.row().classes("gap-8 mt-1 items-end"):
            with ui.column().classes("gap-0"):
                ui.label("Total").classes("text-xs").style(f"color:{TEXT_DIM}")
                total_label = ui.label(f"{CUR}{total:,.2f}").classes("text-2xl font-bold")
            with ui.column().classes("gap-0"):
                ui.label("Daily average").classes("text-xs").style(f"color:{TEXT_DIM}")
                daily_avg_label = ui.label(f"{CUR}{daily_avg:,.2f}").classes("text-2xl font-bold")
        if prev_total is not None:
            with ui.row().classes("mt-1"):
                period_delta_badge(total, prev_total, higher_is_worse=True)

        if by_category:
            sorted_items = sorted(by_category.items(), key=lambda x: -x[1])

            def recompute_from_legend(e):
                # e.args is the {category_name: is_selected} map ECharts sends
                # when a legend entry is toggled. Recompute the headline total
                # and daily average from only the still-selected categories, so
                # excluding e.g. rent updates the numbers, not just the pie.
                selected = (e.args or {}).get("selected", {})
                shown_total = sum(amt for name, amt in by_category.items() if selected.get(name, True))
                total_label.set_text(f"{CUR}{shown_total:,.2f}")
                daily_avg_label.set_text(f"{CUR}{shown_total / num_days:,.2f}")

            chart = ui.echart({
                "backgroundColor": "transparent",
                "color": CHART_PALETTE,
                "tooltip": {"trigger": "item"},
                "legend": {
                    "type": "scroll", "bottom": 0, "left": "center",
                    "textStyle": {"color": TEXT_DIM, "fontSize": 11}, "itemWidth": 10, "itemHeight": 10,
                    "pageIconColor": TEXT_DIM, "pageIconInactiveColor": BORDER,
                    "pageTextStyle": {"color": TEXT_DIM},
                },
                "series": [{
                    "type": "pie", "radius": ["42%", "66%"], "center": ["50%", "43%"],
                    "data": [{"value": round(amt, 2), "name": name} for name, amt in sorted_items],
                    "label": {"show": False},
                    "itemStyle": {"borderColor": SURFACE, "borderWidth": 2},
                }],
            }).classes("w-full h-64 mt-2")
            chart.on("chart:legendselectchanged", recompute_from_legend,
                     js_handler="(e) => emit({selected: e.selected})")
            ui.label("Tap a category to include/exclude it from the total.").classes(
                "text-xs mt-1"
            ).style(f"color:{TEXT_DIM}")
        else:
            empty_state("No spending recorded in this period.", "shopping_cart")


def render_amount_trend(container, model, date_col, title, icon, color, period, ref_date,
                        empty_hint="Nothing recorded in this period.", custom_range=None):
    """Full-width bar chart of a money series per sub-bucket across the window
    -- per day for short windows, per month for long ones -- with a dashed
    average line. Reusable for spending (Transaction) and income (Income),
    since both share `.date` and `.amount`."""
    container.clear()
    start, end = resolve_window(period, ref_date, model, date_col, custom_range)
    with Session(engine) as session:
        rows = session.exec(select(model).where(date_col >= start, date_col <= end)).all()

    span_days = (end - start).days + 1
    with container:
        section_header(title, icon=icon, icon_color=color, subtitle=friendly_range(start, end, period))
        if span_days <= 1:
            empty_state("Pick a longer period to see a trend.", icon)
            return
        if not rows:
            empty_state(empty_hint, icon)
            return

        daily = span_days <= 31
        labels, values = [], []
        if daily:
            by_day: dict = {}
            for r in rows:
                by_day[r.date] = by_day.get(r.date, 0) + r.amount
            d = start
            while d <= end:
                labels.append(d.strftime("%a") if span_days <= 7 else str(d.day))
                values.append(round(by_day.get(d, 0), 2))
                d += timedelta(days=1)
        else:
            by_month: dict = {}
            for r in rows:
                key = (r.date.year, r.date.month)
                by_month[key] = by_month.get(key, 0) + r.amount
            multi_year = start.year != end.year
            y, m = start.year, start.month
            while (y, m) <= (end.year, end.month):
                lbl = date(y, m, 1).strftime("%b %y") if multi_year else date(y, m, 1).strftime("%b")
                labels.append(lbl)
                values.append(round(by_month.get((y, m), 0), 2))
                m += 1
                if m > 12:
                    m, y = 1, y + 1

        rotate = 45 if len(labels) > 14 else 0
        ui.echart({
            "backgroundColor": "transparent",
            "grid": {"left": 55, "right": 15, "top": 15, "bottom": 45 if rotate else 28},
            "xAxis": {
                "type": "category", "data": labels,
                "axisLine": {"lineStyle": {"color": BORDER}},
                "axisLabel": {"color": TEXT_DIM, "fontSize": 10, "rotate": rotate},
            },
            "yAxis": {
                "type": "value", "axisLine": {"show": False},
                "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                "splitLine": {"lineStyle": {"color": BORDER}},
            },
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "series": [{
                "type": "bar", "data": values,
                "itemStyle": {"color": color, "borderRadius": [3, 3, 0, 0]},
                "markLine": {
                    "silent": True, "symbol": "none",
                    "lineStyle": {"color": TEXT_DIM, "type": "dashed"},
                    "label": {"color": TEXT_DIM, "fontSize": 10, "formatter": "avg"},
                    "data": [{"type": "average"}],
                },
            }],
        }).classes("w-full h-48")


def render_income_summary(container, period, ref_date):
    container.clear()
    with Session(engine) as session:
        if period == "all_time":
            earliest = session.exec(select(Income).order_by(Income.date)).first()
            start = earliest.date if earliest else date.today()
            end = date.today()
        else:
            start, end = period_bounds(period, ref_date)
        entries = session.exec(
            select(Income).where(Income.date >= start, Income.date <= end)
        ).all()

    total = sum(i.amount for i in entries)
    num_days = (end - start).days + 1
    daily_avg = total / num_days

    prev_total = None
    if period != "all_time":
        prev_start, prev_end = period_bounds(period, start - timedelta(days=1))
        prev_total = _period_total(Income, "amount", Income.date, prev_start, prev_end)

    by_source: dict = {}
    for i in entries:
        by_source[i.source] = by_source.get(i.source, 0) + i.amount

    with container:
        section_header("Income", icon="payments", icon_color=EMERALD,
                       subtitle=friendly_range(start, end, period))
        with ui.row().classes("gap-8 mt-1 items-end"):
            with ui.column().classes("gap-0"):
                ui.label("Total").classes("text-xs").style(f"color:{TEXT_DIM}")
                ui.label(f"{CUR}{total:,.2f}").classes("text-2xl font-bold").style(f"color:{EMERALD}")
            with ui.column().classes("gap-0"):
                ui.label("Daily average").classes("text-xs").style(f"color:{TEXT_DIM}")
                ui.label(f"{CUR}{daily_avg:,.2f}").classes("text-2xl font-bold")
        if prev_total is not None:
            with ui.row().classes("mt-1"):
                period_delta_badge(total, prev_total, higher_is_worse=False)

        if by_source:
            sorted_items = sorted(by_source.items(), key=lambda x: -x[1])
            ui.echart({
                "backgroundColor": "transparent",
                "color": CHART_PALETTE,
                "tooltip": {"trigger": "item"},
                "legend": {
                    "type": "scroll", "bottom": 0, "left": "center",
                    "textStyle": {"color": TEXT_DIM, "fontSize": 11}, "itemWidth": 10, "itemHeight": 10,
                    "pageIconColor": TEXT_DIM, "pageIconInactiveColor": BORDER,
                    "pageTextStyle": {"color": TEXT_DIM},
                },
                "series": [{
                    "type": "pie", "radius": ["42%", "66%"], "center": ["50%", "43%"],
                    "data": [{"value": round(amt, 2), "name": name} for name, amt in sorted_items],
                    "label": {"show": False},
                    "itemStyle": {"borderColor": SURFACE, "borderWidth": 2},
                }],
            }).classes("w-full h-64 mt-2")
        else:
            empty_state("No income logged in this period.", "payments")


def render_nutrition(container, period, ref_date, goals, custom_range=None):
    container.clear()
    start, end = resolve_window(period, ref_date, FoodLog, FoodLog.date, custom_range)
    with Session(engine) as session:
        entries = session.exec(
            select(FoodLog).where(FoodLog.date >= start, FoodLog.date <= end)
        ).all()

    num_days = (end - start).days + 1
    totals = {field: 0.0 for field in NUTRIENT_FIELDS}
    for e in entries:
        for field in NUTRIENT_FIELDS:
            value = getattr(e, field)
            if value is not None:
                totals[field] += value
    averages = {field: totals[field] / num_days for field in NUTRIENT_FIELDS}

    prev_avg_cal = None
    pw = previous_window(period, start, num_days)
    if pw:
        prev_days = (pw[1] - pw[0]).days + 1
        prev_total_cal = _period_total(FoodLog, "calories", FoodLog.date, *pw)
        prev_avg_cal = prev_total_cal / prev_days if prev_days else None

    with container:
        section_header("Nutrition", icon="restaurant", icon_color=INDIGO,
                       subtitle=friendly_range(start, end, period))
        with ui.row().classes("gap-8 mt-1 items-end"):
            with ui.column().classes("gap-0"):
                ui.label("Total calories").classes("text-xs").style(f"color:{TEXT_DIM}")
                ui.label(f"{totals['calories']:,.0f} kcal").classes("text-2xl font-bold")
            with ui.column().classes("gap-0"):
                ui.label("Daily average").classes("text-xs").style(f"color:{TEXT_DIM}")
                ui.label(f"{averages['calories']:,.0f} kcal").classes("text-2xl font-bold")
        if prev_avg_cal:
            with ui.row().classes("mt-1"):
                period_delta_badge(averages["calories"], prev_avg_cal, neutral=True)

        if entries:
            macro_goals = [goals.protein_g or 0, goals.carbs_g or 0, goals.fat_g or 0]
            macro_actuals = [round(averages["protein_g"], 1), round(averages["carbs_g"], 1), round(averages["fat_g"], 1)]
            ui.echart({
                "backgroundColor": "transparent",
                "color": [INDIGO, SURFACE_2],
                "grid": {"left": 55, "right": 20, "top": 30, "bottom": 20},
                "legend": {"data": ["Daily avg", "Goal"], "textStyle": {"color": TEXT_DIM, "fontSize": 11}, "top": 0},
                "xAxis": {
                    "type": "value", "axisLine": {"show": False},
                    "axisLabel": {"color": TEXT_DIM}, "splitLine": {"lineStyle": {"color": BORDER}},
                },
                "yAxis": {
                    "type": "category", "data": ["Protein", "Carbs", "Fat"],
                    "axisLine": {"lineStyle": {"color": BORDER}}, "axisLabel": {"color": TEXT_DIM},
                },
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "series": [
                    {"name": "Daily avg", "type": "bar", "data": macro_actuals, "itemStyle": {"color": INDIGO, "borderRadius": [0, 4, 4, 0]}},
                    {"name": "Goal", "type": "bar", "data": macro_goals, "itemStyle": {"color": SURFACE_2, "borderRadius": [0, 4, 4, 0]}},
                ],
            }).classes("w-full h-64 mt-2")

            rows = [
                {"nutrient": label, "total": f"{totals[field]:,.1f}{unit}", "daily_avg": f"{averages[field]:,.1f}{unit}"}
                for field, label, unit in [
                    ("fiber_g", "Fiber", "g"), ("sugar_g", "Sugar", "g"), ("sodium_mg", "Sodium", "mg"),
                ]
            ]
            with ui.expansion("Fiber, sugar, sodium").classes("w-full mt-1"):
                ui.table(
                    columns=[
                        {"name": "nutrient", "label": "Nutrient", "field": "nutrient"},
                        {"name": "total", "label": "Total", "field": "total"},
                        {"name": "daily_avg", "label": "Daily avg", "field": "daily_avg"},
                    ],
                    rows=rows,
                ).classes("w-full").props(f"{'dark ' if THEME_DARK else ''}flat dense")
        else:
            empty_state("No food logged in this period.", "restaurant")


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


def render_expiry_badge(exp_date):
    """Render a small colored pill for an item's expiry, if it has one."""
    meta = expiry_meta(exp_date)
    if not meta:
        return
    label, color = meta
    badge(label, color)


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


# ---------------------------------------------------------------------------
# Add / list transactions
# ---------------------------------------------------------------------------
def render_add_transaction_form(on_saved=None):
    """Builds the add-transaction form in whatever container is currently
    active. Reused by both the standalone /add-transaction page and the
    Add tab on the merged /transactions page."""
    with Session(engine) as session:
        categories = session.exec(select(Category)).all()
        all_transactions = session.exec(select(Transaction)).all()
    history_map = build_history_map(all_transactions)
    category_options = {c.id: _category_label(c, categories) for c in categories}
    name_to_id = {c.name: c.id for c in categories}
    id_to_short = {c.id: c.name for c in categories}
    # most-used categories for quick-pick chips (empty until there's history)
    _cat_counts = Counter(t.category_id for t in all_transactions if t.category_id)
    top_category_ids = [cid for cid, _ in _cat_counts.most_common(5)]

    with card_box().classes("w-full max-w-xl"):
        section_header("Add Transaction", icon="add_shopping_cart", icon_color=AMBER)

        with ui.expansion("Attach receipt photo (optional)", icon="camera_alt").classes("w-full mb-1"):
            ui.label(
                "Just keeps a copy for your own reference -- nothing is read automatically. "
                "Type the merchant/amount/date yourself while looking at it."
            ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")
            receipt_photo_path = {"value": None}
            receipt_preview_container = ui.column().classes("w-full")
            receipt_status = ui.label().classes("text-xs")

            async def handle_receipt_upload(e):
                try:
                    image_bytes = await _read_upload_bytes(e)
                    filename = f"{uuid.uuid4().hex}.jpg"
                    dest_path = os.path.join(RECEIPTS_DIR, filename)
                    with open(dest_path, "wb") as f:
                        f.write(image_bytes)
                    receipt_photo_path["value"] = filename
                    receipt_status.set_text("Photo attached.")
                    receipt_status.style(f"color:{EMERALD}")
                    receipt_preview_container.clear()
                    with receipt_preview_container:
                        ui.image(f"/receipt-images/{filename}").classes("w-full max-w-xs rounded-lg mt-1")
                except Exception as exc:
                    receipt_status.set_text(f"Couldn't save that photo: {exc}")
                    receipt_status.style(f"color:{RED}")
                try:
                    upload_widget.reset()
                except Exception:
                    pass

            def clear_receipt_photo():
                receipt_photo_path["value"] = None
                receipt_status.set_text("")
                receipt_preview_container.clear()
                try:
                    upload_widget.reset()
                except Exception:
                    pass

            upload_widget = ui.upload(on_upload=handle_receipt_upload, auto_upload=True, max_files=1).props(
                'accept="image/*" capture="environment"'
            ).classes("max-w-full")
            ui.button("Remove photo", icon="close", on_click=clear_receipt_photo).props("flat dense no-caps").classes("mt-1")

        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
            date_input = date_field("Date", value=date.today().isoformat())
            merchant_input = ui.input(label="Merchant").props("dense").classes("w-full")

        payment_input = segmented(
            "Payment method",
            {"Card": "Card", "Cash": "Cash", "Bank Transfer": "Transfer", "Other": "Other"},
            "Card",
        )
        tag_select = ui.select(TAG_OPTIONS, value="", label="Tag (context)").props("dense options-dense").classes("w-full mt-2")

        split_toggle = ui.switch("Split into multiple categorized items", value=False).props("dense color=primary").classes("mt-2")
        split_help = ui.label(
            "e.g. one supermarket trip that covered both groceries and a book -- each item "
            "gets its own category and becomes its own transaction, sharing this date/merchant."
        ).classes("text-xs -mt-1 mb-1").style(f"color:{TEXT_DIM}")

        # --- single-amount mode (default) -- amount is the headline field ---
        with ui.column().classes("w-full gap-1") as single_amount_section:
            # Caption above (not a floating label): the big text-2xl value would
            # otherwise overlap a floating field label.
            ui.label("Amount").classes("text-xs").style(f"color:{TEXT_DIM}")
            amount_input = ui.number(value=0, format="%.2f").props(
                f'prefix="{CUR}" input-class="text-2xl font-bold"'
            ).classes("w-full")
            category_select = ui.select(category_options, label="Category", with_input=True).props("dense options-dense").classes("w-full")

            if top_category_ids:
                with ui.row().classes("w-full gap-1 flex-wrap items-center mt-1"):
                    ui.label("Quick pick:").classes("text-xs").style(f"color:{TEXT_DIM}")
                    for _cid in top_category_ids:
                        ui.button(
                            id_to_short.get(_cid, "?"),
                            on_click=lambda _, cid=_cid: category_select.set_value(cid),
                        ).props("flat dense no-caps size=sm").classes("text-xs")

            def _suggest_category_from_merchant():
                if category_select.value:  # don't override a category already chosen
                    return
                guess = guess_category_id(merchant_input.value, name_to_id, history_map)
                if guess is not None:
                    category_select.value = guess
            merchant_input.on("blur", lambda e: _suggest_category_from_merchant())

        # --- split-into-items mode ---
        with ui.column().classes("w-full gap-2") as items_section:
            items_container = ui.column().classes("w-full gap-2")
            item_rows = []

            def update_items_total():
                total = sum((r["amount"].value or 0) for r in item_rows)
                items_total_label.set_text(f"Items total: {CUR}{total:,.2f}")

            def remove_item_row(entry):
                entry["row"].delete()
                item_rows.remove(entry)
                update_items_total()

            def add_item_row(amount=0.0, description=""):
                with items_container:
                    row_element = ui.row().classes("w-full items-end gap-2")
                with row_element:
                    desc_input = ui.input(label="Item", value=description).props("dense").classes("flex-grow")
                    amt_input = ui.number(label=f"{CUR}", value=amount, format="%.2f").props("dense").classes("w-24")
                    amt_input.on_value_change(lambda e: update_items_total())
                    cat_select = ui.select(category_options, label="Category", with_input=True).props("dense options-dense").classes("flex-grow")
                    entry = {"row": row_element, "description": desc_input, "amount": amt_input, "category": cat_select}
                    ui.button(icon="close", on_click=lambda: remove_item_row(entry)).props("flat round dense color=red")
                item_rows.append(entry)
                update_items_total()

            items_total_label = ui.label(f"Items total: {CUR}0.00").classes("text-sm font-semibold mt-1")
            ui.button("+ Add item", icon="add", on_click=lambda: add_item_row()).props("flat dense no-caps")

        def update_mode_visibility():
            single_amount_section.set_visibility(not split_toggle.value)
            items_section.set_visibility(split_toggle.value)
            split_help.set_visibility(split_toggle.value)  # only relevant in split mode

        split_toggle.on_value_change(lambda e: update_mode_visibility())
        update_mode_visibility()

        notes_input = ui.textarea(label="Notes").props("dense").classes("w-full mt-1")
        result_label = ui.label().style(f"color:{EMERALD}")

        def submit():
            with Session(engine) as session:
                if split_toggle.value:
                    rows_to_save = [r for r in item_rows if (r["amount"].value or 0) > 0]
                    if not rows_to_save:
                        result_label.set_text("Add at least one item with an amount first.")
                        result_label.style(f"color:{RED}")
                        return
                    for r in rows_to_save:
                        session.add(Transaction(
                            date=date.fromisoformat(date_input.value),
                            amount=r["amount"].value or 0,
                            merchant=merchant_input.value,
                            category_id=r["category"].value,
                            payment_method=payment_input.value,
                            tag=tag_select.value or None,
                            notes=r["description"].value or notes_input.value,
                            receipt_image_path=receipt_photo_path["value"],
                        ))
                    session.commit()
                    result_label.set_text(f"Saved {len(rows_to_save)} transactions!")
                    for entry in list(item_rows):
                        entry["row"].delete()
                    item_rows.clear()
                    update_items_total()
                    split_toggle.set_value(False)
                else:
                    t = Transaction(
                        date=date.fromisoformat(date_input.value),
                        amount=amount_input.value or 0,
                        merchant=merchant_input.value,
                        category_id=category_select.value,
                        payment_method=payment_input.value,
                        tag=tag_select.value or None,
                        notes=notes_input.value,
                        receipt_image_path=receipt_photo_path["value"],
                    )
                    session.add(t)
                    session.commit()
                    result_label.set_text("Saved!")
                    result_label.style(f"color:{EMERALD}")
                    amount_input.value = 0

            merchant_input.value = ""
            notes_input.value = ""
            receipt_photo_path["value"] = None
            receipt_preview_container.clear()
            receipt_status.set_text("")
            if on_saved:
                on_saved()

        ui.button("Save transaction", on_click=submit).props("color=primary unelevated")


def add_transaction_page():
    render_add_transaction_form()


def transactions_page():
    page_header("Transactions", "Every expense, searchable and categorised.", icon="receipt_long")

    _m_start = date.today().replace(day=1)
    with Session(engine) as _s:
        _all_tx = _s.exec(select(Transaction)).all()
    _month_tx = [t for t in _all_tx if t.date >= _m_start]
    summary_strip([
        ("Spent this month", f"{CUR}{sum(t.amount for t in _month_tx):,.0f}", AMBER),
        ("This month", f"{len(_month_tx)} txns", INDIGO),
        ("All-time total", f"{CUR}{sum(t.amount for t in _all_tx):,.0f}", EMERALD),
    ])

    with ui.tabs().classes("w-full") as tabs:
        log_tab = ui.tab("Log", icon="list")
        summary_tab = ui.tab("Summary", icon="bar_chart")
        add_tab = ui.tab("Add", icon="add")

    # min-h-[70vh] matters here: Quasar's swipeable QTabPanels shrinks
    # its swipe hit-area to the height of whatever content is inside,
    # so without an explicit minimum, swiping only works where content
    # happens to be -- not across the rest of the empty screen.
    with ui.tab_panels(tabs, value=log_tab).props('swipeable animated transition-prev="fade" transition-next="fade" transition-duration="260"').classes("w-full bg-transparent min-h-[70vh]"):
        with ui.tab_panel(log_tab).classes("p-0 min-h-[70vh]"):
            with Session(engine) as session:
                all_categories = session.exec(select(Category)).all()
            filter_category_options = {None: "All categories"}
            filter_category_options.update({c.id: _category_label(c, all_categories) for c in all_categories})

            # --- filter bar ---
            with card_box().classes("w-full mt-4 gap-2"):
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    search_input = ui.input(placeholder="Search merchant or notes").props(
                        'dense clearable debounce=300'
                    ).classes("flex-grow min-w-[180px]")
                    with search_input.add_slot("prepend"):
                        ui.icon("search").classes("text-base").style(f"color:{TEXT_DIM}")
                    category_filter = ui.select(
                        filter_category_options, value=None, label="Category"
                    ).props("dense options-dense").classes("w-44")
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    from_input = date_field("From")
                    to_input = date_field("To")
                    ui.button("Clear", icon="close", on_click=lambda: clear_filters()).props("flat dense no-caps").classes("self-end")
                    ui.space()
                    ui.button("Export CSV", icon="download", on_click=lambda: export_transactions()).props(
                        "outline dense no-caps color=primary"
                    ).classes("self-end")
                result_summary = ui.label().classes("text-xs").style(f"color:{TEXT_DIM}")

            undo_container = ui.column().classes("w-full")
            list_container = ui.column().classes("w-full gap-2")

            def query_filtered():
                """Returns (transactions, categories_by_id) applying the active filters."""
                with Session(engine) as session:
                    query = select(Transaction)
                    if category_filter.value is not None:
                        query = query.where(Transaction.category_id == category_filter.value)
                    if from_input.value:
                        query = query.where(Transaction.date >= date.fromisoformat(from_input.value))
                    if to_input.value:
                        query = query.where(Transaction.date <= date.fromisoformat(to_input.value))
                    query = query.order_by(Transaction.date.desc()).limit(500)
                    transactions = session.exec(query).all()
                    categories = {c.id: c.name for c in session.exec(select(Category)).all()}
                term = (search_input.value or "").strip().lower()
                if term:
                    transactions = [
                        t for t in transactions
                        if term in (t.merchant or "").lower() or term in (t.notes or "").lower()
                    ]
                return transactions, categories

            # Render only a capped number of rows at once -- drawing every one of
            # up to 500 transactions builds thousands of DOM nodes and is slow on
            # mobile. "Show more" reveals the rest in chunks.
            _DISPLAY = {"limit": 60}

            def render_list():
                list_container.clear()
                transactions, categories = query_filtered()
                filters_active = bool(
                    (search_input.value or "").strip() or category_filter.value is not None
                    or from_input.value or to_input.value
                )
                if transactions:
                    total = sum(t.amount for t in transactions)
                    result_summary.set_text(f"{len(transactions)} transaction(s) · {CUR}{total:,.2f} total")
                else:
                    result_summary.set_text("")
                shown = transactions[:_DISPLAY["limit"]]
                with list_container:
                    if not transactions:
                        if filters_active:
                            empty_state("No transactions match these filters.", "search_off")
                        else:
                            empty_state("No transactions yet -- swipe right or tap \"Add\" to log your first one.", "receipt_long")
                    for group_date, day_transactions in group_by_date(shown):
                        day_total = sum(t.amount for t in day_transactions)
                        with ui.row().classes("w-full items-baseline justify-between mt-3 mb-1 px-1"):
                            ui.label(format_date_header(group_date)).classes("text-xs font-semibold uppercase tracking-wide").style(f"color:{TEXT_DIM}")
                            ui.label(f"{CUR}{day_total:,.2f}").classes("text-xs font-semibold").style(f"color:{TEXT_DIM}")
                        with ui.column().classes(LIST_GROUP):
                            for idx, t in enumerate(day_transactions):
                                if idx:
                                    ui.element("div").classes("h-px w-full").style(f"background:{BORDER}")
                                icon = PAYMENT_ICONS.get(t.payment_method, "receipt_long")
                                with ui.row().classes("w-full items-center justify-between gap-3 px-3 py-2.5"):
                                    with ui.row().classes("items-center gap-3 min-w-0"):
                                        ui.icon(icon).classes("text-xl shrink-0").style(f"color:{TEXT_DIM}")
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(t.merchant or "Unnamed").classes("font-medium truncate")
                                            sub = categories.get(t.category_id, "Uncategorized")
                                            if t.tag:
                                                sub += f" · {t.tag}"
                                            ui.label(sub).classes("text-xs truncate").style(f"color:{TEXT_DIM}")
                                    with ui.row().classes("items-center gap-1 shrink-0"):
                                        ui.label(f"{CUR}{t.amount:,.2f}").classes("font-semibold")
                                        if t.receipt_image_path:
                                            ui.button(icon="receipt", on_click=lambda _, p=t.receipt_image_path: view_receipt_photo(p)).props("flat round dense size=sm").tooltip("View attached photo")
                                        ui.button(icon="edit", on_click=lambda _, tid=t.id: open_edit_transaction(tid)).props("flat round dense size=sm").tooltip("Edit")
                                        ui.button(icon="delete", on_click=lambda _, tid=t.id: delete_transaction(tid)).props("flat round dense color=red size=sm")
                    remaining = len(transactions) - len(shown)
                    if remaining > 0:
                        def _more():
                            _DISPLAY["limit"] += 100
                            render_list()
                        ui.button(f"Show more ({remaining} remaining)", icon="expand_more", on_click=_more).props(
                            "flat no-caps color=primary").classes("self-center mt-2")

            def refresh():
                _DISPLAY["limit"] = 60   # reset to the top whenever filters change
                render_list()

            def clear_filters():
                search_input.value = ""
                category_filter.value = None
                from_input.value = ""
                to_input.value = ""
                refresh()

            def export_transactions():
                transactions, categories = query_filtered()
                if not transactions:
                    ui.notify("Nothing to export with the current filters.", type="warning")
                    return
                rows = [
                    [
                        t.date.isoformat(), t.merchant or "", f"{t.amount:.2f}",
                        categories.get(t.category_id, "Uncategorized"),
                        t.payment_method or "", t.tag or "", t.notes or "",
                    ]
                    for t in transactions
                ]
                download_csv(
                    ["Date", "Merchant", "Amount", "Category", "Payment method", "Tag", "Notes"],
                    rows, f"transactions-{date.today().isoformat()}.csv",
                )

            search_input.on_value_change(lambda e: refresh())
            category_filter.on_value_change(lambda e: refresh())
            from_input.on_value_change(lambda e: refresh())
            to_input.on_value_change(lambda e: refresh())

            def view_receipt_photo(path):
                with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] p-2"):
                    ui.image(f"/receipt-images/{path}").classes("max-w-full")
                    ui.button("Close", on_click=dialog.close).props("flat dense no-caps").classes("mt-2")
                dialog.open()

            def open_edit_transaction(tid):
                with Session(engine) as session:
                    t = session.get(Transaction, tid)
                    if not t:
                        return
                    cats = session.exec(select(Category)).all()
                    cat_opts = {c.id: _category_label(c, cats) for c in cats}
                    current = dict(date=t.date.isoformat(), merchant=t.merchant or "", amount=t.amount,
                                   category_id=t.category_id, payment=t.payment_method or "Card",
                                   tag=t.tag or "", notes=t.notes or "")

                with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
                    section_header("Edit transaction", icon="edit", icon_color=AMBER)
                    e_date = date_field("Date", value=current["date"])
                    e_merchant = ui.input(label="Merchant", value=current["merchant"]).classes("w-full")
                    e_amount = ui.number(label="Amount", value=current["amount"], format="%.2f").props(
                        f'prefix="{CUR}" input-class="text-xl font-bold"'
                    ).classes("w-full")
                    e_category = ui.select(cat_opts, value=current["category_id"], label="Category").classes("w-full")
                    e_payment = segmented("Payment method",
                                          {"Card": "Card", "Cash": "Cash", "Bank Transfer": "Transfer", "Other": "Other"},
                                          current["payment"] if current["payment"] in ("Card", "Cash", "Bank Transfer", "Other") else "Card")
                    e_tag = ui.select(TAG_OPTIONS, value=current["tag"], label="Tag (context)").classes("w-full")
                    e_notes = ui.textarea(label="Notes", value=current["notes"]).classes("w-full")

                    def save_edit():
                        with Session(engine) as session:
                            obj = session.get(Transaction, tid)
                            if obj:
                                obj.date = date.fromisoformat(e_date.value)
                                obj.merchant = e_merchant.value or None
                                obj.amount = e_amount.value or 0
                                obj.category_id = e_category.value
                                obj.payment_method = e_payment.value
                                obj.tag = e_tag.value or None
                                obj.notes = e_notes.value or None
                                session.add(obj)
                                session.commit()
                        dialog.close()
                        ui.notify("Transaction updated.", type="positive")
                        refresh()

                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                        ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                        ui.button("Save", on_click=save_edit).props("color=primary unelevated no-caps")
                dialog.open()

            def delete_transaction(tid):
                # Snapshot the row's values before deleting so the toast can
                # offer a real undo. The receipt file is deliberately left on
                # disk until undo expires -- deleting it eagerly would make the
                # restore lossy.
                with Session(engine) as session:
                    obj = session.get(Transaction, tid)
                    if not obj:
                        return
                    snapshot = {
                        "date": obj.date, "amount": obj.amount, "merchant": obj.merchant,
                        "category_id": obj.category_id, "payment_method": obj.payment_method,
                        "notes": obj.notes, "tag": obj.tag,
                        "receipt_image_path": obj.receipt_image_path,
                        "is_subscription_payment": obj.is_subscription_payment,
                    }
                    session.delete(obj)
                    session.commit()

                def undo_delete():
                    with Session(engine) as session:
                        session.add(Transaction(**snapshot))
                        session.commit()
                    ui.notify("Restored.", type="positive")
                    refresh()

                refresh()
                undo_banner(undo_container, f"Deleted {snapshot['merchant'] or 'transaction'}.", undo_delete)

            refresh()

        with ui.tab_panel(summary_tab).classes("p-0 min-h-[70vh]"):
            with ui.column().classes("w-full gap-3 pt-4"):
                with card_box().classes("w-full"):
                    period_select = ui.select(
                        {"weekly": "Week", "monthly": "Month", "6month": "6 Months", "yearly": "Year", "2year": "2 Years", "all_time": "All time"},
                        value="monthly", label="Period",
                    ).props("dense options-dense").classes("w-40")
                trend_container = ui.column().classes(CARD)
                summary_container = ui.column().classes(CARD)

                def refresh_summary():
                    render_amount_trend(trend_container, Transaction, Transaction.date, "Spending trend",
                                        "show_chart", AMBER, period_select.value, date.today(),
                                        empty_hint="No spending recorded in this period.")
                    render_expenses(summary_container, period_select.value, date.today())

                period_select.on_value_change(lambda e: refresh_summary())
                refresh_summary()

        with ui.tab_panel(add_tab).classes("p-0 min-h-[70vh]"):
            def on_saved():
                refresh()
                tabs.set_value(log_tab)

            with ui.column().classes("w-full items-center pt-4"):
                render_add_transaction_form(on_saved=on_saved)


def render_add_income_form(on_saved=None):
    """Builds the add-income form. Reused by both the standalone
    /add-income page and the Add tab on the merged /income page."""
    with card_box().classes("w-full max-w-xl"):
        section_header("Add Income", icon="payments", icon_color=EMERALD)
        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
            date_input = date_field("Date", value=date.today().isoformat())
            amount_input = ui.number(label=f"Amount ({CUR})", value=0, format="%.2f").props("dense").classes("w-full")
            source_select = ui.select(INCOME_SOURCES, value="Salary", label="Source").props("dense options-dense").classes("w-full")
            payer_input = ui.input(label="From (employer, client, etc.)").props("dense").classes("w-full")
            tag_select = ui.select(TAG_OPTIONS, value="", label="Tag (context)").props("dense options-dense").classes("w-full")
        notes_input = ui.textarea(label="Notes").props("dense").classes("w-full mt-1")
        result_label = ui.label().style(f"color:{EMERALD}")

        def submit():
            with Session(engine) as session:
                entry = Income(
                    date=date.fromisoformat(date_input.value),
                    amount=amount_input.value or 0,
                    source=source_select.value,
                    payer=payer_input.value or None,
                    tag=tag_select.value or None,
                    notes=notes_input.value,
                )
                session.add(entry)
                session.commit()
            result_label.set_text("Saved!")
            amount_input.value = 0
            payer_input.value = ""
            notes_input.value = ""
            if on_saved:
                on_saved()

        ui.button("Save income", on_click=submit).props("color=primary unelevated")


def add_income_page():
    render_add_income_form()


def income_page():
    page_header("Income", "What's coming in, by source and month.", icon="payments")

    _m_start = date.today().replace(day=1)
    with Session(engine) as _s:
        _all_inc = _s.exec(select(Income)).all()
    _month_inc = [i for i in _all_inc if i.date >= _m_start]
    _sources = len({i.source for i in _all_inc if i.source})
    summary_strip([
        ("This month", f"{CUR}{sum(i.amount for i in _month_inc):,.0f}", EMERALD),
        ("All-time", f"{CUR}{sum(i.amount for i in _all_inc):,.0f}", INDIGO),
        ("Sources", str(_sources), AMBER) if _sources else None,
    ])

    with ui.tabs().classes("w-full") as tabs:
        log_tab = ui.tab("Log", icon="list")
        summary_tab = ui.tab("Summary", icon="bar_chart")
        add_tab = ui.tab("Add", icon="add")

    with ui.tab_panels(tabs, value=log_tab).props('swipeable animated transition-prev="fade" transition-next="fade" transition-duration="260"').classes("w-full bg-transparent min-h-[70vh]"):
        with ui.tab_panel(log_tab).classes("p-0 min-h-[70vh]"):
            with ui.row().classes("w-full justify-end pt-4"):
                ui.button("Export CSV", icon="download", on_click=lambda: export_income()).props(
                    "outline dense no-caps color=primary"
                )
            undo_container = ui.column().classes("w-full")
            list_container = ui.column().classes("w-full gap-2")

            def export_income():
                with Session(engine) as session:
                    entries = session.exec(select(Income).order_by(Income.date.desc())).all()
                if not entries:
                    ui.notify("No income to export yet.", type="warning")
                    return
                rows = [
                    [i.date.isoformat(), i.source, i.payer or "", f"{i.amount:.2f}", i.tag or "", i.notes or ""]
                    for i in entries
                ]
                download_csv(
                    ["Date", "Source", "Payer", "Amount", "Tag", "Notes"],
                    rows, f"income-{date.today().isoformat()}.csv",
                )

            _DISPLAY = {"limit": 60}

            def render_list():
                list_container.clear()
                with Session(engine) as session:
                    income_entries = session.exec(select(Income).order_by(Income.date.desc()).limit(200)).all()
                shown = income_entries[:_DISPLAY["limit"]]
                with list_container:
                    if not income_entries:
                        empty_state("No income logged yet -- swipe right or tap \"Add\" to log your first one.", "payments")
                    for group_date, day_entries in group_by_date(shown):
                        day_total = sum(i.amount for i in day_entries)
                        with ui.row().classes("w-full items-baseline justify-between mt-3 mb-1 px-1"):
                            ui.label(format_date_header(group_date)).classes("text-xs font-semibold uppercase tracking-wide").style(f"color:{TEXT_DIM}")
                            ui.label(f"{CUR}{day_total:,.2f}").classes("text-xs font-semibold").style(f"color:{TEXT_DIM}")
                        with ui.column().classes(LIST_GROUP):
                            for idx, i in enumerate(day_entries):
                                if idx:
                                    ui.element("div").classes("h-px w-full").style(f"background:{BORDER}")
                                icon = INCOME_ICONS.get(i.source, "attach_money")
                                with ui.row().classes("w-full items-center justify-between gap-3 px-3 py-2.5"):
                                    with ui.row().classes("items-center gap-3 min-w-0"):
                                        ui.icon(icon).classes("text-xl shrink-0").style(f"color:{EMERALD}")
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(i.payer or i.source).classes("font-medium truncate")
                                            sub = i.source
                                            if i.tag:
                                                sub += f" · {i.tag}"
                                            ui.label(sub).classes("text-xs truncate").style(f"color:{TEXT_DIM}")
                                    with ui.row().classes("items-center gap-1 shrink-0"):
                                        ui.label(f"{CUR}{i.amount:,.2f}").classes("font-semibold").style(f"color:{EMERALD}")
                                        ui.button(icon="edit", on_click=lambda _, iid=i.id: open_edit_income(iid)).props("flat round dense size=sm").tooltip("Edit")
                                        ui.button(icon="delete", on_click=lambda _, iid=i.id: delete_income(iid)).props("flat round dense color=red size=sm")
                    remaining = len(income_entries) - len(shown)
                    if remaining > 0:
                        def _more():
                            _DISPLAY["limit"] += 100
                            render_list()
                        ui.button(f"Show more ({remaining} remaining)", icon="expand_more", on_click=_more).props(
                            "flat no-caps color=primary").classes("self-center mt-2")

            def refresh():
                _DISPLAY["limit"] = 60
                render_list()

            def open_edit_income(iid):
                with Session(engine) as session:
                    obj = session.get(Income, iid)
                    if not obj:
                        return
                    cur = dict(date=obj.date.isoformat(), amount=obj.amount, source=obj.source,
                               payer=obj.payer or "", tag=obj.tag or "", notes=obj.notes or "")

                with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
                    section_header("Edit income", icon="edit", icon_color=EMERALD)
                    e_date = date_field("Date", value=cur["date"])
                    e_amount = ui.number(label="Amount", value=cur["amount"], format="%.2f").props(
                        f'prefix="{CUR}" input-class="text-xl font-bold"'
                    ).classes("w-full")
                    e_source = ui.select(INCOME_SOURCES, value=cur["source"], label="Source").classes("w-full")
                    e_payer = ui.input(label="Payer", value=cur["payer"]).classes("w-full")
                    e_tag = ui.select(TAG_OPTIONS, value=cur["tag"], label="Tag (context)").classes("w-full")
                    e_notes = ui.textarea(label="Notes", value=cur["notes"]).classes("w-full")

                    def save_edit():
                        with Session(engine) as session:
                            obj = session.get(Income, iid)
                            if obj:
                                obj.date = date.fromisoformat(e_date.value)
                                obj.amount = e_amount.value or 0
                                obj.source = e_source.value
                                obj.payer = e_payer.value or None
                                obj.tag = e_tag.value or None
                                obj.notes = e_notes.value or None
                                session.add(obj)
                                session.commit()
                        dialog.close()
                        ui.notify("Income updated.", type="positive")
                        refresh()

                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                        ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                        ui.button("Save", on_click=save_edit).props("color=primary unelevated no-caps")
                dialog.open()

            def delete_income(iid):
                with Session(engine) as session:
                    obj = session.get(Income, iid)
                    if not obj:
                        return
                    snapshot = dict(date=obj.date, amount=obj.amount, source=obj.source,
                                    payer=obj.payer, tag=obj.tag, notes=obj.notes)
                    session.delete(obj)
                    session.commit()

                def undo_delete():
                    with Session(engine) as session:
                        session.add(Income(**snapshot))
                        session.commit()
                    ui.notify("Restored.", type="positive")
                    refresh()

                refresh()
                undo_banner(undo_container, f"Deleted {snapshot['payer'] or snapshot['source']}.", undo_delete)

            refresh()

        with ui.tab_panel(summary_tab).classes("p-0 min-h-[70vh]"):
            with ui.column().classes("w-full gap-3 pt-4"):
                with card_box().classes("w-full"):
                    period_select = ui.select(
                        {"weekly": "Week", "monthly": "Month", "6month": "6 Months", "yearly": "Year", "2year": "2 Years", "all_time": "All time"},
                        value="monthly", label="Period",
                    ).props("dense options-dense").classes("w-40")
                trend_container = ui.column().classes(CARD)
                summary_container = ui.column().classes(CARD)

                def refresh_summary():
                    render_amount_trend(trend_container, Income, Income.date, "Income trend",
                                        "show_chart", EMERALD, period_select.value, date.today(),
                                        empty_hint="No income logged in this period.")
                    render_income_summary(summary_container, period_select.value, date.today())

                period_select.on_value_change(lambda e: refresh_summary())
                refresh_summary()

        with ui.tab_panel(add_tab).classes("p-0 min-h-[70vh]"):
            def on_saved():
                refresh()
                quick_income_card.refresh()
                tabs.set_value(log_tab)

            with ui.column().classes("w-full items-center pt-4 gap-4"):
                @ui.refreshable
                def quick_income_card():
                    """Recurring income (salary, regular clients) as one-tap
                    chips -- re-logs the entry with today's date, closing the
                    'retype your salary every month' loop."""
                    with Session(engine) as session:
                        recent = session.exec(
                            select(Income).order_by(Income.date.desc(), Income.id.desc()).limit(60)
                        ).all()
                    seen, favourites = set(), []
                    for entry in recent:
                        key = (entry.source, (entry.payer or "").strip().lower())
                        if key in seen:
                            continue
                        seen.add(key)
                        favourites.append(entry)
                        if len(favourites) >= 6:
                            break
                    if not favourites:
                        return
                    with card_box().classes("w-full max-w-xl"):
                        section_header("Quick add", icon="bolt", icon_color=EMERALD,
                                       subtitle="Tap to log a repeat of a recent income for today")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            for entry in favourites:
                                icon = INCOME_ICONS.get(entry.source, "attach_money")
                                with ui.button(on_click=lambda _, iid=entry.id: quick_log_income(iid)).props(
                                    "outline dense no-caps"
                                ).classes("normal-case").style(f"border-color:{BORDER}; color:{TEXT};"):
                                    with ui.row().classes("items-center gap-2 no-wrap"):
                                        ui.icon(icon).classes("text-base").style(f"color:{EMERALD}")
                                        with ui.column().classes("gap-0 items-start"):
                                            ui.label(entry.payer or entry.source).classes("text-xs font-medium leading-tight")
                                            ui.label(f"{CUR}{entry.amount:,.2f}").classes("text-[10px] leading-tight").style(f"color:{TEXT_DIM}")

                def quick_log_income(iid):
                    with Session(engine) as session:
                        src = session.get(Income, iid)
                        if not src:
                            return
                        session.add(Income(date=date.today(), amount=src.amount, source=src.source,
                                           payer=src.payer, tag=src.tag, notes=src.notes))
                        session.commit()
                    ui.notify(f"Logged {CUR}{src.amount:,.2f} from {src.payer or src.source}.", type="positive")
                    refresh()
                    quick_income_card.refresh()

                quick_income_card()
                render_add_income_form(on_saved=on_saved)


# ---------------------------------------------------------------------------
# Import bank statement (CSV or PDF)
# ---------------------------------------------------------------------------
def import_statement_page():
    page_header("Import Statement",
                "Bring in a CSV or PDF bank statement — nothing saves until you review and confirm.",
                icon="upload_file")

    step_container = ui.column().classes("w-full gap-4")
    state = {
        "source_type": None,   # 'csv' or 'pdf'
        "table": None,          # csv: {"headers": [...], "rows": [...]}; pdf: list of line candidates
        "candidates": [],       # unified list of dicts after mapping: {date, description, amount, include, is_duplicate}
        "created_ids": {"transactions": [], "income": []},
    }

    with Session(engine) as session:
        categories = session.exec(select(Category)).all()
    category_options = {c.id: _category_label(c, categories) for c in categories}
    default_category = next((c.id for c in categories if c.name == "Miscellaneous"), None)

    def render_upload_step():
        step_container.clear()
        with step_container:
            with card_box().classes("w-full max-w-xl"):
                section_header("1. Upload a file", icon="upload_file", icon_color=INDIGO)
                upload_status = ui.label().classes("text-xs")

                async def handle_upload(e):
                    upload_status.set_text("Reading file...")
                    upload_status.style(f"color:{TEXT_DIM}")
                    try:
                        file_bytes = await _read_upload_bytes(e)
                        filename = (getattr(e, "file", None) or e)
                        filename = getattr(filename, "name", "") or ""
                    except Exception as exc:
                        upload_status.set_text(f"Couldn't read that file: {exc}")
                        upload_status.style(f"color:{RED}")
                        return

                    try:
                        if filename.lower().endswith(".pdf"):
                            state["source_type"] = "pdf"
                            text = extract_pdf_text(file_bytes)
                            state["table"] = parse_pdf_lines(text)
                            if not state["table"]:
                                raise StatementImportError(
                                    "Couldn't find any lines that look like transactions "
                                    "(a date next to an amount) in this PDF."
                                )
                        else:
                            state["source_type"] = "csv"
                            state["table"] = parse_csv(file_bytes)
                    except StatementImportError as exc:
                        upload_status.set_text(str(exc))
                        upload_status.style(f"color:{RED}")
                        return
                    except Exception as exc:
                        upload_status.set_text(f"Couldn't process that file: {exc}")
                        upload_status.style(f"color:{RED}")
                        return

                    render_mapping_step()

                ui.upload(on_upload=handle_upload, auto_upload=True, max_files=1).props(
                    'accept=".csv,.pdf"'
                ).classes("max-w-full")

    # -----------------------------------------------------------------
    def render_mapping_step():
        step_container.clear()
        with step_container:
            if state["source_type"] == "csv":
                render_csv_mapping()
            else:
                render_pdf_mapping()

    def render_csv_mapping():
        headers = state["table"]["headers"]
        header_options = {i: h for i, h in enumerate(headers)}

        with card_box().classes("w-full max-w-2xl"):
            section_header("2. Match up the columns", icon="view_column", icon_color=INDIGO)
            with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
                date_col = ui.select(header_options, label="Date column").props("dense options-dense").classes("w-full")
                date_format = ui.select(list(DATE_FORMATS.keys()), value="DD/MM/YYYY", label="Date format").props("dense options-dense").classes("w-full")
                desc_col = ui.select(header_options, label="Description column").props("dense options-dense").classes("w-full")

            split_toggle = ui.switch("Separate Debit and Credit columns", value=False).props("dense color=primary").classes("mt-1")

            with ui.column().classes("w-full gap-1") as single_amount_col:
                amount_col = ui.select(header_options, label="Amount column").props("dense options-dense").classes("w-full")
                sign_convention = segmented(
                    "", ["Negative = expense", "Negative = income"], "Negative = expense"
                )

            with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1") as split_amount_cols:
                debit_col = ui.select(header_options, label="Debit (money out) column").props("dense options-dense").classes("w-full")
                credit_col = ui.select(header_options, label="Credit (money in) column").props("dense options-dense").classes("w-full")
            split_amount_cols.set_visibility(False)

            def toggle_split(e):
                single_amount_col.set_visibility(not e.value)
                split_amount_cols.set_visibility(e.value)

            split_toggle.on_value_change(toggle_split)

            error_label = ui.label().classes("text-xs mt-1").style(f"color:{RED}")

            def build_candidates():
                if date_col.value is None or desc_col.value is None:
                    error_label.set_text("Pick a date column and a description column first.")
                    return
                if not split_toggle.value and amount_col.value is None:
                    error_label.set_text("Pick an amount column, or switch on separate Debit/Credit columns.")
                    return
                if split_toggle.value and (debit_col.value is None or credit_col.value is None):
                    error_label.set_text("Pick both a Debit and a Credit column.")
                    return

                candidates = []
                day_first = date_format.value in ("DD/MM/YYYY", "DD-MM-YYYY", "DD.MM.YYYY")
                for row in state["table"]["rows"]:
                    d = parse_date_with_format(row[date_col.value], date_format.value)
                    if not d:
                        continue
                    description = row[desc_col.value].strip()

                    if split_toggle.value:
                        debit = parse_amount(row[debit_col.value]) or 0
                        credit = parse_amount(row[credit_col.value]) or 0
                        if debit:
                            candidates.append({"date": d, "description": description, "amount": abs(debit), "is_income": False})
                        elif credit:
                            candidates.append({"date": d, "description": description, "amount": abs(credit), "is_income": True})
                    else:
                        amt = parse_amount(row[amount_col.value])
                        if amt is None:
                            continue
                        negative_is_expense = sign_convention.value == "Negative = expense"
                        is_income = (amt > 0) if negative_is_expense else (amt < 0)
                        candidates.append({"date": d, "description": description, "amount": abs(amt), "is_income": is_income})

                if not candidates:
                    error_label.set_text(
                        "Couldn't parse any rows with that mapping -- double check the date format and columns."
                    )
                    return

                state["candidates"] = candidates
                render_preview_step()

            with ui.row().classes("w-full justify-between mt-2"):
                ui.button("Back", on_click=render_upload_step).props("flat dense no-caps")
                ui.button("Continue", on_click=build_candidates).props("color=primary unelevated")

    def render_pdf_mapping():
        line_candidates = state["table"]
        with card_box().classes("w-full max-w-2xl"):
            section_header("2. Confirm date format", icon="event", icon_color=INDIGO)
            ui.label(
                f"Found {len(line_candidates)} line(s) that look like transactions (a date next to "
                "an amount). You'll review and can exclude any that aren't real transactions on the next screen."
            ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")
            date_format = ui.select(list(DATE_FORMATS.keys()), value="DD/MM/YYYY", label="Date format").props("dense options-dense").classes("w-48")
            sign_convention = segmented(
                "", ["Negative = expense", "Negative = income"], "Negative = expense"
            ).classes("mt-2")
            error_label = ui.label().classes("text-xs mt-1").style(f"color:{RED}")

            def build_candidates():
                candidates = []
                for c in line_candidates:
                    d = parse_date_with_format(c["date_str"], date_format.value)
                    amt = parse_amount(c["amount_str"])
                    if not d or amt is None:
                        continue
                    negative_is_expense = sign_convention.value == "Negative = expense"
                    is_income = (amt > 0) if negative_is_expense else (amt < 0)
                    candidates.append({"date": d, "description": c["description"], "amount": abs(amt), "is_income": is_income})

                if not candidates:
                    error_label.set_text("Couldn't parse any of the detected lines with that date format.")
                    return
                state["candidates"] = candidates
                render_preview_step()

            with ui.row().classes("w-full justify-between mt-2"):
                ui.button("Back", on_click=render_upload_step).props("flat dense no-caps")
                ui.button("Continue", on_click=build_candidates).props("color=primary unelevated")

    # -----------------------------------------------------------------
    def render_preview_step():
        step_container.clear()

        with Session(engine) as session:
            existing_transactions = session.exec(select(Transaction)).all()
            existing_income = session.exec(select(Income)).all()
        existing_expense_keys = {(t.date, round(t.amount, 2)) for t in existing_transactions}
        existing_income_keys = {(i.date, round(i.amount, 2)) for i in existing_income}

        # Per-row category suggestion: reuse how this merchant was categorised
        # before, else a keyword guess, else the blanket default (Misc).
        history_map = build_history_map(existing_transactions)
        name_to_id = {cat.name: cat.id for cat in categories}

        for c in state["candidates"]:
            key = (c["date"], round(c["amount"], 2))
            c["is_duplicate"] = key in (existing_income_keys if c["is_income"] else existing_expense_keys)
            c["include"] = not c["is_duplicate"]
            guess = guess_category_id(c["description"], name_to_id, history_map)
            c["category_id"] = guess if guess is not None else default_category

        with step_container:
            with card_box().classes("w-full"):
                section_header("3. Review before importing", icon="fact_check", icon_color=INDIGO)
                num_dupes = sum(1 for c in state["candidates"] if c["is_duplicate"])
                num_expense = sum(1 for c in state["candidates"] if not c["is_income"])
                num_income = sum(1 for c in state["candidates"] if c["is_income"])
                ui.label(
                    f"{len(state['candidates'])} row(s) found: {num_expense} expense, {num_income} income. "
                    f"{num_dupes} look like duplicates of transactions you already have and are unchecked below."
                ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")

                ui.label(
                    "Every field below is editable -- fix anything the parser got wrong before importing."
                ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")

                rows_container = ui.column().classes("w-full gap-1")
                row_cat_selects = []  # (candidate, select) pairs, for "apply to all" + income toggling
                with rows_container:
                    for c in state["candidates"]:
                        with ui.row().classes("w-full items-center gap-2 py-2 flex-wrap border-b").style(f"border-color:{BORDER}"):
                            checkbox = ui.checkbox(value=c["include"])
                            checkbox.on_value_change(lambda e, cc=c: cc.update({"include": e.value}))

                            date_input = ui.input(value=c["date"].isoformat()).props("dense").classes("w-28")

                            def on_date_change(e, cc=c):
                                try:
                                    cc["date"] = date.fromisoformat(e.value)
                                except ValueError:
                                    pass  # leave the previous value if what they typed isn't a real date

                            date_input.on_value_change(on_date_change)

                            desc_input = ui.input(value=c["description"]).props("dense").classes("flex-grow min-w-[140px]")
                            desc_input.on_value_change(lambda e, cc=c: cc.update({"description": e.value}))

                            amount_input = ui.number(value=c["amount"], format="%.2f").props("dense").classes("w-24")
                            amount_input.on_value_change(lambda e, cc=c: cc.update({"amount": e.value or 0}))

                            direction_toggle = ui.toggle(
                                ["Expense", "Income"], value="Income" if c["is_income"] else "Expense"
                            ).props("dense toggle-color=primary")

                            cat_select = ui.select(
                                category_options, value=c["category_id"], with_input=True,
                            ).props("dense options-dense").classes("w-44")
                            cat_select.on_value_change(lambda e, cc=c: cc.update({"category_id": e.value}))
                            cat_select.set_visibility(not c["is_income"])  # income uses source, not category
                            row_cat_selects.append((c, cat_select))

                            def on_direction(e, cc=c, sel=cat_select):
                                cc["is_income"] = e.value == "Income"
                                sel.set_visibility(not cc["is_income"])
                            direction_toggle.on_value_change(on_direction)

                            if c["is_duplicate"]:
                                ui.label("possible duplicate").classes("text-xs").style(f"color:{TEXT_DIM}")

                with ui.row().classes("items-center gap-2 mb-2 mt-2"):
                    bulk_category_select = ui.select(
                        category_options, value=default_category, label="Set all expenses to…", with_input=True,
                    ).props("dense options-dense").classes("w-64")

                    def apply_to_all():
                        v = bulk_category_select.value
                        for cc, sel in row_cat_selects:
                            cc["category_id"] = v
                            sel.value = v
                    ui.button("Apply to all", on_click=apply_to_all).props("flat dense no-caps")

                result_label = ui.label().classes("mt-2")

                def do_import():
                    to_import = [c for c in state["candidates"] if c["include"]]
                    if not to_import:
                        result_label.set_text("Nothing selected to import.")
                        result_label.style(f"color:{RED}")
                        return
                    created_tx, created_inc = [], []
                    with Session(engine) as session:
                        for c in to_import:
                            if c["is_income"]:
                                entry = Income(date=c["date"], amount=c["amount"], source="Other", payer=c["description"][:200], notes="Imported from statement")
                                session.add(entry)
                                session.commit()
                                session.refresh(entry)
                                created_inc.append(entry.id)
                            else:
                                entry = Transaction(date=c["date"], amount=c["amount"], merchant=c["description"][:200], category_id=c["category_id"], notes="Imported from statement")
                                session.add(entry)
                                session.commit()
                                session.refresh(entry)
                                created_tx.append(entry.id)
                    state["created_ids"] = {"transactions": created_tx, "income": created_inc}
                    render_success_step(len(created_tx), len(created_inc))

                with ui.row().classes("w-full justify-between mt-2"):
                    ui.button("Back", on_click=render_upload_step).props("flat dense no-caps")
                    ui.button("Import selected", on_click=do_import).props("color=primary unelevated")

    # -----------------------------------------------------------------
    def render_success_step(num_tx, num_inc):
        step_container.clear()
        with step_container:
            with card_box().classes("w-full max-w-xl"):
                ui.label("Imported").classes("text-lg font-semibold mb-1").style(f"color:{EMERALD}")
                ui.label(f"Added {num_tx} transaction(s) and {num_inc} income entr{'y' if num_inc == 1 else 'ies'}.").classes("text-sm mb-2")

                def undo_import():
                    with Session(engine) as session:
                        for tid in state["created_ids"]["transactions"]:
                            obj = session.get(Transaction, tid)
                            if obj:
                                session.delete(obj)
                        for iid in state["created_ids"]["income"]:
                            obj = session.get(Income, iid)
                            if obj:
                                session.delete(obj)
                        session.commit()
                    state["created_ids"] = {"transactions": [], "income": []}
                    ui.notify("Import undone.", type="warning")
                    render_upload_step()

                with ui.row().classes("gap-2"):
                    ui.button("Undo this import", icon="undo", on_click=undo_import).props("flat dense no-caps color=red")
                    ui.link("View Transactions", "/transactions").classes("no-underline").style(f"color:{INDIGO}")
                    ui.button("Import another file", on_click=render_upload_step).props("flat dense no-caps")

    render_upload_step()


# ---------------------------------------------------------------------------
# Add / list food log
# ---------------------------------------------------------------------------
def render_add_food_form(on_saved=None):
    """Builds the add-food form in whatever container is currently active.
    Reused by both the standalone /add-food page and the Add tab on the
    merged /food-log page."""
    with card_box().classes("w-full max-w-xl"):
        section_header("Add Food Entry", icon="restaurant", icon_color=INDIGO)

        date_input = date_field("Date", value=date.today().isoformat())
        meal_select = segmented(
            "Meal", {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}, "lunch"
        )

        with ui.column().classes("w-full gap-1 mt-2"):
            ui.label("Quantity (g)").classes("text-xs").style(f"color:{TEXT_DIM}")
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                quantity_input = ui.number(value=100, format="%g").props("dense").classes("flex-grow")
                for q in [50, 100, 150, 200]:
                    ui.button(f"{q}", on_click=lambda _, v=q: quantity_input.set_value(v)).props(
                        "flat dense no-caps"
                    ).classes("text-xs min-w-0 px-2").style(f"color:{INDIGO}")

        tag_select = ui.select(TAG_OPTIONS, value="", label="Tag (context)").props("dense options-dense").classes("w-full mt-2")
        eaten_out_toggle = ui.switch("Eaten out (restaurant / takeaway)", value=False).props("dense color=primary").classes("mt-1")

        # Unified spend+meal log: when eaten out, optionally record the spend too,
        # so one entry captures both the meal (health) and the transaction (money).
        with Session(engine) as _s:
            _out_cats = {c.id: c.name for c in _s.exec(select(Category)).all()
                         if c.name in ("Eating Out", "Groceries")}
        _default_out_cat = next((cid for cid, n in _out_cats.items() if n == "Eating Out"), None)
        with ui.column().classes("w-full gap-1 mt-1 pl-3 border-l-2").style(f"border-color:{INDIGO}55") as out_spend_section:
            ui.label("Also log the spend").classes("text-xs").style(f"color:{TEXT_DIM}")
            with ui.row().classes("w-full items-end gap-2 flex-wrap"):
                out_amount = ui.number(label="Amount", format="%.2f").props(f'prefix="{CUR}" dense').classes("w-28")
                out_merchant = ui.input(label="Where").props("dense").classes("flex-grow min-w-[120px]")
                out_cat = ui.select(_out_cats, value=_default_out_cat, label="Category").props("dense options-dense").classes("w-36")
        out_spend_section.bind_visibility_from(eaten_out_toggle, "value")

        with ui.row().classes("w-full items-end gap-2 mt-2"):
            barcode_input = ui.input(label="Barcode (scan or type)").props("dense").classes("flex-grow")
            ui.button(icon="qr_code_scanner", on_click=lambda: scan_barcode()).props("outline dense round").tooltip("Scan with camera")
            ui.button(icon="search", on_click=lambda: do_lookup()).props("outline dense round").tooltip("Look up typed barcode")
        lookup_status = ui.label().classes("text-xs").style(f"color:{TEXT_DIM}")

        name_input = ui.input(label="Food name").props("dense").classes("w-full mt-1")

        ui.label("Calories").classes("text-xs mt-2").style(f"color:{TEXT_DIM}")
        calories_input = ui.number(placeholder="0").props(
            'suffix="kcal" input-class="text-2xl font-bold"'
        ).classes("w-full")
        with ui.grid().classes("w-full grid-cols-3 gap-x-3 gap-y-1 mt-1"):
            protein_input = ui.number(label="Protein (g)").props("dense").classes("w-full")
            carbs_input = ui.number(label="Carbs (g)").props("dense").classes("w-full")
            fat_input = ui.number(label="Fat (g)").props("dense").classes("w-full")

        with ui.expansion("More nutrients (optional)").classes("w-full mt-1"):
            with ui.grid().classes("w-full grid-cols-2 gap-x-3 gap-y-1"):
                sugar_input = ui.number(label="Sugar (g)").props("dense").classes("w-full")
                fiber_input = ui.number(label="Fiber (g)").props("dense").classes("w-full")
                sodium_input = ui.number(label="Sodium (mg)").props("dense").classes("w-full")
                satfat_input = ui.number(label="Saturated fat (g)").props("dense").classes("w-full")
                transfat_input = ui.number(label="Trans fat (g)").props("dense").classes("w-full")
                addedsugar_input = ui.number(label="Added sugar (g)").props("dense").classes("w-full")
                alcohol_input = ui.number(label="Alcohol (g)").props("dense").classes("w-full")
                caffeine_input = ui.number(label="Caffeine (mg)").props("dense").classes("w-full")

        result_label = ui.label().style(f"color:{EMERALD}")

        def do_lookup():
            barcode = barcode_input.value
            if not barcode:
                return
            with Session(engine) as session:
                item = lookup_barcode(session, barcode)
            if not item or item.calories_per_100g is None:
                lookup_status.set_text("Not found in Open Food Facts")
                return
            factor = (quantity_input.value or 100) / 100.0
            name_input.value = item.name or ""
            calories_input.value = round((item.calories_per_100g or 0) * factor, 1)
            protein_input.value = round((item.protein_per_100g or 0) * factor, 1)
            carbs_input.value = round((item.carbs_per_100g or 0) * factor, 1)
            fat_input.value = round((item.fat_per_100g or 0) * factor, 1)
            sugar_input.value = round((item.sugar_per_100g or 0) * factor, 1)
            fiber_input.value = round((item.fiber_per_100g or 0) * factor, 1)
            sodium_input.value = round((item.sodium_per_100g or 0) * factor, 1)
            satfat_input.value = round((item.saturated_fat_per_100g or 0) * factor, 1)
            transfat_input.value = round((item.trans_fat_per_100g or 0) * factor, 1)
            caffeine_input.value = round((item.caffeine_per_100g or 0) * factor, 1)
            lookup_status.set_text(f"Found: {item.name}")

        async def scan_barcode():
            scan_js = """
                return await new Promise((resolve) => {
                    if (typeof Html5Qrcode === 'undefined') {
                        resolve({error: 'Scanner library did not load. Check your internet connection.'});
                        return;
                    }
                    const overlay = document.createElement('div');
                    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:#0B0B0F;'
                        + 'display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px;';
                    const readerDiv = document.createElement('div');
                    readerDiv.id = 'balance-barcode-reader';
                    readerDiv.style.cssText = 'width:100%;max-width:480px;border-radius:12px;overflow:hidden;';
                    const hint = document.createElement('div');
                    hint.innerText = 'Point the camera at a barcode';
                    hint.style.cssText = 'color:#E4E4E7;margin-bottom:12px;font-family:sans-serif;font-size:14px;';
                    const cancelBtn = document.createElement('button');
                    cancelBtn.innerText = 'Cancel';
                    cancelBtn.style.cssText = 'margin-top:16px;padding:10px 28px;border-radius:10px;'
                        + 'background:#1C1C22;color:#E4E4E7;border:1px solid #26262E;font-size:14px;';
                    overlay.appendChild(hint);
                    overlay.appendChild(readerDiv);
                    overlay.appendChild(cancelBtn);
                    document.body.appendChild(overlay);

                    let finished = false;
                    const html5QrCode = new Html5Qrcode('balance-barcode-reader');

                    function cleanup() {
                        if (document.body.contains(overlay)) document.body.removeChild(overlay);
                    }
                    function finish(value) {
                        if (finished) return;
                        finished = true;
                        html5QrCode.stop().catch(() => {}).finally(() => {
                            cleanup();
                            resolve(value);
                        });
                    }

                    html5QrCode.start(
                        { facingMode: 'environment' },
                        { fps: 10, qrbox: 250 },
                        (decodedText) => finish({code: decodedText}),
                        () => { /* ignore per-frame no-match, keep scanning */ }
                    ).catch((err) => {
                        cleanup();
                        resolve({error: 'Could not access camera: ' + err});
                    });

                    cancelBtn.onclick = () => finish({code: null});
                });
            """
            try:
                result = await ui.run_javascript(scan_js, timeout=60.0)
            except Exception as exc:
                ui.notify(f"Camera scan failed or timed out: {exc}", type="warning")
                return
            if not result:
                return
            if result.get("error"):
                ui.notify(result["error"], type="negative")
                return
            code = result.get("code")
            if code:
                barcode_input.value = code
                do_lookup()

        def submit():
            with Session(engine) as session:
                entry = FoodLog(
                    date=date.fromisoformat(date_input.value),
                    meal_type=meal_select.value,
                    food_name=name_input.value or "Unnamed food",
                    barcode=barcode_input.value or None,
                    quantity_g=quantity_input.value or 100,
                    tag=tag_select.value or None,
                    eaten_out=eaten_out_toggle.value,
                    calories=calories_input.value,
                    protein_g=protein_input.value,
                    carbs_g=carbs_input.value,
                    fat_g=fat_input.value,
                    sugar_g=sugar_input.value,
                    fiber_g=fiber_input.value,
                    sodium_mg=sodium_input.value,
                    saturated_fat_g=satfat_input.value,
                    trans_fat_g=transfat_input.value,
                    added_sugar_g=addedsugar_input.value,
                    alcohol_g=alcohol_input.value,
                    caffeine_mg=caffeine_input.value,
                )
                session.add(entry)
                session.commit()
                also_spent = bool(eaten_out_toggle.value and out_amount.value)
                if also_spent:
                    session.add(Transaction(
                        date=date.fromisoformat(date_input.value),
                        amount=out_amount.value,
                        merchant=(out_merchant.value or name_input.value or "Meal out")[:200],
                        category_id=out_cat.value,
                        payment_method="Card",
                        notes="Logged with a meal",
                    ))
                    session.commit()
            result_label.set_text("Saved — meal + spend logged!" if also_spent else "Saved!")
            # reset for the next entry rather than leaving stale values behind
            barcode_input.value = ""
            name_input.value = ""
            quantity_input.value = 100
            calories_input.value = None
            protein_input.value = None
            carbs_input.value = None
            fat_input.value = None
            out_amount.value = None
            out_merchant.value = ""
            lookup_status.set_text("")
            if on_saved:
                on_saved()

        ui.button("Save food entry", on_click=submit).props("color=primary unelevated")


def add_food_page():
    render_add_food_form()


def food_log_page():
    page_header("Food Log", "What you ate today, measured against your targets.", icon="restaurant")

    _today = date.today()
    with Session(engine) as _s:
        _tf = _s.exec(select(FoodLog).where(FoodLog.date == _today)).all()
        _g = _s.exec(select(NutrientGoals)).first() or NutrientGoals()
    _cal = sum(f.calories or 0 for f in _tf)
    _pro = sum(f.protein_g or 0 for f in _tf)
    summary_strip([
        ("Calories today", f"{_cal:,.0f}" + (f" / {_g.calories:,.0f}" if _g.calories else ""), INDIGO),
        ("Protein today", f"{_pro:,.0f}g" + (f" / {_g.protein_g:,.0f}g" if _g.protein_g else ""), EMERALD),
        ("Meals logged", str(len(_tf)), AMBER),
    ])

    with ui.tabs().classes("w-full") as tabs:
        log_tab = ui.tab("Log", icon="list")
        add_tab = ui.tab("Add", icon="add")

    with ui.tab_panels(tabs, value=log_tab).props('swipeable animated transition-prev="fade" transition-next="fade" transition-duration="260"').classes("w-full bg-transparent min-h-[70vh]") as panels:
        with ui.tab_panel(log_tab).classes("p-0 min-h-[70vh]"):
            undo_container = ui.column().classes("w-full pt-4")

            with card_box().classes("w-full gap-2"):
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    search_input = ui.input(placeholder="Search food or tag").props(
                        "dense clearable debounce=300"
                    ).classes("flex-grow min-w-[160px]")
                    with search_input.add_slot("prepend"):
                        ui.icon("search").classes("text-base").style(f"color:{TEXT_DIM}")
                    meal_filter = ui.select(
                        {None: "All meals", "breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"},
                        value=None, label="Meal",
                    ).props("dense options-dense").classes("w-40")
                result_summary = ui.label().classes("text-xs").style(f"color:{TEXT_DIM}")

            list_container = ui.column().classes("w-full gap-2")

            def query_food():
                with Session(engine) as session:
                    query = select(FoodLog)
                    if meal_filter.value:
                        query = query.where(FoodLog.meal_type == meal_filter.value)
                    entries = session.exec(query.order_by(FoodLog.date.desc()).limit(400)).all()
                term = (search_input.value or "").strip().lower()
                if term:
                    entries = [e for e in entries if term in (e.food_name or "").lower() or term in (e.tag or "").lower()]
                return entries

            _DISPLAY = {"limit": 60}

            def render_list():
                list_container.clear()
                entries = query_food()
                filters_active = bool((search_input.value or "").strip() or meal_filter.value)
                if entries:
                    total = sum(e.calories or 0 for e in entries)
                    result_summary.set_text(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} · {total:,.0f} kcal")
                else:
                    result_summary.set_text("")
                shown = entries[:_DISPLAY["limit"]]
                with list_container:
                    if not entries:
                        if filters_active:
                            empty_state("No food matches these filters.", "search_off")
                        else:
                            empty_state("No food logged yet -- swipe right or tap \"Add\" to log your first entry.", "restaurant")
                    for group_date, day_entries in group_by_date(shown):
                        day_total = sum(e.calories or 0 for e in day_entries)
                        with ui.row().classes("w-full items-baseline justify-between mt-3 mb-1 px-1"):
                            ui.label(format_date_header(group_date)).classes("text-xs font-semibold uppercase tracking-wide").style(f"color:{TEXT_DIM}")
                            ui.label(f"{day_total:,.0f} kcal").classes("text-xs font-semibold").style(f"color:{TEXT_DIM}")
                        with ui.column().classes(LIST_GROUP):
                            for idx, e in enumerate(day_entries):
                                if idx:
                                    ui.element("div").classes("h-px w-full").style(f"background:{BORDER}")
                                icon, icon_color = MEAL_ICONS.get(e.meal_type, ("restaurant", TEXT_DIM))
                                with ui.row().classes("w-full items-center justify-between gap-2 px-3 py-2.5 no-wrap"):
                                    with ui.row().classes("flex-1 items-center gap-3 min-w-0 no-wrap"):
                                        ui.icon(icon).classes("text-xl shrink-0").style(f"color:{icon_color}")
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(e.food_name).classes("font-medium truncate w-full")
                                            sub = f"{(e.meal_type or 'meal').capitalize()}"
                                            if e.tag:
                                                sub += f" · {e.tag}"
                                            ui.label(sub).classes("text-xs truncate").style(f"color:{TEXT_DIM}")
                                    with ui.row().classes("items-center gap-0.5 shrink-0 no-wrap"):
                                        ui.label(f"{e.calories or 0:,.0f} kcal").classes("font-semibold text-sm whitespace-nowrap")
                                        ui.button(icon="content_copy", on_click=lambda _, eid=e.id: relog_entry(eid)).props("flat round dense size=sm").tooltip("Log this again today")
                                        ui.button(icon="edit", on_click=lambda _, eid=e.id: open_edit_food(eid)).props("flat round dense size=sm").tooltip("Edit")
                                        ui.button(icon="delete", on_click=lambda _, eid=e.id: delete_entry(eid)).props("flat round dense color=red size=sm")
                    remaining = len(entries) - len(shown)
                    if remaining > 0:
                        def _more():
                            _DISPLAY["limit"] += 100
                            render_list()
                        ui.button(f"Show more ({remaining} remaining)", icon="expand_more", on_click=_more).props(
                            "flat no-caps color=primary").classes("self-center mt-2")

            def refresh():
                _DISPLAY["limit"] = 60   # reset to the top whenever filters change
                render_list()

            NUTRIENT_COPY_FIELDS = (
                "food_name", "barcode", "quantity_g", "calories", "protein_g", "carbs_g", "fat_g",
                "fiber_g", "sugar_g", "sodium_mg", "saturated_fat_g", "trans_fat_g",
                "added_sugar_g", "alcohol_g", "caffeine_mg",
            )

            def relog_entry(eid):
                """One-tap re-log: copy an existing entry onto today, keeping all
                its nutrition. The most common food-logging action by far."""
                with Session(engine) as session:
                    src = session.get(FoodLog, eid)
                    if not src:
                        return
                    data = {f: getattr(src, f) for f in NUTRIENT_COPY_FIELDS}
                    data.update(date=date.today(), meal_type=src.meal_type, tag=src.tag)
                    session.add(FoodLog(**data))
                    session.commit()
                ui.notify(f"Logged {data['food_name']} for today.", type="positive")
                refresh()

            def open_edit_food(eid):
                with Session(engine) as session:
                    e = session.get(FoodLog, eid)
                    if not e:
                        return
                    cur = {f: getattr(e, f) for f in NUTRIENT_COPY_FIELDS}
                    cur.update(date=e.date.isoformat(), meal_type=e.meal_type or "lunch", tag=e.tag or "")

                with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
                    section_header("Edit food entry", icon="edit", icon_color=INDIGO)
                    e_date = date_field("Date", value=cur["date"])
                    e_meal = segmented("Meal", {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"},
                                       cur["meal_type"] if cur["meal_type"] in ("breakfast", "lunch", "dinner", "snack") else "lunch")
                    e_name = ui.input(label="Food name", value=cur["food_name"]).classes("w-full")
                    e_qty = ui.number(label="Quantity (g)", value=cur["quantity_g"], format="%g").classes("w-full")
                    e_cal = ui.number(label="Calories", value=cur["calories"]).props(
                        'suffix="kcal" input-class="text-xl font-bold"'
                    ).classes("w-full")
                    with ui.grid().classes("w-full grid-cols-3 gap-x-3 gap-y-1"):
                        e_prot = ui.number(label="Protein (g)", value=cur["protein_g"]).classes("w-full")
                        e_carb = ui.number(label="Carbs (g)", value=cur["carbs_g"]).classes("w-full")
                        e_fat = ui.number(label="Fat (g)", value=cur["fat_g"]).classes("w-full")
                    e_tag = ui.select(TAG_OPTIONS, value=cur["tag"], label="Tag (context)").classes("w-full")

                    def save_edit():
                        with Session(engine) as session:
                            obj = session.get(FoodLog, eid)
                            if obj:
                                obj.date = date.fromisoformat(e_date.value)
                                obj.meal_type = e_meal.value
                                obj.food_name = e_name.value or obj.food_name
                                obj.quantity_g = e_qty.value or 0
                                obj.calories = e_cal.value
                                obj.protein_g = e_prot.value
                                obj.carbs_g = e_carb.value
                                obj.fat_g = e_fat.value
                                obj.tag = e_tag.value or None
                                session.add(obj)
                                session.commit()
                        dialog.close()
                        ui.notify("Food entry updated.", type="positive")
                        refresh()

                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                        ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                        ui.button("Save", on_click=save_edit).props("color=primary unelevated no-caps")
                dialog.open()

            def delete_entry(eid):
                with Session(engine) as session:
                    obj = session.get(FoodLog, eid)
                    if not obj:
                        return
                    snapshot = {f: getattr(obj, f) for f in NUTRIENT_COPY_FIELDS}
                    snapshot.update(date=obj.date, meal_type=obj.meal_type, tag=obj.tag)
                    session.delete(obj)
                    session.commit()

                def undo_delete():
                    with Session(engine) as session:
                        session.add(FoodLog(**snapshot))
                        session.commit()
                    ui.notify("Restored.", type="positive")
                    refresh()

                refresh()
                undo_banner(undo_container, f"Deleted {snapshot['food_name']}.", undo_delete)

            search_input.on_value_change(lambda e: refresh())
            meal_filter.on_value_change(lambda e: refresh())
            refresh()

        with ui.tab_panel(add_tab).classes("p-0 min-h-[70vh]"):
            def on_saved():
                refresh()
                quick_add_card.refresh()
                tabs.set_value(log_tab)

            with ui.column().classes("w-full items-center pt-4 gap-4"):
                @ui.refreshable
                def quick_add_card():
                    """Your most-logged foods as one-tap chips. Logging the same
                    handful of meals is the common case, so this skips the form
                    entirely -- tap a chip and it's on today's log."""
                    with Session(engine) as session:
                        recent = session.exec(
                            select(FoodLog).order_by(FoodLog.date.desc(), FoodLog.id.desc()).limit(120)
                        ).all()
                    seen, favourites = set(), []
                    for e in recent:
                        key = (e.food_name or "").strip().lower()
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        favourites.append(e)
                        if len(favourites) >= 8:
                            break
                    if not favourites:
                        return
                    with card_box().classes("w-full max-w-xl"):
                        section_header("Quick add", icon="bolt", icon_color=AMBER,
                                       subtitle="Tap a recent food to log it for today")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            for f in favourites:
                                icon, icon_color = MEAL_ICONS.get(f.meal_type, ("restaurant", TEXT_DIM))
                                with ui.button(on_click=lambda _, fid=f.id: quick_log(fid)).props(
                                    "outline dense no-caps"
                                ).classes("normal-case").style(f"border-color:{BORDER}; color:{TEXT};"):
                                    with ui.row().classes("items-center gap-2 no-wrap"):
                                        ui.icon(icon).classes("text-base").style(f"color:{icon_color}")
                                        with ui.column().classes("gap-0 items-start"):
                                            ui.label(f.food_name).classes("text-xs font-medium leading-tight")
                                            ui.label(f"{f.calories or 0:,.0f} kcal").classes("text-[10px] leading-tight").style(f"color:{TEXT_DIM}")

                def quick_log(fid):
                    relog_entry(fid)
                    quick_add_card.refresh()

                quick_add_card()
                render_add_food_form(on_saved=on_saved)


# ---------------------------------------------------------------------------
# Pantry
# ---------------------------------------------------------------------------
def pantry_page():
    page_header("Pantry", "What's in stock, with cost and macros.", icon="kitchen")

    @ui.refreshable
    def content():
        with Session(engine) as session:
            goals = session.exec(select(NutrientGoals)).first() or NutrientGoals()
            items = session.exec(select(PantryItem).where(PantryItem.status == "active")).all()

        total_cal = sum(i.calories or 0 for i in items)
        days_left = round(total_cal / goals.calories, 1) if goals.calories else 0
        stock_value = sum(i.price or 0 for i in items)

        summary_strip([
            ("Items in stock", str(len(items)), INDIGO),
            ("Est. runway", f"{days_left} days", EMERALD),
            ("Value in stock", f"{CUR}{stock_value:,.2f}", SKY) if stock_value else None,
        ])

        def resolve_item(item_id, status):
            with Session(engine) as session:
                item = session.get(PantryItem, item_id)
                if item:
                    item.status = status
                    item.resolved_at = datetime.utcnow()
                    session.add(item)
                    session.commit()
            content.refresh()

        expiring = [i for i in items if i.expiration_date and (i.expiration_date - date.today()).days <= 7]
        if expiring:
            with card_box().classes("w-full gap-2").style(f"border-color:{AMBER}66"):
                section_header("Expiring soon", icon="warning_amber", icon_color=AMBER, accent=AMBER)
                for i in sorted(expiring, key=lambda x: x.expiration_date):
                    with ui.row().classes("w-full items-center justify-between gap-2"):
                        ui.label(i.name).classes("text-sm")
                        render_expiry_badge(i.expiration_date)

        with ui.expansion("Add pantry item", icon="add").classes("w-full"):
            with ui.column().classes("gap-1 max-w-xl"):
                name_input = ui.input(label="Item name").props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
                    location_select = ui.select(["fridge", "freezer", "pantry"], value="pantry", label="Location").props("dense options-dense").classes("w-full")
                    macro_select = ui.select(
                        ["protein", "carbs", "fat", "produce", "dairy", "other"], value="other", label="Group"
                    ).props("dense options-dense").classes("w-full")
                    qty_input = ui.number(label="Quantity", value=1).props("dense").classes("w-full")
                    unit_select = ui.select(["unit", "g", "kg", "ml", "l"], value="unit", label="Unit").props("dense options-dense").classes("w-full")
                    price_input = ui.number(label=f"Price ({CUR})").props("dense").classes("w-full")
                    expiry_input = date_field("Expiration date")
                    cal_input = ui.number(label="Calories (total)").props("dense").classes("w-full")
                    protein_input = ui.number(label="Protein (g, total)").props("dense").classes("w-full")

                def add_item():
                    with Session(engine) as session:
                        item = PantryItem(
                            name=name_input.value or "Unnamed item",
                            location=location_select.value,
                            macro_group=macro_select.value,
                            quantity=qty_input.value or 1,
                            unit=unit_select.value,
                            price=price_input.value,
                            expiration_date=date.fromisoformat(expiry_input.value) if expiry_input.value else None,
                            purchase_date=date.today(),
                            calories=cal_input.value,
                            protein_g=protein_input.value,
                        )
                        session.add(item)
                        session.commit()
                    ui.notify("Added.", type="positive")
                    content.refresh()

                ui.button("Add item", on_click=add_item).props("color=primary unelevated")

        if not items:
            with card_box().classes("w-full"):
                ui.label("Your pantry is empty -- tap \"Add pantry item\" above to start tracking what's in stock.").classes(
                    "text-sm"
                ).style(f"color:{TEXT_DIM}")

        # soonest-to-expire first within each location; undated items sink to the bottom
        def expiry_sort_key(item):
            return (item.expiration_date is None, item.expiration_date or date.max)

        for location in ["fridge", "freezer", "pantry"]:
            location_items = sorted([i for i in items if i.location == location], key=expiry_sort_key)
            if not location_items:
                continue
            loc_icon, loc_color = LOCATION_ICONS.get(location, ("inventory_2", TEXT_DIM))
            loc_value = sum(i.price or 0 for i in location_items)
            with card_box().classes("w-full gap-2"):
                hdr = section_header(location.capitalize(), icon=loc_icon, icon_color=loc_color, count=len(location_items))
                if loc_value:
                    with hdr:
                        ui.label(f"{CUR}{loc_value:,.2f}").classes("text-xs").style(f"color:{TEXT_DIM}")
                for i in location_items:
                    macro_icon = MACRO_GROUP_ICONS.get(i.macro_group, "label")
                    with card_box().classes("w-full py-2 flex-row items-center justify-between gap-3").style(f"background:{SURFACE_2}"):
                        with ui.row().classes("items-center gap-3 min-w-0"):
                            ui.icon(macro_icon).classes("text-xl shrink-0").style(f"color:{TEXT_DIM}")
                            with ui.column().classes("gap-0 min-w-0"):
                                with ui.row().classes("items-center gap-2 flex-wrap"):
                                    ui.label(i.name).classes("font-semibold")
                                    render_expiry_badge(i.expiration_date)
                                qty = f"{i.quantity:g}{i.unit}"
                                price = f" · {CUR}{i.price:,.2f}" if i.price else ""
                                group = f" · {i.macro_group}" if i.macro_group and i.macro_group != "other" else ""
                                ui.label(f"{qty}{price}{group}").classes("text-xs").style(f"color:{TEXT_DIM}")
                        with ui.row().classes("gap-1 shrink-0"):
                            ui.button("Consumed", on_click=lambda _, iid=i.id: resolve_item(iid, "consumed")).props("flat dense color=green size=sm")
                            ui.button("Wasted", on_click=lambda _, iid=i.id: resolve_item(iid, "thrown_away")).props("flat dense color=red size=sm")

        with Session(engine) as session:
            wasted = session.exec(select(PantryItem).where(PantryItem.status.in_(["thrown_away", "expired"]))).all()
        if wasted:
            total_wasted = sum(w.price or 0 for w in wasted)
            with card_box().classes("w-full gap-1"):
                section_header("Money lost to waste", icon="delete_forever", icon_color=RED, accent=RED)
                ui.label(f"{CUR}{total_wasted:,.2f} across {len(wasted)} item(s), all-time").classes("text-sm").style(f"color:{TEXT_DIM}")

    content()


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
def subscriptions_page():
    page_header("Subscriptions", "Recurring spend and what's due next.", icon="autorenew")

    @ui.refreshable
    def content():
      with Session(engine) as session:
        subs = session.exec(select(Subscription)).all()
        categories = session.exec(select(Category)).all()
      category_options = {c.id: _category_label(c, categories) for c in categories}
      default_sub_category = next((c.id for c in categories if c.name == "Subscriptions"), None)
      active_subs = [s for s in subs if s.active]
      monthly_total = sum(s.amount if s.billing_cycle == "monthly" else s.amount / 12 for s in active_subs)
      installments = [s for s in active_subs if s.total_payments]
      remaining_owed = sum(s.amount * max(s.total_payments - s.payments_made, 0) for s in installments)

      summary_strip([
          ("Active subs", str(len(active_subs)), INDIGO),
          ("Monthly total", f"{CUR}{monthly_total:,.2f}", EMERALD),
          ("Owed on installments", f"{CUR}{remaining_owed:,.2f}", AMBER) if installments else None,
      ])

      # --- detected recurring payments not yet tracked as subscriptions ---
      with Session(engine) as session:
        all_transactions = session.exec(select(Transaction)).all()
      everyday_ids = frozenset(c.id for c in categories if c.name in NON_SUBSCRIPTION_CATEGORIES)
      detected = detect_recurring_transactions(all_transactions, [s.name for s in subs], everyday_ids)

      def add_detected_subscription(cand):
        with Session(engine) as session:
            session.add(Subscription(
                name=cand["merchant"],
                amount=cand["typical_amount"],
                billing_cycle=cand["cadence"],
                category_id=cand["category_id"],
                payments_made=0,
            ))
            session.commit()
        ui.notify(f"Added {cand['merchant']} as a subscription.", type="positive")
        content.refresh()

      def mark_payment_made(sid):
        with Session(engine) as session:
            sub = session.get(Subscription, sid)
            if not sub:
                return
            category_id = sub.category_id
            if category_id is None:
                fallback = session.exec(select(Category).where(Category.name == "Subscriptions")).first()
                category_id = fallback.id if fallback else None
            session.add(Transaction(
                date=date.today(), amount=sub.amount, merchant=sub.name,
                category_id=category_id, payment_method="Card",
                notes=f"Subscription payment ({sub.billing_cycle})",
                is_subscription_payment=True,
            ))
            if sub.total_payments is not None:
                sub.payments_made += 1
                if sub.payments_made >= sub.total_payments:
                    sub.active = False
            if sub.next_payment_date and sub.active:
                if sub.billing_cycle == "monthly":
                    month = sub.next_payment_date.month + 1
                    year = sub.next_payment_date.year + (1 if month > 12 else 0)
                    month = month if month <= 12 else 1
                    day = min(sub.next_payment_date.day, 28)
                    sub.next_payment_date = date(year, month, day)
                else:
                    sub.next_payment_date = date(sub.next_payment_date.year + 1, sub.next_payment_date.month, sub.next_payment_date.day)
            session.add(sub)
            session.commit()
        content.refresh()

      def set_sub_active(sid, active):
        with Session(engine) as session:
            sub = session.get(Subscription, sid)
            if sub:
                sub.active = active
                session.add(sub)
                session.commit()
        content.refresh()

      def delete_sub(sid):
        with Session(engine) as session:
            sub = session.get(Subscription, sid)
            if sub:
                session.delete(sub)
                session.commit()
        content.refresh()

      if detected:
        with card_box().classes("w-full"):
            section_header(
                "Possible recurring payments", icon="auto_awesome", icon_color=AMBER,
                subtitle="Merchants you're charged by on a regular cadence but haven't set up as a subscription yet.",
            )
            for cand in detected:
                cadence_word = "month" if cand["cadence"] == "monthly" else "year"
                with card_box().classes("w-full py-3 flex-row items-center justify-between gap-3").style(f"background:{SURFACE_2}"):
                    with ui.column().classes("gap-0"):
                        ui.label(f"{cand['merchant']} · {CUR}{cand['typical_amount']:,.2f}/{cadence_word}").classes("font-semibold")
                        ui.label(
                            f"Seen {cand['count']} times · {cand['cadence']} · last {format_date_header(cand['last_seen']).lower()}"
                        ).classes("text-xs").style(f"color:{TEXT_DIM}")
                    ui.button(
                        "Add as subscription", icon="add",
                        on_click=lambda _, c=cand: add_detected_subscription(c),
                    ).props("flat dense no-caps color=primary")

      with ui.expansion("Add subscription", icon="add").classes("w-full"):
        with ui.column().classes("gap-1 max-w-xl w-full"):
            name_input = ui.input(label="Name (e.g. Amazon Prime, or 'Sofa installments')").props("dense").classes("w-full")
            # Caption above (not a floating label): the big text-2xl value would
            # otherwise overlap a floating field label.
            ui.label("Amount per payment").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")
            amount_input = ui.number(placeholder="0.00", format="%.2f").props(
                f'prefix="{CUR}" input-class="text-2xl font-bold"'
            ).classes("w-full")
            cycle_select = segmented("Billing cycle", {"monthly": "Monthly", "yearly": "Yearly"}, "monthly")
            with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1 mt-2"):
                next_date_input = date_field("Next payment date")
                category_select = ui.select(category_options, value=default_sub_category, label="Category").props("dense options-dense").classes("w-full")

            installment_toggle = ui.switch("Fixed-term (installment plan, not ongoing)", value=False).props("dense color=primary").classes("mt-2")
            ui.label(
                "e.g. an item paid off over 5 monthly payments -- tracks progress and stops "
                "counting once it's paid off, instead of continuing forever like a real subscription."
            ).classes("text-xs -mt-1 mb-1").style(f"color:{TEXT_DIM}")
            total_payments_input = ui.number(label="Total number of payments", value=3, format="%.0f").props("dense").classes("w-40")
            total_payments_input.set_visibility(False)
            installment_toggle.on_value_change(lambda e: total_payments_input.set_visibility(e.value))

            def add_sub():
                with Session(engine) as session:
                    sub = Subscription(
                        name=name_input.value or "Unnamed",
                        amount=amount_input.value or 0,
                        billing_cycle=cycle_select.value,
                        next_payment_date=date.fromisoformat(next_date_input.value) if next_date_input.value else None,
                        category_id=category_select.value,
                        total_payments=int(total_payments_input.value) if installment_toggle.value and total_payments_input.value else None,
                        payments_made=0,
                    )
                    session.add(sub)
                    session.commit()
                ui.notify("Subscription added.", type="positive")
                content.refresh()

            ui.button("Add subscription", on_click=add_sub).props("color=primary unelevated")

      if not subs:
        with card_box().classes("w-full"):
            empty_state("No subscriptions yet -- add one above, or check \"Possible recurring payments\" if you have regular charges.", "autorenew")

      for s in subs:
        is_installment = s.total_payments is not None
        is_completed = is_installment and s.payments_made >= s.total_payments
        row_icon = "check_circle" if is_completed else ("pause_circle" if not s.active else ("receipt_long" if is_installment else "autorenew"))
        row_color = EMERALD if is_completed else (TEXT_DIM if not s.active else (AMBER if is_installment else INDIGO))
        with card_box().classes("w-full py-3 flex-row items-center justify-between gap-2 no-wrap"):
            with ui.row().classes("flex-1 items-center gap-3 min-w-0 no-wrap"):
                ui.icon(row_icon).classes("text-2xl shrink-0").style(f"color:{row_color}")
                with ui.column().classes("gap-0 min-w-0"):
                    with ui.row().classes("items-center gap-2 min-w-0 no-wrap w-full"):
                        ui.label(s.name).classes("font-semibold truncate" + ("" if s.active else " line-through")).style(
                            f"color:{TEXT if s.active else TEXT_DIM}"
                        )
                        if is_completed:
                            badge("Paid off", EMERALD)
                        elif not s.active:
                            badge("Paused", TEXT_DIM)
                        elif is_installment:
                            badge("Installment", AMBER)
                    ui.label(f"{CUR}{s.amount:,.2f} / {s.billing_cycle}").classes("text-xs").style(f"color:{TEXT_DIM}")
                    if is_installment:
                        remaining = max(s.total_payments - s.payments_made, 0)
                        ui.label(f"Payment {min(s.payments_made + 1, s.total_payments)} of {s.total_payments} · {CUR}{remaining * s.amount:,.2f} left").classes("text-xs").style(f"color:{TEXT_DIM}")
            with ui.row().classes("items-center gap-1 shrink-0 no-wrap"):
                if s.active and not is_completed:
                    ui.button("Mark paid", icon="check", on_click=lambda _, sid=s.id: mark_payment_made(sid)).props("flat dense no-caps color=primary")
                if not is_installment:
                    ui.switch(value=s.active, on_change=lambda e, sid=s.id: set_sub_active(sid, e.value)).props(
                        "color=primary dense"
                    ).tooltip("Active / Paused")
                ui.button(icon="delete", on_click=lambda _, sid=s.id: delete_sub(sid)).props("flat round dense color=red")

    content()


# ---------------------------------------------------------------------------
# Prices (grocery price / inflation tracking)
# ---------------------------------------------------------------------------
def prices_page():
    page_header("Prices", "Track what staple grocery items cost over time.", icon="trending_up")

    with card_box().classes("w-full max-w-xl"):
        section_header("Log a price", icon="sell", icon_color=EMERALD)
        item_input = ui.input(label="Item name (be consistent, e.g. 'Milk 2L')").props("dense").classes("w-full")
        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
            price_input = ui.number(label=f"Price ({CUR})", format="%.2f").props("dense").classes("w-full")
            store_input = ui.input(label="Store (optional)").props("dense").classes("w-full")
            date_input = date_field("Date", value=date.today().isoformat())
        result_label = ui.label().style(f"color:{EMERALD}")

        def submit():
            with Session(engine) as session:
                obs = PriceObservation(
                    item_name=item_input.value or "",
                    price=price_input.value or 0,
                    store=store_input.value or None,
                    date=date.fromisoformat(date_input.value),
                )
                session.add(obs)
                session.commit()
            result_label.set_text("Logged!")

        ui.button("Log price", on_click=submit).props("color=primary unelevated")

    with Session(engine) as session:
        all_obs = session.exec(select(PriceObservation)).all()
    item_names = sorted({o.item_name for o in all_obs})

    COMPARE_ALL = "__compare_all__"

    if not item_names:
        with card_box().classes("w-full"):
            empty_state("No prices logged yet -- log the same item a few times over weeks to see its trend.", "trending_up")

    if item_names:
        with card_box().classes("w-full"):
            section_header("Price history", icon="query_stats", icon_color=VIOLET)
            select_options = {name: name for name in item_names}
            if len(item_names) > 1:
                # indexed comparison overlays every item on one chart, each
                # rebased to 100 at its first reading so items at very
                # different price points are comparable on relative change.
                select_options = {COMPARE_ALL: "★ Compare all (indexed)", **select_options}
            item_select = ui.select(
                select_options, value=item_names[0], label="Item"
            ).props("dense options-dense").classes("w-64")
            history_container = ui.column().classes("w-full gap-1")

            def render_comparison():
                with Session(engine) as session:
                    all_obs_c = session.exec(select(PriceObservation).order_by(PriceObservation.date)).all()
                by_item = {}
                for o in all_obs_c:
                    by_item.setdefault(o.item_name, []).append(o)

                all_dates = sorted({o.date.isoformat() for o in all_obs_c})
                series = []
                for idx, (name, obs) in enumerate(sorted(by_item.items())):
                    if len(obs) < 2 or not obs[0].price:
                        continue
                    base = obs[0].price
                    by_date = {o.date.isoformat(): round(o.price / base * 100, 1) for o in obs}
                    # align to the shared x-axis; None lets ECharts connect across gaps
                    data = [by_date.get(d) for d in all_dates]
                    series.append({
                        "name": name, "data": data, "type": "line", "smooth": True,
                        "connectNulls": True, "showSymbol": False,
                        "lineStyle": {"color": CHART_PALETTE[idx % len(CHART_PALETTE)], "width": 2},
                        "itemStyle": {"color": CHART_PALETTE[idx % len(CHART_PALETTE)]},
                    })
                with history_container:
                    if len(series) < 2:
                        ui.label(
                            "Log at least two prices for two or more items to compare them."
                        ).classes("text-sm").style(f"color:{TEXT_DIM}")
                        return
                    ui.label(
                        "Each item rebased to 100 at its first logged price -- lines rising above "
                        "100 have gotten more expensive, in percentage terms."
                    ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")
                    ui.echart({
                        "backgroundColor": "transparent",
                        "grid": {"left": 45, "right": 20, "top": 40, "bottom": 40},
                        "legend": {"textStyle": {"color": TEXT_DIM, "fontSize": 11}, "top": 0, "type": "scroll"},
                        "xAxis": {
                            "type": "category", "data": all_dates, "boundaryGap": False,
                            "axisLine": {"lineStyle": {"color": BORDER}},
                            "axisLabel": {"color": TEXT_DIM, "fontSize": 10},
                        },
                        "yAxis": {
                            "type": "value", "axisLine": {"show": False},
                            "axisLabel": {"color": TEXT_DIM, "formatter": "{value}"},
                            "splitLine": {"lineStyle": {"color": BORDER}},
                        },
                        "tooltip": {"trigger": "axis"},
                        "series": series,
                    }).classes("w-full h-72")

            def render_history():
                history_container.clear()
                if item_select.value == COMPARE_ALL:
                    render_comparison()
                    return
                with Session(engine) as session:
                    obs = session.exec(
                        select(PriceObservation).where(PriceObservation.item_name == item_select.value).order_by(PriceObservation.date)
                    ).all()
                with history_container:
                    if len(obs) < 2:
                        ui.label("Log at least two prices for this item to see a trend.").classes("text-sm").style(f"color:{TEXT_DIM}")
                    else:
                        change = ((obs[-1].price - obs[0].price) / obs[0].price) * 100 if obs[0].price else 0
                        color = RED if change > 0 else EMERALD
                        ui.label(f"{change:+.1f}% since first logged").style(f"color:{color}").classes("text-sm mb-2")

                        dates = [o.date.isoformat() for o in obs]
                        prices = [o.price for o in obs]
                        ui.echart({
                            "backgroundColor": "transparent",
                            "grid": {"left": 50, "right": 20, "top": 20, "bottom": 40},
                            "xAxis": {
                                "type": "category", "data": dates, "boundaryGap": False,
                                "axisLine": {"lineStyle": {"color": BORDER}},
                                "axisLabel": {"color": TEXT_DIM, "fontSize": 10},
                            },
                            "yAxis": {
                                "type": "value",
                                "axisLine": {"show": False},
                                "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                                "splitLine": {"lineStyle": {"color": BORDER}},
                            },
                            "tooltip": {"trigger": "axis"},
                            "series": [{
                                "data": prices, "type": "line", "smooth": True,
                                "lineStyle": {"color": INDIGO, "width": 3},
                                "itemStyle": {"color": INDIGO},
                                "areaStyle": {"color": "rgba(99,102,241,0.15)"},
                            }],
                        }).classes("w-full h-64")

                        # monthly averages, nicely formatted (e.g. "Jul 2026" not "2026-07")
                        monthly = {}
                        for o in obs:
                            key = (o.date.year, o.date.month)
                            monthly.setdefault(key, []).append(o.price)
                        monthly_avgs = sorted(monthly.items())

                        if len(monthly_avgs) > 1:
                            ui.label("Monthly average").classes("text-xs font-semibold uppercase tracking-wide mt-3").style(f"color:{TEXT_DIM}")
                            with ui.row().classes("w-full gap-4 flex-wrap mt-1"):
                                for (year, month), vals in monthly_avgs:
                                    label = date(year, month, 1).strftime("%b %Y")
                                    avg = sum(vals) / len(vals)
                                    with ui.column().classes("gap-0"):
                                        ui.label(label).classes("text-xs").style(f"color:{TEXT_DIM}")
                                        ui.label(f"{CUR}{avg:,.2f}").classes("text-sm font-semibold")

                    # full history, newest first, grouped by date, with edit/delete
                    ui.label(f"All logged prices ({len(obs)})").classes("text-xs font-semibold uppercase tracking-wide mt-4").style(f"color:{TEXT_DIM}")
                    for group_date, day_obs in group_by_date(list(reversed(obs))):
                        ui.label(format_date_header(group_date)).classes("text-xs mt-2").style(f"color:{TEXT_DIM}")
                        for o in day_obs:
                            with card_box().classes("w-full py-2 flex-row items-center justify-between gap-2"):
                                with ui.column().classes("gap-0"):
                                    ui.label(f"{CUR}{o.price:,.2f}").classes("font-semibold")
                                    if o.store:
                                        ui.label(o.store).classes("text-xs").style(f"color:{TEXT_DIM}")
                                with ui.row().classes("gap-1"):
                                    ui.button(icon="edit", on_click=lambda _, ob=o: open_edit_dialog(ob)).props("flat round dense")
                                    ui.button(icon="delete", on_click=lambda _, oid=o.id: delete_price(oid)).props("flat round dense color=red")

            def open_edit_dialog(obs):
                with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2"):
                    ui.label("Edit price").classes("text-lg font-semibold")
                    edit_price = ui.number(label=f"Price ({CUR})", value=obs.price, format="%.2f").classes("w-full")
                    edit_store = ui.input(label="Store", value=obs.store or "").props("dense").classes("w-full")
                    edit_date = date_field("Date", value=obs.date.isoformat())

                    def save():
                        with Session(engine) as session:
                            db_obs = session.get(PriceObservation, obs.id)
                            if db_obs:
                                db_obs.price = edit_price.value or 0
                                db_obs.store = edit_store.value or None
                                db_obs.date = date.fromisoformat(edit_date.value)
                                session.add(db_obs)
                                session.commit()
                        dialog.close()
                        render_history()

                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                        ui.button("Cancel", on_click=dialog.close).props("flat")
                        ui.button("Save", on_click=save).props("color=primary unelevated")
                dialog.open()

            def delete_price(observation_id):
                with Session(engine) as session:
                    obs = session.get(PriceObservation, observation_id)
                    if obs:
                        session.delete(obs)
                        session.commit()
                render_history()

            item_select.on_value_change(lambda e: render_history())
            render_history()


# ---------------------------------------------------------------------------
# Caloric ROI Forecast
# ---------------------------------------------------------------------------
def forecast_page():
    page_header("Forecast",
                "Where your weight and spending are headed if your last 30 days continue.",
                icon="insights")

    months_select = ui.select({1: "1 month", 6: "6 months", 12: "12 months"}, value=6, label="Time horizon").props("dense options-dense").classes("w-48")
    forecast_container = ui.column().classes("w-full gap-4")

    def render():
        forecast_container.clear()
        with Session(engine) as session:
            result = compute_forecast(session, months_select.value)

        with forecast_container:
            if not result["available"]:
                with card_box().classes("w-full"):
                    section_header("Missing info needed for a forecast", icon="info", icon_color=AMBER, accent=AMBER)
                    missing = ", ".join(result["missing_fields"])
                    ui.label(f"Add the following on the Profile & Goals page: {missing}.").classes("text-sm").style(f"color:{TEXT_DIM}")
                    ui.link("Go to Profile & Goals", "/profile").classes("no-underline text-sm mt-2").style(f"color:{INDIGO}")
                return

            with ui.expansion("How this is calculated", icon="info").props("dense").classes("w-full"):
                ui.label(
                    "Maintenance calories are estimated with the Mifflin-St Jeor formula, scaled by your "
                    "activity level -- a population-average estimate, not a measurement of your actual "
                    "metabolism (real TDEE commonly varies ±10-20% between people with identical stats). "
                    "\"Recent habits\" means your trailing 30-day daily average calories and spending. Weight "
                    "change is projected using the standard ~7,700 kcal ≈ 1kg rule of thumb. This is a "
                    "projection of current trends, not a guarantee, medical advice, or financial advice."
                ).classes("text-xs").style(f"color:{TEXT_DIM}")

            calib = result.get("calibrated")
            with ui.row().classes("w-full gap-4 flex-wrap items-stretch"):
                activity_short = result["activity_level"].replace("_", " ")
                if result.get("tdee_source") == "calibrated":
                    maint_sub, maint_color = "calibrated from your own data", VIOLET
                else:
                    maint_sub, maint_color = f"BMR {result['bmr']:,.0f} × {activity_short} activity (formula)", INDIGO
                stat_card("Estimated maintenance", f"{result['tdee']:,.0f} kcal/day", maint_sub, maint_color, icon="local_fire_department")
                delta = result["daily_calorie_delta"]
                delta_label = f"{delta:+,.0f} kcal/day" if delta else "0 kcal/day"
                stat_card("Your recent average", f"{result['avg_daily_calories']:,.0f} kcal/day", f"{delta_label} vs. maintenance", EMERALD if delta <= 0 else AMBER, icon="restaurant")
                stat_card("Recent daily spend", f"{CUR}{result['avg_daily_spend']:,.2f}", "trailing 30-day average", SKY, icon="account_balance_wallet")

            if calib:
                with card_box().classes("w-full"):
                    section_header("Calibrated to your metabolism", icon="science", icon_color=VIOLET,
                                   subtitle="Measured from your own logs, not a population-average formula.")
                    ui.label(
                        f"Over {calib['span_days']} days your weight changed {calib['weight_change_kg']:+.2f} kg while "
                        f"averaging {calib['avg_intake']:,.0f} kcal/day (across {calib['logged_days']} logged days). "
                        f"By energy balance that implies a real maintenance of ~{calib['tdee']:,.0f} kcal/day, versus the "
                        f"formula's {result['tdee_formula']:,.0f}. The projection below uses this calibrated figure."
                    ).classes("text-xs").style(f"color:{TEXT_DIM}")
            else:
                with card_box().classes("w-full py-3").style(f"background:{SURFACE_2}"):
                    ui.label(
                        "Tip: log your weight and food for a couple of weeks and this switches to a maintenance "
                        "figure calibrated from your actual data instead of the formula."
                    ).classes("text-xs").style(f"color:{TEXT_DIM}")

            # --- weight projection ---
            with card_box().classes("w-full"):
                change = result["projected_weight_change_kg"]
                direction = "loss" if change < 0 else ("gain" if change > 0 else "change")
                color = EMERALD if change <= 0 else AMBER
                section_header(f"Projected weight {direction}", icon="monitor_weight", icon_color=color)
                ui.label(
                    f"{result['current_weight_kg']:.1f}kg → {result['projected_end_weight_kg']:.1f}kg "
                    f"over {result['months']} month(s) ({change:+.1f}kg)"
                ).style(f"color:{color}").classes("text-sm mb-2")

                months_list = [w["month"] for w in result["weight_series"]]
                weights = [w["projected_weight_kg"] for w in result["weight_series"]]
                ui.echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 50, "right": 20, "top": 20, "bottom": 30},
                    "xAxis": {
                        "type": "category", "data": [f"M{m}" for m in months_list],
                        "axisLine": {"lineStyle": {"color": BORDER}},
                        "axisLabel": {"color": TEXT_DIM, "fontSize": 10},
                    },
                    "yAxis": {
                        "type": "value",
                        "axisLine": {"show": False},
                        "axisLabel": {"color": TEXT_DIM, "formatter": "{value}kg"},
                        "splitLine": {"lineStyle": {"color": BORDER}},
                    },
                    "tooltip": {"trigger": "axis"},
                    "series": [{
                        "data": weights, "type": "line", "smooth": True,
                        "lineStyle": {"color": color, "width": 3},
                        "itemStyle": {"color": color},
                        "areaStyle": {"color": "rgba(52,211,153,0.12)" if change <= 0 else "rgba(245,158,11,0.12)"},
                    }],
                }).classes("w-full h-56")

            # --- spending projection ---
            with card_box().classes("w-full"):
                section_header("Projected spending", icon="savings", icon_color=SKY)
                spend_line = f"{CUR}{result['projected_total_spend']:,.2f} over {result['months']} month(s) at your recent pace"
                ui.label(spend_line).classes("text-sm mb-2").style(f"color:{TEXT_DIM}")

                if result["projected_budget_pace"] is not None:
                    over_under = result["projected_over_under_budget"]
                    budget_color = RED if over_under > 0 else EMERALD
                    verb = "over" if over_under > 0 else "under"
                    ui.label(
                        f"{CUR}{abs(over_under):,.2f} {verb} your budget pace of {CUR}{result['projected_budget_pace']:,.2f} "
                        f"({CUR}{result['monthly_budget_target']:,.2f}/month target)"
                    ).style(f"color:{budget_color}").classes("text-sm mb-2")
                else:
                    ui.label("Set a monthly budget target on Profile & Goals to compare against.").classes("text-xs").style(f"color:{TEXT_DIM}")

                spend_months = [s["month"] for s in result["spend_series"]]
                cumulative = [s["cumulative_spend"] for s in result["spend_series"]]
                series = [{
                    "name": "Projected spend", "data": cumulative, "type": "line", "smooth": True,
                    "lineStyle": {"color": INDIGO, "width": 3},
                    "itemStyle": {"color": INDIGO},
                    "areaStyle": {"color": "rgba(99,102,241,0.12)"},
                }]
                if result["projected_budget_pace"] is not None:
                    budget_line = [round(result["monthly_budget_target"] * m, 2) for m in spend_months]
                    series.append({
                        "name": "Budget pace", "data": budget_line, "type": "line",
                        "lineStyle": {"color": TEXT_DIM, "width": 2, "type": "dashed"},
                        "itemStyle": {"color": TEXT_DIM},
                    })
                ui.echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 60, "right": 20, "top": 20, "bottom": 30},
                    "xAxis": {
                        "type": "category", "data": [f"M{m}" for m in spend_months],
                        "axisLine": {"lineStyle": {"color": BORDER}},
                        "axisLabel": {"color": TEXT_DIM, "fontSize": 10},
                    },
                    "yAxis": {
                        "type": "value",
                        "axisLine": {"show": False},
                        "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                        "splitLine": {"lineStyle": {"color": BORDER}},
                    },
                    "tooltip": {"trigger": "axis"},
                    "series": series,
                }).classes("w-full h-56")

    months_select.on_value_change(lambda e: render())
    render()


# ---------------------------------------------------------------------------
# Profile & Goals
# ---------------------------------------------------------------------------
def profile_page():
    page_header("Profile & Goals", "Your details, targets and weight — what the reference calcs use.", icon="badge")

    with Session(engine) as session:
        profile = session.exec(select(UserProfile)).first() or UserProfile()
        goals = session.exec(select(NutrientGoals)).first() or NutrientGoals()
        overall_budget = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711

    # Shared caption-above field wrapper -- a small caption in TEXT_DIM sitting
    # above a light outlined input, used across every card on the page so the
    # form fields share one rhythm instead of each card inventing its own.
    def capfield(label, builder):
        with ui.column().classes("gap-1 w-full"):
            ui.label(label).classes("text-xs font-medium").style(f"color:{TEXT_DIM}")
            return builder()

    age = calculate_age(profile.date_of_birth)
    with Session(engine) as _s:
        latest_w = _s.exec(select(WeightLog).order_by(WeightLog.date.desc())).first()

    summary_strip([
        ("Age", str(age) if age else "—", INDIGO),
        ("Height", f"{profile.height_cm:.0f} cm" if profile.height_cm else "—", SKY),
        ("Latest weight", f"{latest_w.weight_kg:.1f} kg" if latest_w else "—", EMERALD),
        ("Calorie target", f"{goals.calories:,.0f}" if goals.calories else "—", AMBER),
    ], width_class="max-w-2xl")

    with card_box().classes("w-full max-w-2xl").style(f"border-left:3px solid {INDIGO}"):
        section_header("About you", icon="person", icon_color=INDIGO)

        # Caption-above layout so the grid columns line up (date_field is already
        # caption-above; the others were floating-label at a different height).
        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3 items-start"):
            dob_input = date_field("Date of birth", value=profile.date_of_birth.isoformat() if profile.date_of_birth else None)
            height_input = capfield("Height (cm)", lambda: ui.number(value=profile.height_cm).props("dense outlined").classes("w-full"))
            sex_select = capfield("Sex", lambda: ui.select(["male", "female", "other"], value=profile.sex).props("dense outlined options-dense").classes("w-full"))
            activity_select = capfield("Activity level", lambda: ui.select(ACTIVITY_LEVEL_OPTIONS, value=profile.activity_level).props("dense outlined options-dense").classes("w-full"))
        profile_result = ui.label().classes("text-sm").style(f"color:{EMERALD}")

        def save_profile():
            with Session(engine) as session:
                p = session.exec(select(UserProfile)).first() or UserProfile()
                p.date_of_birth = date.fromisoformat(dob_input.value) if dob_input.value else None
                p.height_cm = height_input.value
                p.sex = sex_select.value
                p.activity_level = activity_select.value
                session.add(p)
                session.commit()
            profile_result.set_text("Saved!")

        with ui.row().classes("w-full justify-end mt-1"):
            ui.button("Save profile", on_click=save_profile).props("color=primary unelevated no-caps")

    ui.separator().classes("w-full max-w-2xl my-4").style(f"background:{BORDER}")
    with ui.column().classes("w-full max-w-2xl gap-3"):
        section_header("Weight", icon="monitor_weight", icon_color=EMERALD)

        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3 items-start max-w-md"):
            weight_date_input = date_field("Date", value=date.today().isoformat())
            weight_input = capfield("Weight (kg)", lambda: ui.number().props("dense outlined").classes("w-full"))
        weight_result = ui.label().classes("text-sm").style(f"color:{EMERALD}")

        weight_chart_container = ui.column().classes("w-full gap-2 mt-3")
        weight_list_container = ui.column().classes("w-full gap-1 mt-3")

        def log_weight():
            with Session(engine) as session:
                entry_date = date.fromisoformat(weight_date_input.value) if weight_date_input.value else date.today()
                session.add(WeightLog(date=entry_date, weight_kg=weight_input.value or 0))
                session.commit()
            weight_result.set_text("Logged!")
            weight_input.value = None
            render_weight_chart()
            render_weight_list()

        with ui.row().classes("w-full justify-end mt-1"):
            ui.button("Log weight", on_click=log_weight).props("color=primary unelevated no-caps")

        window_options = {"1d": "1 day", "3d": "3 day", "1w": "1 week", "1m": "1 month",
                           "3m": "3 month", "6m": "6 month", "1y": "1 year"}
        window_select = ui.select(window_options, value="1w", label="Trend smoothing").props("dense outlined options-dense").classes("w-40 mt-3")
        ui.label(
            "Body weight bounces daily from water and food -- this averages readings over the "
            "selected window so the real trend is easier to see than the raw scale number alone."
        ).classes("text-xs").style(f"color:{TEXT_DIM}")

        def render_weight_chart():
            weight_chart_container.clear()
            with Session(engine) as session:
                trend = compute_weight_trend(session, WEIGHT_TREND_WINDOWS.get(window_select.value, 7))

            with weight_chart_container:
                if not trend["available"] or trend["num_entries"] < 2:
                    # Compact placeholder rather than a tall empty chart void: a
                    # centred hint in a dashed frame that fills only what it needs.
                    with ui.column().classes(
                            "w-full items-center justify-center gap-1 py-6 rounded-xl").style(
                            f"border:1px dashed {BORDER}"):
                        ui.icon("show_chart").classes("text-3xl").style(f"color:{TEXT_DIM}")
                        ui.label("Log at least two weigh-ins to see your trend.").classes(
                            "text-sm").style(f"color:{TEXT_DIM}")
                    return

                change = trend["change_since_first_kg"]
                color = EMERALD if change <= 0 else AMBER
                with ui.row().classes("gap-8 mb-2"):
                    with ui.column().classes("gap-0"):
                        ui.label("Latest").classes("text-xs").style(f"color:{TEXT_DIM}")
                        ui.label(f"{trend['latest_weight_kg']:.1f}kg").classes("text-xl font-bold")
                    with ui.column().classes("gap-0"):
                        ui.label("Trend average").classes("text-xs").style(f"color:{TEXT_DIM}")
                        ui.label(f"{trend['latest_rolling_avg_kg']:.1f}kg").classes("text-xl font-bold")
                    with ui.column().classes("gap-0"):
                        ui.label("Since first log").classes("text-xs").style(f"color:{TEXT_DIM}")
                        ui.label(f"{change:+.1f}kg").classes("text-xl font-bold").style(f"color:{color}")

                dates = [p["date"].isoformat() for p in trend["points"]]
                raw = [p["raw_weight_kg"] for p in trend["points"]]
                smoothed = [p["rolling_avg_kg"] for p in trend["points"]]
                ui.echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 50, "right": 20, "top": 20, "bottom": 40},
                    "xAxis": {
                        "type": "category", "data": dates, "boundaryGap": False,
                        "axisLine": {"lineStyle": {"color": BORDER}},
                        "axisLabel": {"color": TEXT_DIM, "fontSize": 9, "rotate": 45},
                    },
                    "yAxis": {
                        "type": "value", "scale": True,
                        "axisLine": {"show": False},
                        "axisLabel": {"color": TEXT_DIM, "formatter": "{value}kg"},
                        "splitLine": {"lineStyle": {"color": BORDER}},
                    },
                    "tooltip": {"trigger": "axis"},
                    "series": [
                        {
                            "name": "Raw", "data": raw, "type": "line", "smooth": False,
                            "lineStyle": {"color": TEXT_DIM, "width": 1, "type": "dotted"},
                            "itemStyle": {"color": TEXT_DIM},
                            "symbolSize": 4,
                        },
                        {
                            "name": "Trend", "data": smoothed, "type": "line", "smooth": True,
                            "lineStyle": {"color": INDIGO, "width": 3},
                            "itemStyle": {"color": INDIGO},
                            "areaStyle": {"color": "rgba(99,102,241,0.10)"},
                            "symbolSize": 0,
                        },
                    ],
                }).classes("w-full h-64")

        window_select.on_value_change(lambda e: render_weight_chart())
        render_weight_chart()

        def render_weight_list():
            weight_list_container.clear()
            with Session(engine) as session:
                recent = session.exec(select(WeightLog).order_by(WeightLog.date.desc()).limit(10)).all()
            with weight_list_container:
                if not recent:
                    return
                with ui.expansion(f"Recent entries ({len(recent)})").classes("w-full"):
                    for entry in recent:
                        with ui.row().classes("w-full items-center justify-between py-1"):
                            ui.label(f"{entry.date} — {entry.weight_kg:.1f}kg").classes("text-sm")
                            ui.button(icon="delete", on_click=lambda _, eid=entry.id: delete_weight_entry(eid)).props("flat round dense color=red")

        def delete_weight_entry(entry_id):
            with Session(engine) as session:
                entry = session.get(WeightLog, entry_id)
                if entry:
                    session.delete(entry)
                    session.commit()
            render_weight_chart()
            render_weight_list()

        render_weight_list()

    ui.separator().classes("w-full max-w-2xl my-4").style(f"background:{BORDER}")
    with card_box().classes("w-full max-w-2xl").style(f"border-left:3px solid {INDIGO}"):
        section_header("Daily nutrient goals", icon="flag", icon_color=INDIGO,
                       subtitle="Tap the ⓘ next to any field for what it does and why it matters.")
        # Just-in-time estimate: fill the fields from the profile + latest weight
        # rather than entering them by hand. Pick a direction, tap Estimate, review, Save.
        with ui.row().classes("w-full items-center gap-x-2 gap-y-1 flex-wrap mb-3"):
            ui.label("Estimate for").classes("text-xs shrink-0").style(f"color:{TEXT_DIM}")
            est_dir = ui.toggle({"maintain": "Maintain", "lose": "Lose fat", "gain": "Build muscle"},
                                value="maintain").props(
                "no-caps unelevated dense toggle-color=primary").classes(
                "seg-toggle text-xs overflow-hidden").style(
                f"border:1px solid {BORDER}; border-radius:999px; background:{SURFACE_2};")
            est_btn = ui.button("Estimate", icon="auto_awesome").props("flat dense no-caps color=primary")
        with ui.column().classes("w-full gap-0 mt-1"):
            cal_g = goal_row("Calories", goals.calories, "calories", "kcal", INDIGO)
            protein_g = goal_row("Protein", goals.protein_g, "protein_g", "g", EMERALD)
            carbs_g = goal_row("Carbs", goals.carbs_g, "carbs_g", "g", AMBER)
            fat_g = goal_row("Fat", goals.fat_g, "fat_g", "g", VIOLET)
            fiber_g = goal_row("Fiber", goals.fiber_g, "fiber_g", "g", SKY)
            water_g = goal_row("Water", goals.water_ml, "water_ml", "ml", SKY, last=True)

        with ui.expansion("Daily limits", icon="do_not_disturb_on").props("dense").classes("w-full mt-3"):
            ui.label("Ceilings, not targets — a day is flagged when it goes over.").classes(
                "text-xs mb-1").style(f"color:{TEXT_DIM}")
            with ui.column().classes("w-full gap-0"):
                sugar_lim = goal_row("Added sugar", goals.sugar_limit_g, "sugar_limit_g", "g", RED)
                satfat_lim = goal_row("Saturated fat", goals.saturated_fat_limit_g, "saturated_fat_limit_g", "g", RED)
                transfat_lim = goal_row("Trans fat", goals.trans_fat_limit_g, "trans_fat_limit_g", "g", RED)
                sodium_lim = goal_row("Sodium", goals.sodium_limit_mg, "sodium_limit_mg", "mg", RED)
                alcohol_lim = goal_row("Alcohol", goals.alcohol_limit_g, "alcohol_limit_g", "g", RED)
                caffeine_lim = goal_row("Caffeine", goals.caffeine_limit_mg, "caffeine_limit_mg", "mg", RED, last=True)
        goals_result = ui.label().style(f"color:{EMERALD}").classes("mt-2")

        def _estimate_targets():
            direction = est_dir.value
            with Session(engine) as session:
                prof = session.exec(select(UserProfile)).first()
                lw = session.exec(select(WeightLog).order_by(WeightLog.date.desc())).first()
            age = calculate_age(prof.date_of_birth) if prof and prof.date_of_birth else None
            height = prof.height_cm if prof else None
            weight = lw.weight_kg if lw else None
            sex = prof.sex if prof else None
            activity = prof.activity_level if prof and prof.activity_level else "moderate"
            missing = []
            if not weight: missing.append("a weight entry")
            if not height: missing.append("height")
            if age is None: missing.append("date of birth")
            if missing:
                goals_result.set_text("Add " + ", ".join(missing) + " above so I can estimate.")
                goals_result.style(f"color:{AMBER}")
                return
            tdee = estimate_bmr(weight, height, age, sex) * ACTIVITY_MULTIPLIERS.get(activity, 1.55)
            if direction == "lose":
                cals, ppk = tdee - 500, 2.0
            elif direction == "gain":
                cals, ppk = tdee + 350, 2.0
            else:
                cals, ppk = tdee, 1.8
            cals = max(round(cals / 10) * 10, 1200)
            protein = round(weight * ppk)
            fat = round(cals * 0.25 / 9)
            cal_g.value = cals
            protein_g.value = protein
            fat_g.value = fat
            carbs_g.value = max(round((cals - protein * 4 - fat * 9) / 4), 0)
            fiber_g.value = round(cals / 1000 * 14)
            water_g.value = int(round(weight * 35 / 50) * 50)
            goals_result.set_text(f"Estimated for '{direction}' at {activity} activity — review and Save.")
            goals_result.style(f"color:{EMERALD}")

        est_btn.on("click", lambda: _estimate_targets())

        def save_goals():
            with Session(engine) as session:
                g = session.exec(select(NutrientGoals)).first() or NutrientGoals()
                g.calories = cal_g.value
                g.protein_g = protein_g.value
                g.carbs_g = carbs_g.value
                g.fat_g = fat_g.value
                g.fiber_g = fiber_g.value
                g.water_ml = water_g.value
                g.sugar_limit_g = sugar_lim.value
                g.saturated_fat_limit_g = satfat_lim.value
                g.trans_fat_limit_g = transfat_lim.value
                g.sodium_limit_mg = sodium_lim.value
                g.alcohol_limit_g = alcohol_lim.value
                g.caffeine_limit_mg = caffeine_lim.value
                session.add(g)
                session.commit()
            goals_result.set_text("Saved!")

        with ui.row().classes("w-full justify-end mt-1"):
            ui.button("Save goals", on_click=save_goals).props("color=primary unelevated no-caps")

    ui.separator().classes("w-full max-w-2xl my-4").style(f"background:{BORDER}")
    with ui.column().classes("w-full max-w-2xl gap-3"):
        section_header("Monthly budget target", icon="account_balance_wallet", icon_color=AMBER)
        budget_input = capfield(
            f"Overall monthly budget ({CUR})",
            lambda: ui.number(value=overall_budget.monthly_amount if overall_budget else None).props("dense outlined").classes("w-full max-w-xs"))
        budget_result = ui.label().classes("text-sm").style(f"color:{EMERALD}")

        def save_budget():
            with Session(engine) as session:
                target = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711
                if not target:
                    target = BudgetTarget(category_id=None, monthly_amount=budget_input.value or 0)
                else:
                    target.monthly_amount = budget_input.value or 0
                session.add(target)
                session.commit()
            budget_result.set_text("Saved!")

        with ui.row().classes("w-full justify-end mt-1"):
            ui.button("Save budget", on_click=save_budget).props("color=primary unelevated no-caps")

        with ui.expansion("Per-category budgets", icon="tune").props("dense").classes("w-full mt-1"):
            ui.label(
                "Optional -- caps a specific category instead of your whole spend, shown as its "
                "own progress bar on the dashboard alongside the overall budget above."
            ).classes("text-xs mb-1").style(f"color:{TEXT_DIM}")
            budget_section = ui.column().classes("w-full gap-2")

        def render_budget_section():
            budget_section.clear()
            with Session(engine) as session:
                targets = session.exec(select(BudgetTarget).where(BudgetTarget.category_id != None)).all()  # noqa: E711
                all_cats = session.exec(select(Category)).all()
            cats_by_id = {c.id: c for c in all_cats}
            budgeted_ids = {t.category_id for t in targets}
            available = [c for c in all_cats if c.id not in budgeted_ids]

            with budget_section:
                if not targets:
                    ui.label("No category budgets set yet.").classes("text-xs").style(f"color:{TEXT_DIM}")
                else:
                    for target in sorted(targets, key=lambda t: _category_label(cats_by_id[t.category_id], all_cats)):
                        category = cats_by_id[target.category_id]
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            ui.label(_category_label(category, all_cats)).classes("text-sm flex-1 min-w-0 truncate")
                            amount_input = ui.number(value=target.monthly_amount, format="%.2f").props("dense").classes("w-28 shrink-0")

                            def save_one(target_id=target.id, amount_input=amount_input):
                                with Session(engine) as session:
                                    t = session.get(BudgetTarget, target_id)
                                    t.monthly_amount = amount_input.value or 0
                                    session.add(t)
                                    session.commit()

                            def delete_one(target_id=target.id):
                                with Session(engine) as session:
                                    t = session.get(BudgetTarget, target_id)
                                    session.delete(t)
                                    session.commit()
                                render_budget_section()

                            ui.button(icon="save", on_click=save_one).props("flat dense round color=primary")
                            ui.button(icon="delete", on_click=delete_one).props("flat dense round color=red")

                if available:
                    with ui.row().classes("w-full items-end gap-2 mt-1 no-wrap"):
                        new_category_select = ui.select(
                            {c.id: _category_label(c, all_cats) for c in available}, label="Category"
                        ).props("dense options-dense").classes("flex-1 min-w-0")
                        new_amount_input = ui.number(label=f"{CUR} / month", format="%.2f").props("dense").classes("w-28 shrink-0")

                        def add_one():
                            if not new_category_select.value:
                                return
                            with Session(engine) as session:
                                session.add(BudgetTarget(
                                    category_id=new_category_select.value,
                                    monthly_amount=new_amount_input.value or 0,
                                ))
                                session.commit()
                            render_budget_section()

                        ui.button("Add", icon="add", on_click=add_one).props("flat dense no-caps")
                else:
                    ui.label("All categories have a budget set.").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")

        render_budget_section()

    ui.separator().classes("w-full max-w-2xl my-4").style(f"background:{BORDER}")
    with ui.column().classes("w-full max-w-2xl gap-3"):
        section_header("Backup", icon="cloud_download", icon_color=SKY,
                       subtitle="Everything in one JSON file -- transactions, income, food, water, weight, pantry, subscriptions, prices, budgets, goals, profile.")

        def export_backup():
            tables = {
                "transactions": Transaction, "income": Income, "food_log": FoodLog,
                "water_log": WaterLog, "weight_log": WeightLog, "pantry": PantryItem,
                "subscriptions": Subscription, "prices": PriceObservation,
                "budgets": BudgetTarget, "categories": Category,
                "profile": UserProfile, "goals": NutrientGoals, "settings": AppSettings,
            }
            payload = {"exported_at": datetime.utcnow().isoformat(), "app": "balance", "version": 1}
            with Session(engine) as session:
                for name, model in tables.items():
                    rows = session.exec(select(model)).all()
                    payload[name] = [
                        {k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
                         for k, v in r.model_dump().items()}
                        for r in rows
                    ]
            content = json.dumps(payload, indent=1)
            ui.download.content(content.encode("utf-8"), f"balance-backup-{date.today().isoformat()}.json", "application/json")
            ui.notify("Backup downloaded.", type="positive")

        ui.button("Download full backup", icon="download", on_click=export_backup).props("outline no-caps color=primary")
        ui.label(
            "Receipt photos live in data/receipts/ and aren't included -- copy that folder alongside this file for a complete backup."
        ).classes("text-xs").style(f"color:{TEXT_DIM}")

        ui.separator().classes("my-2").style(f"background:{BORDER}")
        ui.label("Automatic off-machine backups").classes("text-sm font-semibold").style(f"color:{TEXT}")
        with Session(engine) as _s:
            _mirror_now = _s.exec(select(AppSettings)).first()
        mirror_input = ui.input(
            label="Backup folder (optional)",
            value=(_mirror_now.backup_mirror_path if _mirror_now else "") or "",
            placeholder="e.g. D:\\Backups\\Balance, or a cloud-synced folder",
        ).props("dense clearable").classes("w-full")

        def save_mirror():
            path = (mirror_input.value or "").strip() or None
            with Session(engine) as session:
                row = session.exec(select(AppSettings)).first()
                row.backup_mirror_path = path
                session.add(row)
                session.commit()
            ui.notify("Off-machine backups enabled." if path else "Off-machine backups disabled.",
                      type="positive")

        ui.button("Save backup folder", icon="save", on_click=save_mirror).props("flat dense no-caps")
        ui.label(
            "The app already snapshots your database daily to data/backups/. Set a folder on a second drive or a "
            "cloud-synced location here and each snapshot is copied there too, so a single disk failure can't lose everything."
        ).classes("text-xs").style(f"color:{TEXT_DIM}")


# ---------------------------------------------------------------------------
# Settings: display currency, category management, and an optional PIN lock.
# ---------------------------------------------------------------------------
def _hash_pin(pin: str, salt: str) -> str:
    return hashlib.sha256((salt + pin).encode()).hexdigest()


def settings_page():
    page_header("Settings", "Modules, categories, security and backups.", icon="settings")
    settings = load_app_settings()

    # --- currency ---
    with card_box().classes("w-full max-w-lg"):
        section_header("Currency", icon="payments", icon_color=EMERALD,
                       subtitle="Display symbol used across the app. Amounts are not converted.")
        currency_select = ui.select(CURRENCY_OPTIONS, value=settings.currency or "£", label="Currency symbol").classes("w-40")

        def save_currency():
            with Session(engine) as session:
                s = session.exec(select(AppSettings)).first()
                s.currency = currency_select.value
                session.add(s)
                session.commit()
            load_app_settings()
            ui.notify(f"Currency set to {currency_select.value}.", type="positive")

        currency_select.on_value_change(lambda e: save_currency())

    # --- theme ---
    with card_box().classes("w-full max-w-lg"):
        section_header("Theme", icon="palette", icon_color=VIOLET,
                       subtitle="Pick the app's look. Applies everywhere, instantly.")

        def set_theme(name):
            with Session(engine) as session:
                s = session.exec(select(AppSettings)).first()
                s.theme = name
                session.add(s)
                session.commit()
            ui.run_javascript("location.reload()")

        with ui.row().classes("w-full gap-3 flex-wrap"):
            for key, theme in THEMES.items():
                active = key == ACTIVE_THEME
                # color=None stops NiceGUI from adding Quasar's bg-primary/text-white
                # classes (they carry !important and would override the per-theme
                # background below, making every swatch render in the primary blue).
                with ui.button(on_click=lambda _, k=key: set_theme(k), color=None).props("unelevated no-caps").classes(
                    "normal-case p-0 rounded-xl overflow-hidden"
                ).style(
                    f"background:{theme['BG']}; border:2px solid {theme['INDIGO'] if active else theme['BORDER']}; width:9.5rem;"
                ):
                    with ui.column().classes("items-start gap-1 p-3 w-full"):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            # mini swatch: surface chip + two accent dots in the theme's own colors
                            ui.element("div").classes("rounded-md").style(
                                f"width:1.1rem;height:1.1rem;background:{theme['SURFACE']};border:1px solid {theme['BORDER']};")
                            ui.element("div").classes("rounded-full").style(
                                f"width:0.65rem;height:0.65rem;background:{theme['INDIGO']};")
                            ui.element("div").classes("rounded-full").style(
                                f"width:0.65rem;height:0.65rem;background:{theme['EMERALD']};")
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.label(theme["label"]).classes("text-sm font-semibold").style(f"color:{theme['TEXT']}")
                            if active:
                                ui.icon("check_circle").classes("text-sm").style(f"color:{theme['INDIGO']}")

    # --- modules (optional feature areas) ---
    with card_box().classes("w-full max-w-lg"):
        section_header("Modules", icon="widgets", icon_color=INDIGO,
                       subtitle="Turn optional areas on or off. Core areas (dashboard, transactions, food log) always stay. Changes apply on the next page load.")
        _enabled = load_enabled_modules()

        def toggle_module(key, value):
            set_module_enabled(key, value)
            ui.notify(f"{MODULES[key][0]} {'shown' if value else 'hidden'} — reload to update the menu.", type="info")

        for tier_key, tier_label in MODULE_TIERS:
            tier_modules = [(k, m) for k, m in MODULES.items() if m[1] == tier_key]
            if not tier_modules:
                continue
            ui.label(tier_label).classes("text-xs font-semibold uppercase mt-3 mb-1").style(f"color:{TEXT_DIM}")
            for key, meta in tier_modules:
                ui.switch(meta[0], value=_enabled.get(key, meta[2])).props("dense color=primary").on_value_change(
                    lambda e, k=key: toggle_module(k, e.value)
                )

        def apply_preset(value):
            set_all_modules(value)
            ui.run_javascript("location.reload()")

        with ui.row().classes("gap-2 mt-3 flex-wrap"):
            ui.button("Enable all", icon="done_all",
                      on_click=lambda: apply_preset(True)).props("flat dense no-caps color=primary")
            ui.button("Lean defaults", icon="filter_list_off",
                      on_click=lambda: apply_preset(False)).props("flat dense no-caps color=primary")
            ui.button("Reload to apply", icon="refresh",
                      on_click=lambda: ui.run_javascript("location.reload()")).props("flat dense no-caps")

    # --- categories ---
    with card_box().classes("w-full max-w-2xl"):
        section_header("Categories", icon="category", icon_color=VIOLET,
                       subtitle="Rename, add, or remove spending categories.")
        # Collapsed by default -- the full 32-row editor is a wall most people
        # never touch; keep it one tap away instead of always on screen.
        with ui.expansion("Manage categories", icon="tune").props("dense").classes("w-full mt-1"):
            cat_container = ui.column().classes("w-full gap-1")

        def category_usage(session, cat_id):
            n = len(session.exec(select(Transaction).where(Transaction.category_id == cat_id)).all())
            n += len(session.exec(select(Subscription).where(Subscription.category_id == cat_id)).all())
            n += len(session.exec(select(BudgetTarget).where(BudgetTarget.category_id == cat_id)).all())
            return n

        def rename_category(cat_id, new_name):
            name = (new_name or "").strip()
            if not name:
                return
            with Session(engine) as session:
                c = session.get(Category, cat_id)
                if c and c.name != name:
                    c.name = name
                    session.add(c)
                    session.commit()
                    ui.notify(f"Renamed to {name}.", type="positive")

        def delete_category(cat_id):
            with Session(engine) as session:
                children = session.exec(select(Category).where(Category.parent_id == cat_id)).all()
                if children:
                    ui.notify("Remove its sub-categories first.", type="warning")
                    return
                used = category_usage(session, cat_id)
                c = session.get(Category, cat_id)
                if used:
                    # detach references rather than orphan them silently
                    for t in session.exec(select(Transaction).where(Transaction.category_id == cat_id)).all():
                        t.category_id = None
                        session.add(t)
                    for sub in session.exec(select(Subscription).where(Subscription.category_id == cat_id)).all():
                        sub.category_id = None
                        session.add(sub)
                    for b in session.exec(select(BudgetTarget).where(BudgetTarget.category_id == cat_id)).all():
                        session.delete(b)
                session.delete(c)
                session.commit()
            ui.notify("Category deleted." + (f" {used} item(s) set to Uncategorized." if used else ""), type="positive")
            render_categories()

        def render_categories():
            cat_container.clear()
            with Session(engine) as session:
                cats = session.exec(select(Category)).all()
                usage = {c.id: category_usage(session, c.id) for c in cats}
            parents = [c for c in cats if c.parent_id is None]
            children = {}
            for c in cats:
                if c.parent_id is not None:
                    children.setdefault(c.parent_id, []).append(c)

            with cat_container:
                for parent in sorted(parents, key=lambda c: c.name.lower()):
                    with ui.column().classes(LIST_GROUP + " mb-2"):
                        rows = [parent] + sorted(children.get(parent.id, []), key=lambda c: c.name.lower())
                        for idx, c in enumerate(rows):
                            if idx:
                                ui.element("div").classes("h-px w-full").style(f"background:{BORDER}")
                            is_parent = c.parent_id is None
                            with ui.row().classes("w-full items-center gap-2 px-3 py-1.5 no-wrap"):
                                ui.icon("folder" if is_parent else "label").classes("text-base shrink-0").style(
                                    f"color:{VIOLET if is_parent else TEXT_DIM}")
                                name_input = ui.input(value=c.name).props("dense borderless").classes(
                                    "flex-1 min-w-0" + ("" if is_parent else " pl-2"))
                                name_input.on("blur", lambda e, cid=c.id, inp=name_input: rename_category(cid, inp.value))
                                if usage.get(c.id):
                                    badge(f"{usage[c.id]} in use", TEXT_DIM)
                                ui.button(icon="delete", on_click=lambda _, cid=c.id: delete_category(cid)).props(
                                    "flat round dense color=red size=sm")

                with ui.row().classes("w-full items-end gap-2 mt-2"):
                    with Session(engine) as session:
                        parent_opts = {None: "(top level)"}
                        parent_opts.update({c.id: c.name for c in session.exec(
                            select(Category).where(Category.parent_id == None)).all()})  # noqa: E711
                    new_name = ui.input(label="New category").props("dense").classes("flex-grow")
                    new_parent = ui.select(parent_opts, value=None, label="Parent").props("dense options-dense").classes("w-44")

                    def add_category():
                        name = (new_name.value or "").strip()
                        if not name:
                            return
                        with Session(engine) as session:
                            session.add(Category(name=name, parent_id=new_parent.value))
                            session.commit()
                        ui.notify(f"Added {name}.", type="positive")
                        render_categories()

                    ui.button("Add", icon="add", on_click=add_category).props("flat dense no-caps")

        render_categories()

    # --- PIN lock ---
    with card_box().classes("w-full max-w-lg"):
        section_header("PIN lock", icon="lock", icon_color=AMBER,
                       subtitle="Ask for a PIN when the app opens in a new browser session. "
                                "Note: the JSON API under /api is not PIN-protected -- your Tailscale "
                                "network remains the real security boundary.")
        has_pin = bool(settings.pin_hash)
        badge("PIN is set" if has_pin else "No PIN set", EMERALD if has_pin else TEXT_DIM)
        pin_input = ui.input(label="New PIN (4-8 digits)", password=True, password_toggle_button=True).props(
            'dense inputmode="numeric"').classes("w-56")

        def set_pin():
            pin = (pin_input.value or "").strip()
            if not (pin.isdigit() and 4 <= len(pin) <= 8):
                ui.notify("PIN must be 4-8 digits.", type="warning")
                return
            salt = secrets.token_hex(8)
            with Session(engine) as session:
                s = session.exec(select(AppSettings)).first()
                s.pin_salt = salt
                s.pin_hash = _hash_pin(pin, salt)
                session.add(s)
                session.commit()
            app.storage.user["unlocked"] = True  # don't lock out the person who just set it
            ui.notify("PIN set.", type="positive")
            ui.run_javascript("location.reload()")

        def clear_pin():
            with Session(engine) as session:
                s = session.exec(select(AppSettings)).first()
                s.pin_hash = None
                s.pin_salt = None
                session.add(s)
                session.commit()
            ui.notify("PIN removed.", type="positive")
            ui.run_javascript("location.reload()")

        with ui.row().classes("gap-2"):
            ui.button("Set PIN", icon="lock", on_click=set_pin).props("outline no-caps color=primary")
            if has_pin:
                ui.button("Remove PIN", icon="lock_open", on_click=clear_pin).props("flat no-caps color=red")


def render_lock_screen(settings):
    """Full-page PIN gate shown instead of the app shell until unlocked."""
    inject_theme()
    with ui.column().classes("w-full h-screen items-center justify-center gap-4"):
        icon_chip("lock", INDIGO, size="text-2xl")
        ui.label("Balance is locked").classes("text-xl font-bold")
        pin_entry = ui.input(label="PIN", password=True).props(
            'dense inputmode="numeric" autofocus').classes("w-48")
        status = ui.label().classes("text-xs").style(f"color:{RED}")

        def try_unlock():
            pin = (pin_entry.value or "").strip()
            if settings.pin_hash and _hash_pin(pin, settings.pin_salt or "") == settings.pin_hash:
                app.storage.user["unlocked"] = True
                ui.run_javascript("location.reload()")
            else:
                status.set_text("Wrong PIN.")
                pin_entry.set_value("")

        pin_entry.on("keydown.enter", lambda e: try_unlock())
        ui.button("Unlock", icon="lock_open", on_click=try_unlock).props("color=primary unelevated no-caps")


# ---------------------------------------------------------------------------
# Single entry point: header/drawer render once, ui.sub_pages swaps the
# content panel client-side (history.pushState) instead of a full browser
# reload on every nav click.
# ---------------------------------------------------------------------------
def scheduled_page():
    from backend.recurring import post_now, skip_next
    from backend.cashflow import cashflow_summary

    page_header("Scheduled", "Recurring transactions and upcoming cashflow.", icon="event_repeat")

    @ui.refreshable
    def content():
        today = date.today()
        with Session(engine) as session:
            items = session.exec(select(ScheduledTransaction)).all()
            categories = session.exec(select(Category)).all()
            month_start = today.replace(day=1)
            spent_mtd = sum(t.amount for t in session.exec(
                select(Transaction).where(Transaction.date >= month_start, Transaction.date <= today)).all())
            earned_mtd = sum(i.amount for i in session.exec(
                select(Income).where(Income.date >= month_start, Income.date <= today)).all())
        net_so_far = earned_mtd - spent_mtd
        category_options = {c.id: _category_label(c, categories) for c in categories}
        cats_by_id = {c.id: c for c in categories}
        active_items = [i for i in items if i.active]

        def monthly_norm(i):
            if i.cadence == "weekly":
                return i.amount * 52 / 12
            if i.cadence == "yearly":
                return i.amount / 12
            return i.amount
        monthly_out = sum(monthly_norm(i) for i in active_items if i.kind == "expense")
        monthly_in = sum(monthly_norm(i) for i in active_items if i.kind == "income")

        summary_strip([
            ("Scheduled items", str(len(active_items)), INDIGO),
            ("Recurring out / mo", f"{CUR}{monthly_out:,.0f}", RED),
            ("Recurring in / mo", f"{CUR}{monthly_in:,.0f}", EMERALD) if monthly_in else None,
        ])

        # --- forward cashflow: what's due in the next 30 days ---
        cf = cashflow_summary(days=30, today=today)
        with card_box().classes("w-full"):
            with section_header("Upcoming (next 30 days)", icon="date_range", icon_color=SKY,
                                subtitle="Known bills and income from your subscriptions and scheduled items."):
                ui.label(f"{'+' if cf['net'] >= 0 else '-'}{CUR}{abs(cf['net']):,.2f}").classes(
                    "text-lg font-bold").style(f"color:{EMERALD if cf['net'] >= 0 else RED}")
            with ui.row().classes("w-full gap-4 flex-wrap"):
                ui.label(f"Out {CUR}{cf['out']:,.2f}").classes("text-xs").style(f"color:{RED}")
                ui.label(f"In {CUR}{cf['in']:,.2f}").classes("text-xs").style(f"color:{EMERALD}")
            if cf["out"] > 0:
                after = net_so_far + cf["in"] - cf["out"]
                ui.label(
                    f"Net so far this month is {CUR}{net_so_far:,.2f}; after the {CUR}{cf['out']:,.2f} of upcoming bills "
                    f"(and {CUR}{cf['in']:,.2f} income) that leaves {CUR}{after:,.2f}."
                ).classes("text-xs").style(f"color:{TEXT_DIM if after >= 0 else AMBER}")
            if not cf["events"]:
                ui.label("Nothing scheduled in the next 30 days.").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")
            for e in cf["events"][:30]:
                sign = "+" if e["direction"] == "in" else "-"
                color = EMERALD if e["direction"] == "in" else RED
                with ui.row().classes("w-full items-center justify-between gap-2 py-0.5 no-wrap"):
                    with ui.row().classes("flex-1 items-center gap-2 min-w-0 no-wrap"):
                        ui.label(e["date"].strftime("%a %d %b")).classes("text-xs w-20 shrink-0").style(f"color:{TEXT_DIM}")
                        ui.label(e["label"]).classes("text-sm min-w-0 truncate").style(f"color:{TEXT}")
                        with ui.element("div").classes("shrink-0"):
                            badge(e["source"], TEXT_DIM)
                    ui.label(f"{sign}{CUR}{e['amount']:,.2f}").classes("text-sm shrink-0 whitespace-nowrap").style(f"color:{color}")

        def _post_now(iid):
            post_now(iid)
            ui.notify("Posted.", type="positive")
            content.refresh()

        def _skip(iid):
            skip_next(iid)
            ui.notify("Skipped to next date.", type="info")
            content.refresh()

        def _toggle_active(iid, val):
            with Session(engine) as session:
                row = session.get(ScheduledTransaction, iid)
                if row:
                    row.active = val
                    session.add(row); session.commit()
            content.refresh()

        def _delete(iid):
            with Session(engine) as session:
                row = session.get(ScheduledTransaction, iid)
                if row:
                    session.delete(row); session.commit()
            ui.notify("Deleted.", type="info")
            content.refresh()

        due = sorted([i for i in active_items if not i.auto_post and i.next_date and i.next_date <= today],
                     key=lambda i: i.next_date)
        if due:
            with card_box().classes("w-full"):
                section_header("Due now", icon="notification_important", icon_color=AMBER, accent=AMBER,
                               subtitle="Confirm to record them, or skip to move to the next date.")
                for i in due:
                    lbl = i.description or ("Income" if i.kind == "income" else "Expense")
                    sign = "+" if i.kind == "income" else "-"
                    with card_box().classes("w-full py-3 flex-row items-center justify-between gap-3").style(f"background:{SURFACE_2}"):
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(f"{lbl} · {sign}{CUR}{i.amount:,.2f}").classes("font-semibold")
                            ui.label(f"Due {format_date_header(i.next_date).lower()} · {i.cadence}").classes("text-xs").style(f"color:{TEXT_DIM}")
                        with ui.row().classes("items-center gap-2 shrink-0"):
                            ui.button("Post now", icon="check", on_click=lambda _, iid=i.id: _post_now(iid)).props("flat dense no-caps color=primary")
                            ui.button("Skip", icon="skip_next", on_click=lambda _, iid=i.id: _skip(iid)).props("flat dense no-caps").style(f"color:{TEXT_DIM}")

        with ui.expansion("Add scheduled item", icon="add").classes("w-full"):
            with ui.column().classes("gap-1 max-w-xl w-full"):
                kind_toggle = segmented("Type", {"expense": "Expense", "income": "Income"}, "expense")
                ui.label("Amount").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")
                amount_input = ui.number(placeholder="0.00", format="%.2f").props(
                    f'prefix="{CUR}" input-class="text-2xl font-bold"').classes("w-full")
                desc_input = ui.input(label="Description (merchant / payer)").props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1 mt-2"):
                    cadence_select = segmented("Repeats", {"weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly"}, "monthly")
                    next_date_input = date_field("Next date", value=today.isoformat())
                category_select = ui.select(category_options, label="Category", with_input=True).props("dense options-dense").classes("w-full")
                source_select = ui.select(INCOME_SOURCES, value="Other", label="Income source").props("dense options-dense").classes("w-full")
                source_select.set_visibility(False)

                def _sync_kind(e):
                    is_income = e.value == "income"
                    category_select.set_visibility(not is_income)
                    source_select.set_visibility(is_income)
                kind_toggle.on_value_change(_sync_kind)

                auto_switch = ui.switch("Post automatically on the due date", value=True).props("dense color=primary").classes("mt-2")
                ui.label("Off = it waits here for you to confirm each time (good for variable amounts).").classes(
                    "text-xs -mt-1").style(f"color:{TEXT_DIM}")

                def add_item():
                    if not amount_input.value:
                        ui.notify("Enter an amount.", type="warning"); return
                    if not next_date_input.value:
                        ui.notify("Pick a next date.", type="warning"); return
                    is_income = kind_toggle.value == "income"
                    with Session(engine) as session:
                        session.add(ScheduledTransaction(
                            kind=kind_toggle.value,
                            amount=amount_input.value or 0,
                            description=desc_input.value or None,
                            category_id=None if is_income else category_select.value,
                            source=source_select.value if is_income else None,
                            cadence=cadence_select.value,
                            next_date=date.fromisoformat(next_date_input.value),
                            auto_post=auto_switch.value,
                        ))
                        session.commit()
                    ui.notify("Scheduled.", type="positive")
                    content.refresh()

                ui.button("Add scheduled item", on_click=add_item).props("color=primary unelevated")

        if not items:
            with card_box().classes("w-full"):
                empty_state("Nothing scheduled yet -- add a recurring bill, subscription charge, or your salary above.", "event_repeat")

        for i in sorted(items, key=lambda x: (not x.active, x.next_date or date.max)):
            is_income = i.kind == "income"
            color = EMERALD if is_income else RED
            icon = "trending_up" if is_income else "trending_down"
            lbl = i.description or ("Income" if is_income else "Expense")
            with card_box().classes("w-full py-3 flex-row items-center justify-between gap-2 no-wrap"):
                with ui.row().classes("flex-1 items-center gap-3 min-w-0 no-wrap"):
                    ui.icon(icon).classes("text-2xl shrink-0").style(f"color:{color if i.active else TEXT_DIM}")
                    with ui.column().classes("gap-0 min-w-0"):
                        with ui.row().classes("items-center gap-2 min-w-0 no-wrap w-full"):
                            ui.label(lbl).classes("font-semibold truncate" + ("" if i.active else " line-through")).style(
                                f"color:{TEXT if i.active else TEXT_DIM}")
                            badge("Auto" if i.auto_post else "Confirm", INDIGO if i.auto_post else AMBER)
                            if not i.active:
                                badge("Paused", TEXT_DIM)
                        sub = f"{'+' if is_income else '-'}{CUR}{i.amount:,.2f} · {i.cadence}"
                        if is_income and i.source:
                            sub += f" · {i.source}"
                        elif not is_income and i.category_id in cats_by_id:
                            sub += f" · {_category_label(cats_by_id[i.category_id], categories)}"
                        ui.label(sub).classes("text-xs truncate w-full").style(f"color:{TEXT_DIM}")
                        if i.next_date:
                            ui.label(f"Next: {format_date_header(i.next_date).lower()}").classes("text-xs truncate w-full").style(f"color:{TEXT_DIM}")
                with ui.row().classes("items-center gap-2 shrink-0 no-wrap"):
                    ui.switch(value=i.active, on_change=lambda e, iid=i.id: _toggle_active(iid, e.value)).props(
                        "color=primary dense").tooltip("Active / Paused")
                    ui.button(icon="delete", on_click=lambda _, iid=i.id: _delete(iid)).props("flat round dense color=red")

    content()


def recipes_page():
    from backend.recipes import log_recipe, recipe_totals, mark_recipe_ingredients_used

    page_header("Recipes", "Meals from your pantry, costed per serving.", icon="menu_book")

    @ui.refreshable
    def content():
        with Session(engine) as session:
            recipes = session.exec(select(Recipe)).all()
            all_items = session.exec(select(RecipeItem)).all()
        items_by_recipe = {}
        for it in all_items:
            items_by_recipe.setdefault(it.recipe_id, []).append(it)

        summary_strip([
            ("Saved recipes", str(len(recipes)), VIOLET),
            ("Ingredients", str(len(all_items)), SKY) if all_items else None,
        ])

        def _del_recipe(rid):
            with Session(engine) as session:
                for it in session.exec(select(RecipeItem).where(RecipeItem.recipe_id == rid)).all():
                    session.delete(it)
                r = session.get(Recipe, rid)
                if r:
                    session.delete(r)
                session.commit()
            ui.notify("Recipe deleted.", type="info")
            content.refresh()

        def _del_item(iid):
            with Session(engine) as session:
                it = session.get(RecipeItem, iid)
                if it:
                    session.delete(it)
                session.commit()
            content.refresh()

        with ui.expansion("New recipe", icon="add").classes("w-full"):
            with ui.column().classes("gap-1 max-w-xl w-full"):
                r_name = ui.input(label="Recipe name (e.g. Spaghetti Bolognese)").props("dense").classes("w-full")
                r_serv = ui.number(label="Servings it makes", value=1, format="%g").props("dense").classes("w-40")

                def add_recipe():
                    if not r_name.value:
                        ui.notify("Give the recipe a name.", type="warning"); return
                    with Session(engine) as session:
                        session.add(Recipe(name=r_name.value, servings=r_serv.value or 1))
                        session.commit()
                    ui.notify("Recipe created -- add ingredients below.", type="positive")
                    content.refresh()
                ui.button("Create recipe", on_click=add_recipe).props("color=primary unelevated")

        if not recipes:
            with card_box().classes("w-full"):
                empty_state("No recipes yet -- create one above, then add ingredients to log the whole meal in one tap.", "menu_book")

        for r in recipes:
            items = items_by_recipe.get(r.id, [])
            totals, grams = recipe_totals(items)
            servings = r.servings or 1
            with card_box().classes("w-full"):
                with section_header(r.name, icon="menu_book", icon_color=VIOLET,
                                    subtitle=f"Makes {servings:g} serving(s) · {len(items)} ingredient(s)"):
                    ui.button(icon="delete", on_click=lambda _, rid=r.id: _del_recipe(rid)).props("flat round dense color=red")
                ui.label(
                    f"Per serving: {totals['calories'] / servings:,.0f} kcal · "
                    f"P {totals['protein_g'] / servings:,.0f}g · C {totals['carbs_g'] / servings:,.0f}g · "
                    f"F {totals['fat_g'] / servings:,.0f}g"
                ).classes("text-xs").style(f"color:{TEXT_DIM}")

                for it in items:
                    with ui.row().classes("w-full items-center justify-between gap-2 py-1"):
                        ui.label(f"{it.food_name} · {it.quantity_g:g}g · {it.calories or 0:,.0f} kcal").classes(
                            "text-sm min-w-0").style(f"color:{TEXT}")
                        ui.button(icon="close", on_click=lambda _, iid=it.id: _del_item(iid)).props("flat round dense").style(f"color:{TEXT_DIM}")

                with ui.expansion("Add ingredient", icon="add").classes("w-full"):
                    with ui.column().classes("gap-1 w-full"):
                        with ui.row().classes("w-full items-end gap-2 no-wrap"):
                            bc = ui.input(label="Barcode (optional)").props("dense").classes("flex-grow")
                            i_name = ui.input(label="Ingredient").props("dense").classes("flex-grow")
                            i_qty = ui.number(label="Grams", value=100, format="%g").props("dense").classes("w-24")
                        with ui.grid().classes("w-full grid-cols-2 sm:grid-cols-4 gap-2"):
                            i_cal = ui.number(label="Calories").props("dense")
                            i_p = ui.number(label="Protein (g)").props("dense")
                            i_c = ui.number(label="Carbs (g)").props("dense")
                            i_f = ui.number(label="Fat (g)").props("dense")
                        extra = {"fiber_g": None, "sugar_g": None, "sodium_mg": None,
                                 "saturated_fat_g": None, "trans_fat_g": None, "caffeine_mg": None}
                        lookup_note = ui.label().classes("text-xs").style(f"color:{TEXT_DIM}")

                        def do_lookup(_=None, bc=bc, i_name=i_name, i_qty=i_qty, i_cal=i_cal,
                                      i_p=i_p, i_c=i_c, i_f=i_f, extra=extra, note=lookup_note):
                            if not bc.value:
                                return
                            with Session(engine) as session:
                                item = lookup_barcode(session, bc.value)
                            if not item or item.calories_per_100g is None:
                                note.set_text("Not found in Open Food Facts"); return
                            f = (i_qty.value or 100) / 100.0
                            i_name.value = item.name or i_name.value
                            i_cal.value = round((item.calories_per_100g or 0) * f, 1)
                            i_p.value = round((item.protein_per_100g or 0) * f, 1)
                            i_c.value = round((item.carbs_per_100g or 0) * f, 1)
                            i_f.value = round((item.fat_per_100g or 0) * f, 1)
                            extra["fiber_g"] = round((item.fiber_per_100g or 0) * f, 1)
                            extra["sugar_g"] = round((item.sugar_per_100g or 0) * f, 1)
                            extra["sodium_mg"] = round((item.sodium_per_100g or 0) * f, 1)
                            extra["saturated_fat_g"] = round((item.saturated_fat_per_100g or 0) * f, 1)
                            extra["trans_fat_g"] = round((item.trans_fat_per_100g or 0) * f, 1)
                            extra["caffeine_mg"] = round((item.caffeine_per_100g or 0) * f, 1)
                            note.set_text(f"Found: {item.name}")

                        with bc.add_slot("append"):
                            ui.icon("search").classes("cursor-pointer text-sm").style(f"color:{TEXT_DIM}").on("click", do_lookup)

                        def add_ingredient(_=None, rid=r.id, bc=bc, i_name=i_name, i_qty=i_qty,
                                           i_cal=i_cal, i_p=i_p, i_c=i_c, i_f=i_f, extra=extra):
                            if not i_name.value:
                                ui.notify("Name the ingredient.", type="warning"); return
                            with Session(engine) as session:
                                session.add(RecipeItem(
                                    recipe_id=rid, food_name=i_name.value, quantity_g=i_qty.value or 0,
                                    barcode=bc.value or None, calories=i_cal.value, protein_g=i_p.value,
                                    carbs_g=i_c.value, fat_g=i_f.value, **extra,
                                ))
                                session.commit()
                            ui.notify("Ingredient added.", type="positive")
                            content.refresh()
                        ui.button("Add ingredient", icon="add", on_click=add_ingredient).props("flat dense no-caps color=primary")

                if items:
                    with ui.row().classes("w-full items-end gap-2 mt-2 flex-wrap"):
                        eat_qty = ui.number(label="Servings eaten", value=1, format="%g").props("dense").classes("w-32")
                        meal_sel = ui.select({"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"},
                                             value="dinner", label="Meal").props("dense options-dense").classes("w-36")
                        use_pantry = ui.checkbox("Use from pantry").props("dense").tooltip(
                            "Also mark matching active pantry items as consumed")

                        def log_it(_=None, rid=r.id, eat_qty=eat_qty, meal_sel=meal_sel, use_pantry=use_pantry):
                            log_recipe(rid, servings_eaten=eat_qty.value or 1, meal_type=meal_sel.value)
                            msg = "Logged to your food diary."
                            if use_pantry.value:
                                n = mark_recipe_ingredients_used(rid)
                                msg += f" {n} pantry item(s) marked used." if n else " No matching pantry items."
                            ui.notify(msg, type="positive")
                        ui.button("Log to diary", icon="restaurant", on_click=log_it).props("unelevated no-caps color=primary")

    content()


def shopping_page():
    page_header("Shopping List", "What to buy, linked to pantry and spend.", icon="shopping_cart")

    @ui.refreshable
    def content():
        today = date.today()
        with Session(engine) as session:
            items = session.exec(select(ShoppingListItem)).all()
            pantry = session.exec(select(PantryItem)).all()
            prices = session.exec(select(PriceObservation)).all()
            categories = session.exec(select(Category)).all()

        to_buy = [i for i in items if not i.done]
        existing_names = {(i.name or "").strip().lower() for i in items}
        active_pantry_names = {(p.name or "").strip().lower() for p in pantry if p.status == "active"}
        category_options = {c.id: _category_label(c, categories) for c in categories}
        default_grocery_cat = next((c.id for c in categories if c.name == "Groceries"), None)

        summary_strip([
            ("To buy", str(len(to_buy)), INDIGO),
            ("Completed", str(len(items) - len(to_buy)), EMERALD) if items else None,
        ])

        def _toggle(iid, val):
            # No refresh: lets you tick several items before "Add to pantry".
            with Session(engine) as session:
                it = session.get(ShoppingListItem, iid)
                if it:
                    it.done = val
                    session.add(it); session.commit()

        def _del(iid):
            with Session(engine) as session:
                it = session.get(ShoppingListItem, iid)
                if it:
                    session.delete(it)
                session.commit()
            content.refresh()

        def _add_suggestion(name, location="pantry", source="pantry"):
            with Session(engine) as session:
                session.add(ShoppingListItem(name=name, location=location, source=source))
                session.commit()
            ui.notify(f"Added {name}.", type="positive")
            content.refresh()

        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            add_name = ui.input(label="Add an item").props("dense").classes("flex-grow")
            add_qty = ui.input(label="Qty (optional)").props("dense").classes("w-28")
            loc_sel = ui.select({"fridge": "Fridge", "freezer": "Freezer", "pantry": "Pantry"},
                                value="pantry", label="Goes to").props("dense options-dense").classes("w-32")

            def add_item():
                if not add_name.value:
                    return
                with Session(engine) as session:
                    session.add(ShoppingListItem(name=add_name.value, quantity_note=add_qty.value or None,
                                                 location=loc_sel.value, source="manual"))
                    session.commit()
                content.refresh()
            ui.button("Add", icon="add", on_click=add_item).props("unelevated no-caps color=primary")

        with card_box().classes("w-full"):
            section_header("Items", icon="shopping_cart", icon_color=INDIGO, count=len(to_buy))
            if not items:
                empty_state("Your list is empty -- add items above, or pull from Suggestions below.", "shopping_cart")
            for i in sorted(items, key=lambda x: (x.done, (x.name or "").lower())):
                with ui.row().classes("w-full items-center gap-2 py-1"):
                    ui.checkbox(value=i.done, on_change=lambda e, iid=i.id: _toggle(iid, e.value)).props("dense")
                    lbl = i.name + (f" · {i.quantity_note}" if i.quantity_note else "")
                    ui.label(lbl).classes("text-sm flex-grow min-w-0").style(
                        f"color:{TEXT_DIM if i.done else TEXT}" + ("; text-decoration:line-through" if i.done else ""))
                    if i.source != "manual":
                        badge(i.source, TEXT_DIM)
                    ui.button(icon="close", on_click=lambda _, iid=i.id: _del(iid)).props("flat round dense").style(f"color:{TEXT_DIM}")

        if items:
            with card_box().classes("w-full"):
                section_header("Bought the checked items?", icon="check_circle", icon_color=EMERALD, accent=EMERALD,
                               subtitle="Move them into your pantry, and optionally record the grocery spend in one go.")
                with ui.row().classes("w-full items-end gap-2 flex-wrap"):
                    spend_input = ui.number(label="Total spent (optional)", format="%.2f").props(f'prefix="{CUR}"').classes("w-40")
                    spend_cat = ui.select(category_options, value=default_grocery_cat, label="Category").props("dense options-dense").classes("w-48")

                def buy_checked():
                    moved = 0
                    with Session(engine) as session:
                        rows = session.exec(select(ShoppingListItem).where(ShoppingListItem.done == True)).all()  # noqa: E712
                        for it in rows:
                            session.add(PantryItem(name=it.name, location=it.location or "pantry",
                                                   quantity=1, unit="unit", status="active", purchase_date=today))
                            session.delete(it)
                            moved += 1
                        if spend_input.value:
                            session.add(Transaction(date=today, amount=spend_input.value, merchant="Groceries",
                                                    category_id=spend_cat.value, notes="From shopping list"))
                        session.commit()
                    if not moved:
                        ui.notify("Check some items first.", type="warning"); return
                    ui.notify(f"Moved {moved} item(s) to pantry" + (" and logged the spend." if spend_input.value else "."),
                              type="positive")
                    content.refresh()

                def clear_checked():
                    with Session(engine) as session:
                        for it in session.exec(select(ShoppingListItem).where(ShoppingListItem.done == True)).all():  # noqa: E712
                            session.delete(it)
                        session.commit()
                    content.refresh()

                with ui.row().classes("gap-2"):
                    ui.button("Add to pantry", icon="kitchen", on_click=buy_checked).props("unelevated no-caps color=primary")
                    ui.button("Just clear checked", icon="clear_all", on_click=clear_checked).props("flat no-caps").style(f"color:{TEXT_DIM}")

        # --- suggestions from pantry + tracked prices ---
        suggestions = []
        seen = set(existing_names)
        for p in pantry:
            if p.status == "active" and p.expiration_date:
                days = (p.expiration_date - today).days
                nm = (p.name or "").strip()
                if days <= 7 and nm and nm.lower() not in seen:
                    seen.add(nm.lower())
                    reason = "expired -- restock" if days < 0 else (f"expires in {days}d -- restock")
                    suggestions.append((nm, p.location or "pantry", "pantry", reason))
        seen |= active_pantry_names
        for p in pantry:
            nm = (p.name or "").strip()
            if p.status in ("consumed", "thrown_away", "expired") and nm and nm.lower() not in seen:
                seen.add(nm.lower())
                suggestions.append((nm, p.location or "pantry", "pantry", f"{p.status.replace('_', ' ')} -- rebuy?"))
        for pr in prices:
            nm = (pr.item_name or "").strip()
            if nm and nm.lower() not in seen:
                seen.add(nm.lower())
                suggestions.append((nm, "pantry", "recurring", "you buy this repeatedly"))

        if suggestions:
            with card_box().classes("w-full"):
                section_header("Suggestions", icon="lightbulb", icon_color=AMBER,
                               subtitle="From pantry stock that's low, used up or expiring -- and things you buy repeatedly.")
                for nm, loc, src, reason in suggestions[:20]:
                    with ui.row().classes("w-full items-center gap-2 py-1"):
                        with ui.column().classes("gap-0 flex-grow min-w-0"):
                            ui.label(nm).classes("text-sm").style(f"color:{TEXT}")
                            ui.label(reason).classes("text-xs").style(f"color:{TEXT_DIM}")
                        ui.button("Add", icon="add", on_click=lambda _, n=nm, l=loc, s=src: _add_suggestion(n, l, s)).props(
                            "flat dense no-caps color=primary")

    content()


def savings_page():
    page_header("Savings Goals", "Targets, pace, and what it takes to hit them.", icon="savings")
    @ui.refreshable
    def content():
        today = date.today()
        with Session(engine) as session:
            goals = session.exec(select(SavingsGoal)).all()
            _since = today - timedelta(days=90)
            _recent = session.exec(select(Transaction).where(Transaction.date >= _since)).all()
            _cat_name = {c.id: c.name for c in session.exec(select(Category)).all()}
        # Average monthly "flexible" spend over the last ~90 days -- the pool a
        # goal can be funded from without touching essentials.
        discretionary_monthly = sum(
            t.amount for t in _recent if _cat_name.get(t.category_id) in DISCRETIONARY_CATEGORIES
        ) / 3.0

        def _coach(per_month, remaining, disc):
            """Turn a required monthly saving into honest, non-preachy guidance
            tied to the person's actual flexible spending."""
            per_week = per_month / 4.345
            if disc <= 0:
                ui.label(f"That's ~{CUR}{per_week:,.0f}/week. Log a few weeks of spending and Balance "
                         "will show where it could come from.").classes("text-xs").style(f"color:{TEXT_DIM}")
            elif per_month <= disc:
                share = per_month / disc * 100
                ui.label(f"That's ~{CUR}{per_week:,.0f}/week — about {share:.0f}% of your ~{CUR}{disc:,.0f}/mo "
                         "of flexible spend (dining, coffee, subs). Redirect that and you're on track.").classes(
                    "text-xs").style(f"color:{EMERALD}")
            else:
                realistic = remaining / max(disc, 1)
                ui.label(f"Heads up: this needs {CUR}{per_month:,.0f}/mo, but you have only ~{CUR}{disc:,.0f}/mo "
                         f"of flexible spend. Even redirecting all of it that's ~{realistic:.0f} months — or "
                         "you'd have to trim essentials.").classes("text-xs").style(f"color:{AMBER}")

        total_saved = sum(g.saved_amount or 0 for g in goals)
        total_target = sum(g.target_amount or 0 for g in goals)

        summary_strip([
            ("Total saved", f"{CUR}{total_saved:,.0f}", EMERALD),
            ("Target", f"{CUR}{total_target:,.0f} · {len(goals)} goal{'s' if len(goals) != 1 else ''}", INDIGO),
            ("Overall progress", f"{min(total_saved / total_target * 100, 100):.0f}%", AMBER) if total_target else None,
        ])

        def _contribute(gid, amount):
            with Session(engine) as session:
                g = session.get(SavingsGoal, gid)
                if g:
                    g.saved_amount = (g.saved_amount or 0) + amount
                    session.add(g); session.commit()
            content.refresh()

        def _del(gid):
            with Session(engine) as session:
                g = session.get(SavingsGoal, gid)
                if g:
                    session.delete(g)
                session.commit()
            ui.notify("Goal deleted.", type="info")
            content.refresh()

        with ui.expansion("New goal", icon="add").classes("w-full"):
            with ui.column().classes("gap-1 max-w-xl w-full"):
                g_name = ui.input(label="Goal (e.g. Emergency fund)").props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-2"):
                    g_target = ui.number(label="Target amount", format="%.2f").props(f'prefix="{CUR}"').classes("w-full")
                    g_date = date_field("Target date (optional)")
                g_start = ui.number(label="Already saved (optional)", value=0, format="%.2f").props(f'prefix="{CUR}"').classes("w-full")

                def add_goal():
                    if not g_name.value or not g_target.value:
                        ui.notify("Give it a name and a target amount.", type="warning"); return
                    with Session(engine) as session:
                        session.add(SavingsGoal(
                            name=g_name.value, target_amount=g_target.value, saved_amount=g_start.value or 0,
                            target_date=date.fromisoformat(g_date.value) if g_date.value else None))
                        session.commit()
                    ui.notify("Goal created.", type="positive")
                    content.refresh()
                ui.button("Create goal", on_click=add_goal).props("color=primary unelevated")

        if not goals:
            with card_box().classes("w-full"):
                empty_state("No savings goals yet -- add one above to start a sinking fund.", "savings")

        for g in goals:
            saved = g.saved_amount or 0
            target = g.target_amount or 0
            pct = min(saved / target * 100, 100) if target else 0
            reached = bool(target) and saved >= target
            with card_box().classes("w-full"):
                with section_header(g.name, icon="savings", icon_color=EMERALD,
                                    subtitle=f"{CUR}{saved:,.2f} of {CUR}{target:,.2f}"):
                    if reached:
                        badge("Reached", EMERALD)
                    ui.button(icon="delete", on_click=lambda _, gid=g.id: _del(gid)).props("flat round dense color=red")
                with ui.element("div").classes("w-full rounded-full h-2 mt-1").style(f"background:{SURFACE_2}"):
                    ui.element("div").classes("rounded-full h-2").style(
                        f"background:{EMERALD if reached else INDIGO}; width:{pct}%")
                ui.label(f"{pct:.0f}%").classes("text-xs").style(f"color:{TEXT_DIM}")
                if g.target_date and not reached:
                    days_left = (g.target_date - today).days
                    remaining = target - saved
                    if days_left > 0:
                        per_month = remaining / max(days_left / 30.0, 0.1)
                        ui.label(f"Save {CUR}{per_month:,.2f}/month to reach it by "
                                 f"{g.target_date.strftime('%d %b %Y')} ({days_left} days left).").classes(
                            "text-xs").style(f"color:{TEXT_DIM}")
                        _coach(per_month, remaining, discretionary_monthly)
                    else:
                        ui.label(f"Target date passed -- {CUR}{remaining:,.2f} still to go.").classes(
                            "text-xs").style(f"color:{AMBER}")
                elif not reached and discretionary_monthly > 0:
                    remaining = target - saved
                    months = remaining / discretionary_monthly
                    ui.label(f"No target date. At ~{CUR}{discretionary_monthly:,.0f}/mo of flexible spend, "
                             f"redirecting it all would get you there in ~{months:.0f} months.").classes(
                        "text-xs").style(f"color:{TEXT_DIM}")
                if not reached:
                    with ui.row().classes("w-full items-end gap-2 mt-1"):
                        amt = ui.number(label="Add contribution", format="%.2f").props(f'prefix="{CUR}" dense').classes("w-40")

                        def contribute(_=None, gid=g.id, amt=amt):
                            if amt.value:
                                _contribute(gid, amt.value)
                        ui.button("Add", icon="add", on_click=contribute).props("unelevated no-caps color=primary")

    content()


def accounts_page():
    from backend.networth import snapshot_if_due, ASSET_TYPES, LIABILITY_TYPES, TYPE_LABELS

    page_header("Accounts & Net Worth", "Balances across accounts, tracked over time.", icon="account_balance")

    @ui.refreshable
    def content():
        today = date.today()
        with Session(engine) as session:
            if session.exec(select(Account)).first() is not None:
                snapshot_if_due(session, today)   # commits -> expires ORM objects
            # Materialise to plain tuples: the commit above expires the ORM
            # instances, so they must not be touched after the session closes.
            accounts = [(a.id, a.name, a.type, a.balance or 0)
                        for a in session.exec(select(Account)).all()]
            snaps = [(sn.date, sn.net_worth)
                     for sn in session.exec(select(NetWorthSnapshot).order_by(NetWorthSnapshot.date)).all()]

        assets = sum(bal for (_i, _n, typ, bal) in accounts if typ in ASSET_TYPES)
        liabilities = sum(bal for (_i, _n, typ, bal) in accounts if typ in LIABILITY_TYPES)
        net = assets - liabilities

        summary_strip([
            ("Net worth", f"{CUR}{net:,.0f}", EMERALD if net >= 0 else RED),
            ("Assets", f"{CUR}{assets:,.0f}", INDIGO),
            ("Liabilities", f"{CUR}{liabilities:,.0f}", RED) if liabilities else None,
            ("Accounts", str(len(accounts)), SKY) if accounts else None,
        ])

        def _save_balance(aid, val):
            with Session(engine) as session:
                a = session.get(Account, aid)
                if a:
                    a.balance = val or 0
                    session.add(a)
                    session.commit()
                    snapshot_if_due(session, today)
            ui.notify("Balance updated.", type="positive")
            content.refresh()

        def _del(aid):
            with Session(engine) as session:
                a = session.get(Account, aid)
                if a:
                    session.delete(a)
                session.commit()
            content.refresh()

        with ui.expansion("Add account", icon="add").classes("w-full"):
            with ui.column().classes("gap-1 max-w-xl w-full"):
                a_name = ui.input(label="Account name (e.g. Monzo Current)").props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-2"):
                    a_type = ui.select(TYPE_LABELS, value="current", label="Type").props("dense options-dense").classes("w-full")
                    a_bal = ui.number(label="Current balance", format="%.2f").props(f'prefix="{CUR}"').classes("w-full")
                ui.label("Credit card / loan balances count as liabilities (subtracted from net worth).").classes(
                    "text-xs").style(f"color:{TEXT_DIM}")

                def add_account():
                    if not a_name.value:
                        ui.notify("Name the account.", type="warning"); return
                    with Session(engine) as session:
                        session.add(Account(name=a_name.value, type=a_type.value, balance=a_bal.value or 0))
                        session.commit()
                        snapshot_if_due(session, today)
                    ui.notify("Account added.", type="positive")
                    content.refresh()
                ui.button("Add account", on_click=add_account).props("color=primary unelevated")

        if len(snaps) >= 2:
            with card_box().classes("w-full"):
                section_header("Net worth trend", icon="show_chart", icon_color=EMERALD,
                               subtitle="Snapshotted once a day as you update balances")
                ui.echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 60, "right": 15, "top": 15, "bottom": 28},
                    "xAxis": {"type": "category", "data": [dt.strftime("%d %b") for (dt, nw) in snaps],
                              "axisLine": {"lineStyle": {"color": BORDER}},
                              "axisLabel": {"color": TEXT_DIM, "fontSize": 10}},
                    "yAxis": {"type": "value", "axisLine": {"show": False},
                              "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                              "splitLine": {"lineStyle": {"color": BORDER}}},
                    "tooltip": {"trigger": "axis"},
                    "series": [{"type": "line", "smooth": True,
                                "data": [round(nw, 2) for (dt, nw) in snaps],
                                "itemStyle": {"color": EMERALD}, "lineStyle": {"color": EMERALD},
                                "areaStyle": {"color": EMERALD + "22"}}],
                }).classes("w-full h-56")

        if not accounts:
            with card_box().classes("w-full"):
                empty_state("No accounts yet -- add your current, savings, cash or credit accounts to track net worth.",
                            "account_balance")

        for group, title, types in (("assets", "Assets", ASSET_TYPES), ("liab", "Liabilities", LIABILITY_TYPES)):
            group_accs = [t for t in accounts if t[2] in types]
            if not group_accs:
                continue
            with card_box().classes("w-full"):
                section_header(title, icon="account_balance_wallet",
                               icon_color=INDIGO if group == "assets" else RED, count=len(group_accs))
                for aid, nm, typ, bal in group_accs:
                    with ui.row().classes("w-full items-center gap-2 py-1"):
                        with ui.column().classes("gap-0 min-w-0 flex-grow"):
                            ui.label(nm).classes("text-sm").style(f"color:{TEXT}")
                            ui.label(TYPE_LABELS.get(typ, typ)).classes("text-xs").style(f"color:{TEXT_DIM}")
                        bal_in = ui.number(value=bal, format="%.2f").props(f'prefix="{CUR}" dense').classes("w-32")

                        def save_bal(_=None, aid=aid, bal_in=bal_in):
                            _save_balance(aid, bal_in.value)
                        ui.button(icon="save", on_click=save_bal).props("flat round dense color=primary").tooltip("Save balance")
                        ui.button(icon="delete", on_click=lambda _, aid=aid: _del(aid)).props("flat round dense color=red")

    content()


def reports_page():
    from backend.report import monthly_report, report_html

    page_header("Monthly Report", "A shareable summary of your month.", icon="summarize")
    today = date.today()
    opts, y, m = {}, today.year, today.month
    for _ in range(12):
        opts[f"{y}-{m:02d}"] = date(y, m, 1).strftime("%B %Y")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    month_select = ui.select(opts, value=f"{today.year}-{today.month:02d}", label="Month").props(
        "dense options-dense").classes("w-56")
    container = ui.column().classes("w-full gap-4")

    def render():
        container.clear()
        yr, mo = map(int, month_select.value.split("-"))
        with Session(engine) as session:
            data = monthly_report(session, yr, mo)
        with container:
            with ui.row().classes("w-full gap-4 flex-wrap items-stretch"):
                stat_card("Income", f"{CUR}{data['total_income']:,.2f}", accent=EMERALD, icon="trending_up")
                stat_card("Spent", f"{CUR}{data['total_spent']:,.2f}",
                          f"{data['transaction_count']} transactions", RED, icon="trending_down")
                stat_card("Net", f"{CUR}{data['net']:,.2f}", accent=EMERALD if data['net'] >= 0 else RED,
                          icon="account_balance")
            if data["overall_budget"] is not None:
                ou = data["over_under_budget"]
                with card_box().classes("w-full py-3"):
                    ui.label(f"Overall budget {CUR}{data['overall_budget']:,.2f} — "
                             f"{CUR}{abs(ou):,.2f} {'over' if ou > 0 else 'under'} budget.").classes(
                        "text-sm").style(f"color:{RED if ou > 0 else EMERALD}")

            with card_box().classes("w-full"):
                section_header("Spending by category", icon="pie_chart", icon_color=VIOLET)
                if not data["by_category"]:
                    ui.label("No spending recorded this month.").classes("text-xs").style(f"color:{TEXT_DIM}")
                for name, amt in data["by_category"].items():
                    with ui.row().classes("w-full justify-between py-0.5"):
                        ui.label(name).classes("text-sm").style(f"color:{TEXT}")
                        ui.label(f"{CUR}{amt:,.2f}").classes("text-sm").style(f"color:{TEXT_DIM}")

            if data["top_merchants"]:
                with card_box().classes("w-full"):
                    section_header("Top merchants", icon="storefront", icon_color=AMBER)
                    for name, amt in data["top_merchants"]:
                        with ui.row().classes("w-full justify-between py-0.5"):
                            ui.label(name).classes("text-sm").style(f"color:{TEXT}")
                            ui.label(f"{CUR}{amt:,.2f}").classes("text-sm").style(f"color:{TEXT_DIM}")

            n = data["nutrition"]
            with card_box().classes("w-full"):
                section_header("Nutrition", icon="restaurant", icon_color=INDIGO)
                ui.label(
                    f"{n['days_logged']} day(s) logged. Daily average {n['avg_calories']:,.0f} kcal · "
                    f"P {n['avg_protein']:,.0f}g · C {n['avg_carbs']:,.0f}g · F {n['avg_fat']:,.0f}g."
                ).classes("text-sm").style(f"color:{TEXT_DIM}")

            def download():
                html = report_html(data, CUR)
                ui.download.content(html.encode("utf-8"), f"balance-report-{yr}-{mo:02d}.html", "text/html")
            ui.button("Download report (HTML)", icon="download", on_click=download).props("outline no-caps color=primary")

    month_select.on_value_change(render)
    render()


ROUTES = {
    "/": dashboard,
    "/scheduled": scheduled_page,
    "/recipes": recipes_page,
    "/shopping": shopping_page,
    "/savings": savings_page,
    "/accounts": accounts_page,
    "/reports": reports_page,
    "/add-transaction": add_transaction_page,
    "/transactions": transactions_page,
    "/add-income": add_income_page,
    "/income": income_page,
    "/import": import_statement_page,
    "/add-food": add_food_page,
    "/food-log": food_log_page,
    "/pantry": pantry_page,
    "/subscriptions": subscriptions_page,
    "/prices": prices_page,
    "/forecast": forecast_page,
    "/profile": profile_page,
    "/settings": settings_page,
}

# Route -> module gate. Core routes (dashboard, transactions/add, food/add,
# profile, settings) are omitted = always reachable. Disabled routes render the
# "turned off" notice instead of the page, so a hidden area can't be opened by
# typing its URL. Built from the nav registry, plus /add-income (Income module).
ROUTE_MODULE = {route: mod for _, route, _, mod in NAV_ITEMS if mod}
ROUTE_MODULE["/add-income"] = "income"
for _route, _mod in ROUTE_MODULE.items():
    if _route in ROUTES:
        ROUTES[_route] = _module_guard(ROUTES[_route], _mod)


@ui.page("/")
@ui.page("/{_:path}")
def main_page():
    settings = load_app_settings()
    if settings.pin_hash and not app.storage.user.get("unlocked"):
        render_lock_screen(settings)
        return
    content = shell()
    with content:
        # w-full is essential: the parent content column is align-items:flex-start,
        # so without it this sub_pages wrapper collapses to its content's natural
        # width and every w-full page element inside is measured against that
        # shrunken box instead of the full page width.
        ui.sub_pages(ROUTES).classes("w-full")
