"""Page chrome, in the Ensemble style shared with Medley, Cadence and
Crescendo: a frosted top bar (search, theme, app switcher), a floating dock
with a quick-add button in the middle, and a Ctrl/Cmd+K command palette.

Pages render inside ui.sub_pages, so this chrome stays put while they change;
the dock's highlight follows the address client-side (see _NAV_JS)."""

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import AppSettings
from backend.modules import MODULES

from . import theme as _theme
from .common import (
    CUR,
    INCOME_ICONS,
    MEAL_ICONS,
    NAV_ITEMS,
    load_app_settings,
    load_enabled_modules,
    module_enabled,
    refresh_page,
)
from .components import pill_toggle
from .theme import (
    _TOKEN_KEYS,
    BG,
    BORDER,
    EMERALD,
    INDIGO,
    PAGE,
    SURFACE,
    SURFACE_2,
    TEXT,
    TEXT_DIM,
    THEMES,
    _var,
    alpha,
)


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
    dark = ui.dark_mode(_theme.THEME_DARK)
    # Make Quasar's *brand* primary the theme accent too. The CSS --q-primary
    # override below only reaches components that read that var; components that
    # bake the brand colour into an inline style (q-uploader header, q-loading-bar,
    # ripples, spinners) stay NiceGUI-default blue unless we set the brand here.
    # Filled buttons carry white text, so they use a deeper indigo than the
    # bright one text and icons get in dark mode (#818CF8 behind white is ~3:1).
    ui.colors(primary="#6366F1" if _theme.THEME_DARK else THEMES["light"]["INDIGO"])
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
    def _vars(mode):
        return " ".join(f"{_var(k)[4:-1]}: {THEMES[mode][k]};" for k in _TOKEN_KEYS)

    ui.add_head_html(f"""<meta name="theme-color" content="{THEMES[_theme.ACTIVE_THEME]['BG']}">
    <style>
        body.body--dark {{ {_vars("dark")} }}
        body.body--light {{ {_vars("light")} }}
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
            background: linear-gradient(180deg, {alpha(INDIGO, '14')}, {alpha(INDIGO, '0a')}) !important;
            border-color: {alpha(INDIGO, '40')} !important;
            box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 12px 28px -14px {alpha(INDIGO, '59')};
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
            box-shadow: 0 0 0 3px {alpha(INDIGO, '22')};
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
            background: {alpha(INDIGO, '26')} !important;
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

        /* Segmented toggles (meal / type selectors) -- theme-aware; replaces
           Quasar's fixed dark/grey-5, which rendered dark boxes on light themes.
           Inactive: transparent over the SURFACE_2 track with dim text; active:
           the app's primary fill (via toggle-color) with white text. */
        .seg-toggle .q-btn {{ color: {TEXT_DIM} !important; background: transparent !important; }}
        .seg-toggle .q-btn.bg-primary {{ color: #fff !important; }}
    </style>
    """)
    ui.add_head_html(f"<style>{_SHELL_CSS}</style>")
    ui.add_head_html(_NAV_JS)
    return dark


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


