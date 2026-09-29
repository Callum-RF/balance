"""The settings page."""
import hashlib
import json
import secrets
from datetime import date, datetime

from nicegui import app, ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    AppSettings,
    BudgetTarget,
    Category,
    FoodLog,
    Income,
    NutrientGoals,
    PantryItem,
    PriceObservation,
    Subscription,
    Transaction,
    UserProfile,
    WaterLog,
    WeightLog,
)
from backend.modules import MODULE_TIERS, MODULES
from backend.timeutil import utcnow

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
    icon_chip,
    page_header,
    pill_toggle,
    section_header,
    setting_row,
)
from ..shell import inject_theme
from ..theme import (
    AMBER,
    BORDER,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    RED,
    SKY,
    SURFACE,
    TEXT_DIM,
    THEMES,
    VIOLET,
)

MODULE_ICONS = {
    "income": "payments", "networth": "account_balance", "subscriptions": "autorenew",
    "scheduled": "event_repeat", "prices": "trending_up", "forecast": "insights", "savings": "savings",
    "recipes": "menu_book", "pantry": "kitchen", "shopping": "shopping_cart", "import": "upload_file",
    "reports": "summarize",
}
TIER_STYLE = {"money": ("Money", EMERALD), "health": ("Food & kitchen", AMBER), "power": ("Tools", VIOLET)}


# ---------------------------------------------------------------------------
# Settings: display currency, category management, and an optional PIN lock.
# ---------------------------------------------------------------------------
def _hash_pin(pin: str, salt: str) -> str:
    return hashlib.sha256((salt + pin).encode()).hexdigest()


