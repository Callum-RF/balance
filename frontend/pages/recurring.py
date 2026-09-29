"""Recurring: subscriptions and scheduled bills/income on one page."""
from nicegui import ui

from ..common import load_enabled_modules, module_enabled
from ..components import page_header, pill_toggle
from .scheduled import scheduled_page
from .subscriptions import subscriptions_page

TABS = {"subscriptions": "Subscriptions", "scheduled": "Scheduled"}


def recurring_page(tab=None):
    """Both kinds of repeating money in one place. `tab` picks the one shown
    first (the old /subscriptions and /scheduled links land on theirs)."""
    enabled = load_enabled_modules()
    tabs = {k: v for k, v in TABS.items() if module_enabled(k, enabled)}
    if not tabs:
        page_header("Recurring", "Turn on Subscriptions or Scheduled in Settings to use this page.")
        return
    tab = tab if tab in tabs else next(iter(tabs))
    adders = {k: {} for k in tabs}
    state = {"tab": tab}
    page_header("Recurring", "What repeats, and what's due next.",
                action=("Add", "add", lambda: adders[state["tab"]]["open"]()))
    views = {}

    def show(key):
        state["tab"] = key
        for k, v in views.items():
            v.classes(remove="b-off") if k == key else v.classes(add="b-off")

    if len(tabs) > 1:
        pill_toggle(tabs, tab, show)
    for key in tabs:
        with ui.column().classes("w-full gap-4 sm:gap-6" + ("" if key == tab else " b-off")) as view:
            (subscriptions_page if key == "subscriptions" else scheduled_page)(embedded=True, adder=adders[key])
        views[key] = view