_SHELL_CSS = """
body.body--dark  { --b-glass: rgba(20,23,30,.74); --b-glass-strong: rgba(14,17,23,.88); }
body.body--light { --b-glass: rgba(253,251,246,.8); --b-glass-strong: rgba(243,237,225,.92); }
.q-page-container, .q-layout { padding: 0 !important; }

/* Top bar: frosted, fixed. */
.b-topbar { position: fixed; top: 0; left: 0; right: 0; z-index: 2500; height: 60px;
  display: flex; align-items: center; background: var(--b-glass-strong);
  backdrop-filter: blur(16px) saturate(1.3); -webkit-backdrop-filter: blur(16px) saturate(1.3);
  box-shadow: 0 1px 0 var(--b-border); }
.b-topbar-in { width: 100%; max-width: 64rem; margin: 0 auto; padding: 0 20px;
  display: flex; align-items: center; gap: 10px; }
@media (max-width: 640px) { .b-topbar-in { padding: 0 12px; } }
.b-wordmark { font-size: 19px; font-weight: 800; letter-spacing: -.02em; color: var(--b-text);
  text-decoration: none; }
.b-wordmark span { color: var(--b-indigo); }
.b-search { margin-left: auto; display: flex; align-items: center; gap: 10px; height: 38px;
  padding: 0 8px 0 14px; min-width: 250px; border-radius: 999px; cursor: pointer; font-size: 13px;
  color: var(--b-text-dim); background: var(--b-surface); border: 1px solid var(--b-border); }
.b-search:hover { border-color: var(--b-indigo); }
.b-search .kbd { margin-left: auto; font-size: 11px; padding: 2px 7px; border-radius: 6px;
  border: 1px solid currentColor; opacity: .6; }
@media (max-width: 640px) {
  .b-search { min-width: 0; padding: 0 11px; }
  .b-search .txt, .b-search .kbd { display: none; }
}
.b-icon-btn { color: var(--b-text-dim) !important; }

/* Floating dock, with quick-add in the middle. */
.b-dock { position: fixed; left: 50%; transform: translateX(-50%); z-index: 2600;
  bottom: calc(16px + env(safe-area-inset-bottom, 0px));
  display: flex; align-items: center; gap: 2px; padding: 6px; border-radius: 999px;
  background: var(--b-glass); border: 1px solid var(--b-border);
  backdrop-filter: blur(18px) saturate(1.4); -webkit-backdrop-filter: blur(18px) saturate(1.4);
  box-shadow: 0 14px 36px rgba(0,0,0,.28); user-select: none; -webkit-tap-highlight-color: transparent; }
.b-dock-item { display: flex; align-items: center; gap: 0; height: 46px; padding: 0 13px;
  border-radius: 999px; color: var(--b-text-dim); text-decoration: none; cursor: pointer;
  font-size: 13px; font-weight: 650; white-space: nowrap; transition: background .15s, color .15s; }
.b-dock-item .q-icon { font-size: 22px; }
.b-dock-item:hover { color: var(--b-text); background: var(--b-surface-2); }
.b-dock-item.active { background: color-mix(in srgb, var(--b-indigo) 16%, transparent);
  color: var(--b-indigo); gap: 7px; }
.b-dock-label { max-width: 0; overflow: hidden; transition: max-width .2s ease; }
.b-dock-item.active .b-dock-label { max-width: 110px; }
.b-dock-add.q-btn { width: 50px; height: 50px; min-height: 50px; margin: 0 4px;
  box-shadow: 0 8px 20px color-mix(in srgb, var(--b-indigo) 40%, transparent); }
.b-dock-add .q-icon { font-size: 28px; }
@media (max-width: 640px) {
  .b-dock { left: 12px; right: 12px; transform: none; justify-content: space-between; }
  .b-dock-item.active .b-dock-label { max-width: 0; }
  .b-dock-item.active { gap: 0; }
}
.q-notifications__list--bottom { bottom: calc(88px + env(safe-area-inset-bottom)) !important; }

/* Menus opened from the dock (quick-add, More). */
.b-sheet { min-width: 250px; padding: 6px !important; border-radius: 16px !important; }
.b-sheet-label { font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
  color: var(--b-text-dim); padding: 10px 12px 4px; }
.b-sheet .q-item { border-radius: 10px; min-height: 44px; }
.b-sheet .q-item .q-icon { color: var(--b-indigo); }

/* Page headings, as in the other Ensemble apps. */
.b-title { font-size: 34px; font-weight: 800; letter-spacing: -.03em; line-height: 1.05;
  color: var(--b-text); }
.b-subtitle { font-size: 14.5px; color: var(--b-text-dim); }
.b-eyebrow { font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  color: var(--b-indigo); }
@media (max-width: 640px) { .b-title { font-size: 30px; } }

/* Headline figures (summary_strip), as on Cadence's Stats page. */
.b-figs { display: grid; width: 100%; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  margin: 2px 0 6px; }
.b-fig { padding: 4px 20px 4px 0; min-width: 0; }
.b-fig + .b-fig { padding-left: 20px; border-left: 1px solid var(--b-border); }
.b-fig-label { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600;
  color: var(--b-text-dim); }
.b-fig-label .dot { width: 7px; height: 7px; border-radius: 999px; flex: none; }
.b-fig-num { font-size: 30px; font-weight: 800; letter-spacing: -.03em; line-height: 1.15;
  color: var(--b-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 640px) {
  .b-figs { grid-template-columns: 1fr 1fr; row-gap: 12px; }
  .b-fig, .b-fig + .b-fig { padding: 2px 0; border-left: 0; }
  .b-fig-num { font-size: 24px; }
}

/* Pills: tabs and quick filters. */
.b-pills { display: flex; gap: 6px; flex-wrap: wrap; }
.b-pill { height: 34px; padding: 0 15px; border-radius: 999px; display: inline-flex;
  align-items: center; font-size: 13px; font-weight: 650; cursor: pointer; user-select: none;
  color: var(--b-text-dim); background: var(--b-surface); border: 1px solid var(--b-border);
  transition: background .15s, color .15s, border-color .15s; white-space: nowrap; }
.b-pill:hover { color: var(--b-text); border-color: var(--b-indigo); }
.b-pill.active { background: var(--q-primary); border-color: var(--q-primary); color: #fff; }

/* List toolbar: a pill search, a Filters button, active-filter chips. */
.b-toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; width: 100%; }
.b-field { flex: 1 1 220px; }
.b-field .q-field__control { height: 40px !important; min-height: 40px !important;
  border-radius: 999px !important; background: var(--b-surface) !important; padding: 0 14px !important; }
.b-field .q-field__control:before { border-radius: 999px !important; }
.b-field .q-field__marginal { height: 40px; }
.b-tool-btn.q-btn { height: 40px; border-radius: 999px !important; padding: 0 16px;
  background: var(--b-surface) !important; border: 1px solid var(--b-border);
  color: var(--b-text-dim) !important; font-weight: 650; }
.b-tool-btn.on.q-btn { border-color: var(--b-indigo); color: var(--b-indigo) !important;
  background: color-mix(in srgb, var(--b-indigo) 12%, transparent) !important; }
.b-chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.b-chip { display: inline-flex; align-items: center; gap: 4px; height: 28px; padding: 0 6px 0 11px;
  border-radius: 999px; font-size: 12.5px; font-weight: 650; cursor: pointer;
  background: color-mix(in srgb, var(--b-indigo) 14%, transparent); color: var(--b-indigo); }
.b-chip .q-icon { font-size: 15px; }
.b-count { font-size: 12.5px; color: var(--b-text-dim); }
.b-filters { width: min(360px, 92vw); padding: 14px !important; gap: 10px; }
/* On a phone the Filters button is just its icon, so it sits beside the search. */
@media (max-width: 640px) {
  .b-field { flex-basis: 0; }
  .b-tool-btn.q-btn { padding: 0 11px; }
  .b-tool-btn .block { display: none; }
}

/* List rows: the whole row opens the entry. */
.b-row { display: flex; align-items: center; gap: 12px; width: 100%; padding: 10px 14px;
  cursor: pointer; transition: background .12s; }
.b-row:hover { background: var(--b-surface-2); }
.b-row + .b-row { border-top: 1px solid var(--b-border); }
.b-row-icon { width: 38px; height: 38px; border-radius: 12px; flex: none; display: flex;
  align-items: center; justify-content: center; }
.b-row-icon .q-icon { font-size: 20px; }
.b-row-text { flex: 1; min-width: 0; }
.b-row-title { font-weight: 650; font-size: 14.5px; color: var(--b-text); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.b-row-sub { font-size: 12.5px; color: var(--b-text-dim); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.b-row-value { font-weight: 750; font-size: 15px; font-variant-numeric: tabular-nums;
  white-space: nowrap; color: var(--b-text); }
.b-day { display: flex; align-items: baseline; justify-content: space-between; width: 100%;
  margin: 16px 2px 6px; font-size: 12px; font-weight: 700; letter-spacing: .05em;
  text-transform: uppercase; color: var(--b-text-dim); }

/* Dashboard */
.b-budget { width: 100%; display: flex; flex-direction: column; gap: 6px; margin-top: -2px; }
.b-budget-cap { display: flex; justify-content: space-between; gap: 12px; font-size: 12.5px;
  color: var(--b-text-dim); }
.b-budget-cap b { color: var(--b-text); font-weight: 650; }
.b-nudge { display: flex; align-items: center; gap: 12px; width: 100%; padding: 11px 4px;
  cursor: pointer; border-radius: 10px; }
.b-nudge + .b-nudge { border-top: 1px solid var(--b-border); border-radius: 0; }
.b-nudge-cta .q-icon { transition: transform .15s; }
.b-nudge:hover .b-nudge-cta .q-icon { transform: translateX(3px); }
.b-nudge .dot { width: 8px; height: 8px; border-radius: 999px; flex: none; }
.b-nudge-text { flex: 1; min-width: 0; font-size: 14px; color: var(--b-text); }
.b-nudge-cta { display: flex; align-items: center; font-size: 13px; font-weight: 650;
  color: var(--b-indigo); white-space: nowrap; }
.b-nudge-cta .q-icon { font-size: 18px; }
.b-water { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.b-water .b-pill .q-icon { font-size: 15px; margin-right: 4px; color: var(--b-sky); }
.b-streaks { display: flex; gap: 10px; flex-wrap: wrap; }
.b-streak { display: flex; align-items: center; gap: 10px; padding: 10px 14px 10px 12px;
  border-radius: 14px; background: var(--b-surface-2); }
.b-streak .n { font-size: 22px; font-weight: 800; letter-spacing: -.02em; line-height: 1; }
.b-streak .l { font-size: 12px; color: var(--b-text-dim); line-height: 1.25; }

/* Quick-add sheet */
.b-addsheet { width: min(560px, 100vw); max-width: 100vw !important; max-height: 88vh;
  border-radius: 22px 22px 0 0 !important; padding: 0 !important; overflow: hidden;
  display: flex; flex-direction: column; background: var(--b-bg) !important; }
.b-addsheet-head { display: flex; align-items: center; gap: 10px; padding: 14px 14px 10px 18px;
  border-bottom: 1px solid var(--b-border); background: var(--b-surface); }
.b-addsheet-title { font-size: 18px; font-weight: 800; letter-spacing: -.01em; margin-right: 4px; }
.b-addsheet-body { overflow-y: auto; padding: 16px 18px calc(22px + env(safe-area-inset-bottom)); }
.b-grab { width: 38px; height: 4px; border-radius: 999px; background: var(--b-border);
  margin: 8px auto 0; }
.b-recent { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; margin-bottom: 14px;
  scrollbar-width: none; }
.b-recent::-webkit-scrollbar { display: none; }
.b-recent-chip { flex: none; display: flex; align-items: center; gap: 8px; padding: 7px 12px 7px 9px;
  border-radius: 14px; background: var(--b-surface); border: 1px solid var(--b-border);
  cursor: pointer; }
.b-recent-chip:hover { border-color: var(--b-indigo); }
.b-recent-chip .n { font-size: 13px; font-weight: 650; color: var(--b-text); white-space: nowrap; }
.b-recent-chip .k { font-size: 11.5px; color: var(--b-text-dim); }

/* Command palette */
.b-palette { width: min(600px, 92vw); max-width: none !important; padding: 0 !important;
  gap: 0 !important; margin-top: 11vh; align-self: flex-start; overflow: hidden;
  border-radius: 18px !important; box-shadow: 0 30px 80px rgba(0,0,0,.45) !important; }
.b-palette .b-pal-input .q-field__control { height: 56px; padding: 0 16px; }
.b-palette .b-pal-input .q-field__control:before,
.b-palette .b-pal-input .q-field__control:after { display: none; }
.b-palette .b-pal-input input { font-size: 17px; }
.b-pal-results { max-height: 52vh; overflow-y: auto; padding: 6px 8px 10px;
  border-top: 1px solid var(--b-border); }
.b-pal-group { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  color: var(--b-text-dim); padding: 10px 10px 4px; }
.b-pal-row { display: flex; align-items: center; gap: 12px; padding: 9px 10px; border-radius: 10px;
  cursor: pointer; color: var(--b-text); font-size: 14px; font-weight: 550; }
.b-pal-row .q-icon { color: var(--b-indigo); font-size: 20px; }
.b-pal-row:hover { background: var(--b-surface-2); }
.b-pal-row.sel { background: color-mix(in srgb, var(--b-indigo) 16%, transparent); }
.b-pal-foot { display: flex; gap: 16px; padding: 9px 16px; font-size: 11px; color: var(--b-text-dim);
  border-top: 1px solid var(--b-border); }
"""

