"""Balance's web UI: the routes, and the page that hosts them.

The frontend is split by job:
  theme.py       design tokens -- Light / Dark with indigo, as CSS variables
  common.py      shared non-UI pieces: currency, settings, modules, nav, periods
  components.py  reusable UI pieces: cards, headers, badges, gauges, meters
  shell.py       page chrome: theme CSS, header / nav, the Ensemble app switcher
  pages/         one module per page

Importing this module registers the @ui.page routes (run.py does so).
"""

from nicegui import app, ui

from .common import NAV_ITEMS, load_app_settings, set_page_refresh
from .pages.dashboard import dashboard
from .pages.food import add_food_page, food_log_page
from .pages.forecast import forecast_page
from .pages.import_statement import import_statement_page
from .pages.income import add_income_page, income_page
from .pages.pantry import pantry_page
from .pages.prices import prices_page
from .pages.profile import profile_page
from .pages.recipes import recipes_page
from .pages.recurring import recurring_page
from .pages.reports import reports_page
from .pages.savings import savings_and_worth_page
from .pages.settings import render_lock_screen, settings_page
from .pages.shopping import shopping_page
from .pages.transactions import add_transaction_page, transactions_page
from .shell import _module_guard, shell

ROUTES = {
    "/": dashboard,
    "/recurring": recurring_page,
    "/scheduled": lambda: recurring_page("scheduled"),
    "/recipes": recipes_page,
    "/shopping": shopping_page,
    "/savings": savings_and_worth_page,
    "/accounts": savings_and_worth_page,
    "/reports": reports_page,
    "/add-transaction": add_transaction_page,
    "/transactions": transactions_page,
    "/add-income": add_income_page,
    "/income": income_page,
    "/import": import_statement_page,
    "/add-food": add_food_page,
    "/food-log": food_log_page,
    "/pantry": pantry_page,
    "/subscriptions": lambda: recurring_page("subscriptions"),
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
# Pages that use the full 1240px frame (dashboards, charts, list + summary
# side by side). Everything else is mostly a list or a form, and sits in a
# centred reading-width column.
WIDE_ROUTES = {"/", "/transactions", "/income", "/food-log", "/forecast", "/reports"}


def _fresh_page(page_fn, route):
    """Each page starts with no refresh hook, so quick-add never calls into
    the page that was on screen before this one."""
    def wrapped():
        set_page_refresh(None)
        with ui.column().classes("w-full gap-4 sm:gap-6" + ("" if route in WIDE_ROUTES else " b-narrow")):
            page_fn()
    return wrapped


for _route, _mod in ROUTE_MODULE.items():
    if _route in ROUTES:
        ROUTES[_route] = _module_guard(ROUTES[_route], _mod)


ROUTES = {route: _fresh_page(fn, route) for route, fn in ROUTES.items()}


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