def settings_page():
    page_header("Settings", "How Balance looks, what's in it, and keeping your data safe.")
    settings = load_app_settings()

    def section(title):
        with ui.element("div").classes("b-day"):
            ui.label(title)
        return ui.column().classes(LIST_GROUP)

    def sheet(title, subtitle=None):
        """A dialog for one setting (a bottom sheet on a phone)."""
        dlg = ui.dialog()
        with dlg, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-3 w-full max-w-lg") as card:
            section_header(title, subtitle=subtitle)
        return dlg, card

    def save_setting(**values):
        with Session(engine) as session:
            s = session.exec(select(AppSettings)).first()
            for k, v in values.items():
                setattr(s, k, v)
            session.add(s)
            session.commit()

    # --- appearance ------------------------------------------------------------------
    def set_theme(name):
        save_setting(theme=name)
        ui.run_javascript("location.reload()")

    def set_currency(e):
        save_setting(currency=e.value)
        load_app_settings()
        ui.notify(f"Currency set to {e.value}.", type="positive")

    with section("Appearance"):
        with setting_row("contrast", VIOLET, "Theme"):
            pill_toggle({k: t["label"] for k, t in THEMES.items()}, _theme.ACTIVE_THEME, set_theme)
        with setting_row("payments", EMERALD, "Currency symbol", "Display only -- amounts aren't converted"):
            ui.select(CURRENCY_OPTIONS, value=settings.currency or "£", on_change=set_currency).props(
                "dense outlined options-dense").classes("w-20")

    # --- pages (modules) -------------------------------------------------------------
    enabled = load_enabled_modules()

    def toggle_module(key, value):
        set_module_enabled(key, value)
        reload_hint.classes(remove="b-off")

    def apply_preset(value):
        set_all_modules(value)
        ui.run_javascript("location.reload()")

    for tier_key, tier_label in MODULE_TIERS:
        tier_modules = [(k, m) for k, m in MODULES.items() if m[1] == tier_key]
        if not tier_modules:
            continue
        title, color = TIER_STYLE.get(tier_key, (tier_label, INDIGO))
        with section(f"Pages · {title}"):
            for key, meta in tier_modules:
                with setting_row(MODULE_ICONS.get(key, "widgets"), color, meta[0]):
                    ui.switch(value=enabled.get(key, meta[2]),
                              on_change=lambda e, k=key: toggle_module(k, e.value)).props("color=primary")
    with ui.row().classes("w-full items-center gap-2 b-off") as reload_hint:
        ui.label("Reload to update the menus.").classes("b-hint flex-1")
        ui.button("Reload", icon="refresh", on_click=lambda: ui.run_javascript("location.reload()")).props(
            "unelevated dense no-caps color=primary")
    with ui.row().classes("w-full items-center gap-1 -mt-2"):
        ui.label("Dashboard, Transactions and Food Log are always on.").classes("b-hint flex-1")
        ui.button("All on", on_click=lambda: apply_preset(True)).props("flat dense no-caps color=primary")
        ui.button("Lean", on_click=lambda: apply_preset(False)).props("flat dense no-caps color=primary").tooltip(
            "Just the core: optional pages off")

    # --- your data -------------------------------------------------------------------
    cat_dlg, cat_card = sheet("Categories", "Rename by editing a name; add new ones at the bottom.")
    with cat_card:
        cat_container = ui.column().classes("w-full gap-1")

    backup_dlg, backup_card = sheet(
        "Off-machine backups",
        "Balance snapshots your data daily to data/backups/. Pick a folder on another drive, or a "
        "cloud-synced one, and each snapshot is copied there too -- so one disk failure can't lose everything.")
    with backup_card:
        mirror_input = ui.input(label="Backup folder", value=settings.backup_mirror_path or "",
                                placeholder="e.g. D:\\Backups\\Balance").props("dense clearable").classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Save", on_click=lambda: save_mirror()).props("color=primary unelevated no-caps")

    def save_mirror():
        path = (mirror_input.value or "").strip() or None
        save_setting(backup_mirror_path=path)
        backup_dlg.close()
        ui.notify("Off-machine backups on." if path else "Off-machine backups off.", type="positive")
        mirror_sub.set_text(path or "Off -- only on this machine")

    with Session(engine) as session:
        n_cats = len(session.exec(select(Category)).all())
    with section("Your data"):
        with setting_row("category", VIOLET, "Spending categories", f"{n_cats} categories",
                         on_click=lambda: (render_categories(), cat_dlg.open())):
            pass
        with setting_row("download", SKY, "Download a full backup",
                         "Everything in one JSON file (receipt photos aren't included)",
                         on_click=lambda: export_backup()):
            pass
        with setting_row("backup", EMERALD, "Off-machine backups",
                         settings.backup_mirror_path or "Off -- only on this machine",
                         on_click=backup_dlg.open) as mirror_sub:
            pass

    def export_backup():
        tables = {
            "transactions": Transaction, "income": Income, "food_log": FoodLog,
            "water_log": WaterLog, "weight_log": WeightLog, "pantry": PantryItem,
            "subscriptions": Subscription, "prices": PriceObservation,
            "budgets": BudgetTarget, "categories": Category,
            "profile": UserProfile, "goals": NutrientGoals, "settings": AppSettings,
        }
        payload = {"exported_at": utcnow().isoformat(), "app": "balance", "version": 1}
        with Session(engine) as session:
            for name, model in tables.items():
                payload[name] = [
                    {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in r.model_dump().items()}
                    for r in session.exec(select(model)).all()
                ]
        ui.download.content(json.dumps(payload, indent=1).encode("utf-8"),
                            f"balance-backup-{date.today().isoformat()}.json", "application/json")
        ui.notify("Backup downloaded.", type="positive")

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
            with ui.column().classes(LIST_GROUP):
                for parent in sorted(parents, key=lambda c: c.name.lower()):
                    for c in [parent] + sorted(children.get(parent.id, []), key=lambda c: c.name.lower()):
                        is_parent = c.parent_id is None
                        with ui.element("div").classes("b-row").style("cursor:default; padding:4px 8px 4px 14px"):
                            ui.icon("folder" if is_parent else "subdirectory_arrow_right").classes(
                                "text-base shrink-0").style(f"color:{VIOLET if is_parent else TEXT_DIM}")
                            name_input = ui.input(value=c.name).props("dense borderless").classes("flex-1 min-w-0")
                            name_input.on("blur", lambda e, cid=c.id, inp=name_input: rename_category(cid, inp.value))
                            if usage.get(c.id):
                                badge(f"{usage[c.id]} in use", TEXT_DIM)
                            ui.button(icon="close", on_click=lambda _, cid=c.id: delete_category(cid)).props(
                                "flat round dense").classes("b-icon-btn").tooltip("Delete")
            with ui.row().classes("w-full items-end gap-2 mt-2 no-wrap"):
                parent_opts = {None: "(top level)", **{c.id: c.name for c in parents}}
                new_name = ui.input(label="New category").props("dense").classes("flex-1 min-w-0")
                new_parent = ui.select(parent_opts, value=None, label="Under").props(
                    "dense options-dense").classes("w-36")

                def add_category():
                    name = (new_name.value or "").strip()
                    if not name:
                        return
                    with Session(engine) as session:
                        session.add(Category(name=name, parent_id=new_parent.value))
                        session.commit()
                    ui.notify(f"Added {name}.", type="positive")
                    render_categories()

                ui.button("Add", icon="add", on_click=add_category).props("flat dense no-caps color=primary")

    # --- security --------------------------------------------------------------------
    has_pin = bool(settings.pin_hash)
    pin_dlg, pin_card = sheet("PIN lock", "Ask for a PIN when Balance opens in a new browser session. The "
                                          "JSON API under /api isn't PIN-protected -- your Tailscale network "
                                          "is the real security boundary.")
    with pin_card:
        pin_input = ui.input(label="New PIN (4-8 digits)", password=True, password_toggle_button=True).props(
            'dense inputmode="numeric"').classes("w-full")

        def set_pin():
            pin = (pin_input.value or "").strip()
            if not (pin.isdigit() and 4 <= len(pin) <= 8):
                ui.notify("PIN must be 4-8 digits.", type="warning")
                return
            salt = secrets.token_hex(8)
            save_setting(pin_salt=salt, pin_hash=_hash_pin(pin, salt))
            app.storage.user["unlocked"] = True  # don't lock out the person who just set it
            ui.notify("PIN set.", type="positive")
            ui.run_javascript("location.reload()")

        def clear_pin():
            save_setting(pin_hash=None, pin_salt=None)
            ui.notify("PIN removed.", type="positive")
            ui.run_javascript("location.reload()")

        with ui.row().classes("w-full items-center gap-2"):
            if has_pin:
                ui.button("Remove PIN", icon="lock_open", on_click=clear_pin).props("flat no-caps color=negative")
            ui.space()
            ui.button("Change PIN" if has_pin else "Set PIN", icon="lock", on_click=set_pin).props(
                "unelevated no-caps color=primary")

    with section("Security"):
        with setting_row("lock", AMBER, "PIN lock", "Asks when the app opens" if has_pin else "Off",
                         on_click=pin_dlg.open):
            badge("On" if has_pin else "Off", EMERALD if has_pin else TEXT_DIM)


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