# Ctrl/Cmd+K (or "/" when not typing) opens the palette -- handled in the page
# so Chrome doesn't send Ctrl+K to its address bar. And the dock's highlight
# follows the address: sub_pages navigates with history.pushState (no reload),
# so that's patched to fire an update, as are back/forward and first load.
_NAV_JS = """
<script>
document.addEventListener('keydown', function (ev) {
  var t = ev.target, typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA'
                                     || t.isContentEditable);
  if (((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k') || (ev.key === '/' && !typing)) {
    ev.preventDefault();
    if (window.emitEvent) emitEvent('b-palette');
  }
});
(function () {
  function updateNav() {
    var path = window.location.pathname, hit = false;
    document.querySelectorAll('.b-dock a.b-dock-item[href]').forEach(function (a) {
      var on = a.getAttribute('href') === path;
      a.classList.toggle('active', on);
      hit = hit || on;
    });
    var more = document.querySelector('.b-dock .b-more');
    if (more) more.classList.toggle('active', !hit && path !== '/add-transaction'
                                              && path !== '/add-food' && path !== '/add-income');
  }
  var _push = history.pushState;
  history.pushState = function () { _push.apply(this, arguments); setTimeout(updateNav, 0); };
  window.addEventListener('popstate', function () { setTimeout(updateNav, 0); });
  window.addEventListener('load', function () { setTimeout(updateNav, 100); });
  setTimeout(updateNav, 400);
})();
</script>
"""

