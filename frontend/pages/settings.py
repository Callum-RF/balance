"""The settings page."""
import hashlib
import secrets

from nicegui import app, ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    AppSettings,
    BudgetTarget,
    Category,
    Subscription,
    Transaction,
)
from backend.modules import MODULE_TIERS, MODULES

from .. import theme as _theme
from ..common import (
    CURRENCY_OPTIONS,
    load_app_settings,
    load_enabled_modules,
    set_all_modules,
    set_module_enabled,
)
from ..components import (
    badge,
    card_box,
    icon_chip,
    page_header,
    section_header,
)
from ..shell import inject_theme
from ..theme import (
    AMBER,
    BORDER,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    RED,
    TEXT_DIM,
    THEMES,
    VIOLET,
)


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
                active = key == _theme.ACTIVE_THEME
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
