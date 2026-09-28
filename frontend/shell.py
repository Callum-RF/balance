"""Page chrome: theme CSS, the app switcher, the header / nav shell."""

from nicegui import ui

from backend.modules import MODULES

from . import theme as _theme
from .common import (
    BOTTOM_NAV_ITEMS,
    NAV_ITEMS,
    load_app_settings,
    load_enabled_modules,
    module_enabled,
)
from .theme import (
    _TOKEN_KEYS,
    BG,
    BORDER,
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
    (ui.dark_mode().enable() if _theme.THEME_DARK else ui.dark_mode().disable())
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
        .drawer-nav-item.nav-active {{ color: {TEXT} !important; background: {alpha(INDIGO, '22')}; }}

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