# The dock: the three places visited daily, plus quick-add and More.
DOCK = [("Home", "/", "space_dashboard"), ("Money", "/transactions", "receipt_long"),
        ("Food", "/food-log", "restaurant")]


def _quick_add_items(enabled):
    items = [("Add expense", "/add-transaction", "remove_circle_outline"),
             ("Log food", "/add-food", "restaurant")]
    if module_enabled("income", enabled):
        items.append(("Add income", "/add-income", "add_circle_outline"))
    return items


def _more_sections(enabled):
    """Everything not on the dock, grouped the way the old sidebar was."""
    on_dock = {route for _, route, _ in DOCK}
    by_tier = {"money": [], "health": [], "power": []}
    for label, route, icon, mod in NAV_ITEMS:
        if mod and module_enabled(mod, enabled) and route not in on_dock:
            by_tier[MODULES[mod][1]].append((label, route, icon))
    sections = [(title, by_tier[key]) for title, key in
                (("Money", "money"), ("Health", "health"), ("More", "power")) if by_tier[key]]
    sections.append(("You", [(label, route, icon) for label, route, icon, _ in NAV_ITEMS
                             if route in ("/profile", "/settings")]))
    return sections


_ADD_KINDS = {"expense": "Expense", "food": "Food", "income": "Income"}
_ADDED = {"expense": "Expense added", "food": "Food logged", "income": "Income added"}


def quick_add_sheet(enabled):
    """The + button's sheet: add an expense, a meal or income without leaving
    the page. Rises from the bottom on a phone. Saving closes it and refreshes
    the page underneath (see common.refresh_page). Returns open_sheet(kind)."""
    from .pages.food import recent_foods, relog_food, render_add_food_form
    from .pages.income import recent_incomes, relog_income, render_add_income_form
    from .pages.transactions import render_add_transaction_form

    kinds = {k: v for k, v in _ADD_KINDS.items() if k != "income" or module_enabled("income", enabled)}
    state = {"kind": "expense"}

    with ui.dialog().props("position=bottom") as dlg, ui.card().classes("b-addsheet"):
        with ui.element("div").classes("b-addsheet-head w-full"):
            ui.label("Add").classes("b-addsheet-title")
            select = pill_toggle(kinds, "expense", lambda k: show(k))
            ui.space()
            ui.button(icon="close", on_click=dlg.close).props("flat round dense").classes(
                "b-icon-btn").tooltip("Close")
        body = ui.element("div").classes("b-addsheet-body w-full")

    def saved():
        dlg.close()
        ui.notify(_ADDED[state["kind"]], type="positive")
        refresh_page()

    def one_tap(fid):
        name = relog_food(fid)
        dlg.close()
        ui.notify(f"Logged {name} for today", type="positive")
        refresh_page()

    def one_tap_income(iid):
        what = relog_income(iid)
        dlg.close()
        if what:
            ui.notify(f"Logged {what} for today", type="positive")
        refresh_page()

    def show(kind):
        state["kind"] = kind
        body.clear()
        with body:
            if kind == "food":
                favourites = recent_foods()
                if favourites:
                    ui.label("Again today? Tap to log").classes("b-count")
                    with ui.element("div").classes("b-recent"):
                        for f in favourites:
                            icon, color = MEAL_ICONS.get(f.meal_type, ("restaurant", TEXT_DIM))
                            with ui.element("div").classes("b-recent-chip").on(
                                    "click", lambda fid=f.id: one_tap(fid)):
                                ui.icon(icon).style(f"color:{color}")
                                with ui.column().classes("gap-0"):
                                    ui.label(f.food_name).classes("n")
                                    ui.label(f"{f.calories or 0:,.0f} kcal").classes("k")
                render_add_food_form(on_saved=saved, compact=True)
            elif kind == "income":
                repeats = recent_incomes()
                if repeats:
                    ui.label("Again today? Tap to log").classes("b-count")
                    with ui.element("div").classes("b-recent"):
                        for i in repeats:
                            with ui.element("div").classes("b-recent-chip").on(
                                    "click", lambda iid=i.id: one_tap_income(iid)):
                                ui.icon(INCOME_ICONS.get(i.source, "attach_money")).style(f"color:{EMERALD}")
                                with ui.column().classes("gap-0"):
                                    ui.label(i.payer or i.source).classes("n")
                                    ui.label(f"{CUR}{i.amount:,.2f}").classes("k")
                render_add_income_form(on_saved=saved, compact=True)
            else:
                render_add_transaction_form(on_saved=saved, compact=True)

    def open_sheet(kind="expense"):
        kind = kind if kind in kinds else "expense"
        select(kind, notify=False)
        show(kind)
        dlg.open()

    return open_sheet


def command_palette(toggle_theme, enabled, open_sheet):
    """Jump to any page or quick action by typing. Arrow keys move, Enter
    opens, Esc closes."""
    state = {"items": [], "sel": 0}
    fade = "transition-show=fade transition-hide=fade transition-duration=120"
    with ui.dialog().props(fade) as dlg, ui.card().classes("b-palette"):
        inp = ui.input(placeholder="Go to a page, or add something…").props(
            "borderless autofocus debounce=100").classes("w-full b-pal-input")
        with inp.add_slot("prepend"):
            ui.icon("search").classes("text-xl").style(f"color:{INDIGO}")
        results = ui.element("div").classes("b-pal-results w-full")
        with ui.element("div").classes("b-pal-foot w-full"):
            ui.label("↑↓ to move")
            ui.label("Enter to open")
            ui.label("Esc to close")

    add_kinds = {"/add-transaction": "expense", "/add-food": "food", "/add-income": "income"}
    everything = (
        [("Add", label, icon, add_kinds[route]) for label, route, icon in _quick_add_items(enabled)]
        + [("Go to", label, icon, route) for label, route, icon, mod in NAV_ITEMS
           if module_enabled(mod, enabled)]
        + [("Actions", "Switch light / dark", "brightness_6", None)]
    )

    def build(q):
        q = (q or "").strip().casefold()
        return [it for it in everything if not q or q in it[1].casefold()]

    def render():
        results.clear()
        with results:
            if not state["items"]:
                ui.label("Nothing matches.").classes("b-pal-group")
            last = None
            for i, (group, label, icon, _route) in enumerate(state["items"]):
                if group != last:
                    ui.label(group).classes("b-pal-group")
                    last = group
                with ui.element("div").classes("b-pal-row" + (" sel" if i == state["sel"] else "")) as row:
                    ui.icon(icon)
                    ui.label(label)
                row.on("click", lambda i=i: choose(i))

    def refresh(q):
        state["items"], state["sel"] = build(q), 0
        render()

    def move(d):
        if state["items"]:
            state["sel"] = (state["sel"] + d) % len(state["items"])
            render()

    def choose(i=None):
        if not state["items"]:
            return
        _group, _label, _icon, route = state["items"][state["sel"] if i is None else i]
        dlg.close()
        if route is None:
            toggle_theme()
        elif not route.startswith("/"):
            open_sheet(route)          # an Add item: the sheet, not a page
        else:
            ui.navigate.to(route)

    inp.on_value_change(lambda e: refresh(e.value))
    inp.on("keydown.down.prevent", lambda: move(1))
    inp.on("keydown.up.prevent", lambda: move(-1))
    inp.on("keydown.enter", lambda: choose())

    def open_palette():
        inp.value = ""
        refresh("")
        dlg.open()

    dlg.on("show", lambda: inp.run_method("focus"))
    ui.on("b-palette", open_palette)
    return open_palette


def shell():
    """The page chrome. Returns the content column the current page renders
    into."""
    load_app_settings()   # currency + mode, so a change in Settings applies at once
    dark = inject_theme()
    enabled = load_enabled_modules()

    def toggle_theme():
        dark.value = not dark.value
        mode = "dark" if dark.value else "light"
        _theme.apply_theme(mode)
        with Session(engine) as session:     # remembered, like any other setting
            row = session.exec(select(AppSettings)).first()
            row.theme = mode
            session.add(row)
            session.commit()

    open_sheet = quick_add_sheet(enabled)
    ui.context.client.b_open_sheet = open_sheet     # common.open_add
    open_palette = command_palette(toggle_theme, enabled, open_sheet)

    with ui.element("header").classes("b-topbar"):
        with ui.element("div").classes("b-topbar-in"):
            with ui.link(target="/").classes("b-wordmark"):
                ui.html("bal<span>=</span>nce")
            with ui.element("div").classes("b-search").on("click", open_palette):
                ui.icon("search").classes("text-lg")
                ui.label("Search or jump to…").classes("txt")
                ui.label("Ctrl K").classes("kbd")
            ui.button(icon="brightness_6", on_click=toggle_theme).props(
                "flat round dense").classes("b-icon-btn").tooltip("Light / dark")
            app_switcher()

    with ui.element("nav").classes("b-dock"):
        for label, route, icon in DOCK[:2]:
            with ui.link(target=route).classes("b-dock-item").tooltip(label):
                ui.icon(icon)
                ui.label(label).classes("b-dock-label")
        ui.button(icon="add", on_click=lambda: open_sheet("expense")).props(
            "round unelevated color=primary").classes("b-dock-add").tooltip("Add")
        for label, route, icon in DOCK[2:]:
            with ui.link(target=route).classes("b-dock-item").tooltip(label):
                ui.icon(icon)
                ui.label(label).classes("b-dock-label")
        with ui.element("div").classes("b-dock-item b-more").tooltip("More"):
            ui.icon("apps")
            ui.label("More").classes("b-dock-label")
            with ui.menu().props('anchor="top right" self="bottom right"').classes("b-sheet"):
                for title, items in _more_sections(enabled):
                    ui.label(title).classes("b-sheet-label")
                    for label, route, icon in items:
                        with ui.menu_item(on_click=lambda r=route: ui.navigate.to(r)):
                            with ui.row().classes("items-center gap-3 no-wrap"):
                                ui.icon(icon)
                                ui.label(label)

    # Room for the fixed top bar above and the floating dock below. Inline, as
    # PAGE's own responsive padding (sm:p-6) would otherwise win over a class.
    return ui.column().classes(PAGE).style(
        "padding-top: 84px; padding-bottom: calc(120px + env(safe-area-inset-bottom))")
