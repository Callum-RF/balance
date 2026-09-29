"""The pantry page."""
from datetime import date, timedelta

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    NutrientGoals,
    PantryItem,
)
from backend.timeutil import utcnow

from ..common import CUR, LOCATION_ICONS
from ..components import (
    card_box,
    card_box_accent,
    date_field,
    empty_state,
    list_row,
    page_header,
    pill_toggle,
    section_header,
    segmented,
    sheet_dialog,
    summary_strip,
    undo_banner,
)
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
)

# ---------------------------------------------------------------------------
# Pantry
# ---------------------------------------------------------------------------
LOCATIONS = ["fridge", "freezer", "pantry"]
GROUPS = ["protein", "carbs", "fat", "produce", "dairy", "other"]
UNITS = ["unit", "g", "kg", "ml", "l"]


def _expiry(d):
    """(text, colour) for an expiry date: how urgent, in words."""
    if not d:
        return None, None
    days = (d - date.today()).days
    if days < 0:
        return f"expired {-days}d ago", RED
    if days == 0:
        return "use today", RED
    if days == 1:
        return "use by tomorrow", RED
    if days <= 3:
        return f"use within {days} days", AMBER
    return f"use by {d.day} {d:%b}", None


def pantry_page():
    adder = {}
    page_header("Pantry", "What's in stock, with cost and macros.",
                action=("Add", "add", lambda: adder["open"]()))
    undo_container = ui.column().classes("w-full")

    def resolve_item(item_id, status):
        with Session(engine) as session:
            item = session.get(PantryItem, item_id)
            if not item:
                return
            name = item.name
            item.status = status
            item.resolved_at = utcnow()
            session.add(item)
            session.commit()

        def undo():
            with Session(engine) as session:
                item = session.get(PantryItem, item_id)
                if item:
                    item.status = "active"
                    item.resolved_at = None
                    session.add(item)
                    session.commit()
            ui.notify("Back in stock.", type="positive")
            content.refresh()

        content.refresh()
        undo_banner(undo_container, f"{name}: {'used up' if status == 'consumed' else 'thrown away'}.", undo)

    def open_item(item_id):
        """One item: use it up, bin it, or correct its details."""
        with Session(engine) as session:
            item = session.get(PantryItem, item_id)
            if not item:
                return
            cur = item.model_dump()
        text, _ = _expiry(cur["expiration_date"])
        with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
            section_header(cur["name"], subtitle=f"In the {cur['location']}" + (f" · {text}" if text else ""))

            def resolve(status):
                dialog.close()
                resolve_item(item_id, status)

            with ui.row().classes("w-full gap-2"):
                ui.button("Used it", icon="check", on_click=lambda: resolve("consumed")).props(
                    "unelevated no-caps color=primary")
                ui.button("Threw it away", icon="delete_outline", on_click=lambda: resolve("thrown_away")).props(
                    "outline no-caps color=negative")
            e_name = ui.input(label="Name", value=cur["name"]).props("dense").classes("w-full")
            with ui.grid().classes("w-full grid-cols-2 gap-x-3 gap-y-1"):
                e_loc = ui.select(LOCATIONS, value=cur["location"], label="Location").props("dense").classes("w-full")
                e_group = ui.select(GROUPS, value=cur["macro_group"] or "other", label="Group").props(
                    "dense").classes("w-full")
                e_qty = ui.number(label="Quantity", value=cur["quantity"]).props("dense").classes("w-full")
                e_unit = ui.select(UNITS, value=cur["unit"] if cur["unit"] in UNITS else "unit",
                                   label="Unit").props("dense").classes("w-full")
                e_price = ui.number(label=f"Price ({CUR})", value=cur["price"]).props("dense").classes("w-full")
                e_exp = date_field("Use by", value=cur["expiration_date"].isoformat() if cur["expiration_date"] else "")

            def save():
                with Session(engine) as session:
                    obj = session.get(PantryItem, item_id)
                    if obj:
                        obj.name = e_name.value or obj.name
                        obj.location = e_loc.value
                        obj.macro_group = e_group.value
                        obj.quantity = e_qty.value or 1
                        obj.unit = e_unit.value
                        obj.price = e_price.value
                        obj.expiration_date = date.fromisoformat(e_exp.value) if e_exp.value else None
                        session.add(obj)
                        session.commit()
                dialog.close()
                content.refresh()

            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", on_click=save).props("color=primary unelevated no-caps")
        dialog.open()

    def render_add_form():
        """Name first -- a name you've stocked before fills in the rest from
        last time -- then where it lives and when it goes off. Macros and the
        group fold away."""
        with Session(engine) as session:
            past = session.exec(select(PantryItem).order_by(PantryItem.id.desc()).limit(300)).all()
        last_by_name = {}
        for it in past:
            last_by_name.setdefault(it.name.strip().lower(), it)
        names = sorted({it.name for it in past})

        with ui.column().classes("gap-2 max-w-xl w-full"):
            name_input = ui.input(label="What is it?", autocomplete=names).props("dense").classes("w-full")
            location = segmented("Where", {"fridge": "Fridge", "freezer": "Freezer", "pantry": "Pantry"},
                                 "fridge")
            with ui.row().classes("w-full gap-3 no-wrap"):
                qty_input = ui.number(label="Quantity", value=1, min=0).props("dense").classes("flex-1")
                unit_select = ui.select(UNITS, value="unit", label="Unit").props("dense options-dense").classes("w-24")
                price_input = ui.number(label=f"Price ({CUR})", format="%.2f").props("dense").classes("flex-1")
            ui.label("Use by").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")
            with ui.row().classes("w-full items-center gap-2"):
                with ui.element("div").classes("b-pills"):
                    for label, days in (("3 days", 3), ("1 week", 7), ("2 weeks", 14), ("1 month", 30)):
                        with ui.element("div").classes("b-pill").on(
                                "click", lambda d=days: setattr(
                                    expiry_input, "value", (date.today() + timedelta(days=d)).isoformat())):
                            ui.label(label)
                expiry_input = date_field(None)
            with ui.expansion("More details", icon="tune", caption="Group, calories, protein").classes("w-full"):
                ui.label("Group").classes("text-xs").style(f"color:{TEXT_DIM}")
                group = {"value": "other"}
                set_group = pill_toggle({g: g.capitalize() for g in GROUPS}, "other",
                                        lambda g: group.update(value=g))
                with ui.row().classes("w-full gap-3 no-wrap"):
                    cal_input = ui.number(label="Calories (total)").props("dense").classes("flex-1")
                    protein_input = ui.number(label="Protein (g, total)").props("dense").classes("flex-1")

            def prefill(e):
                known = last_by_name.get((e.value or "").strip().lower())
                if not known:
                    return
                location.value = known.location
                set_group(known.macro_group if known.macro_group in GROUPS else "other")
                qty_input.value = known.quantity
                unit_select.value = known.unit if known.unit in UNITS else "unit"
                price_input.value = known.price
                cal_input.value = known.calories
                protein_input.value = known.protein_g
                if known.purchase_date and known.expiration_date:
                    shelf = (known.expiration_date - known.purchase_date).days
                    if shelf > 0:
                        expiry_input.value = (date.today() + timedelta(days=shelf)).isoformat()

            name_input.on_value_change(prefill)

            def add_item():
                name = (name_input.value or "").strip()
                if not name:
                    ui.notify("What is it? Add a name first.", type="warning")
                    return
                with Session(engine) as session:
                    session.add(PantryItem(
                        name=name,
                        location=location.value,
                        macro_group=group["value"],
                        quantity=qty_input.value or 1,
                        unit=unit_select.value,
                        price=price_input.value,
                        expiration_date=date.fromisoformat(expiry_input.value) if expiry_input.value else None,
                        purchase_date=date.today(),
                        calories=cal_input.value,
                        protein_g=protein_input.value,
                    ))
                    session.commit()
                adder["close"]()
                ui.notify(f"Added {name} to the {location.value}.",
                          type="positive")
                content.refresh()

            ui.button("Add to pantry", icon="add", on_click=add_item).props("color=primary unelevated no-caps")

    @ui.refreshable
    def content():
        with Session(engine) as session:
            goals = session.exec(select(NutrientGoals)).first() or NutrientGoals()
            items = session.exec(select(PantryItem).where(PantryItem.status == "active")).all()
            wasted = session.exec(select(PantryItem).where(PantryItem.status.in_(["thrown_away", "expired"]))).all()

        total_cal = sum(i.calories or 0 for i in items)
        days_left = round(total_cal / goals.calories, 1) if goals.calories else 0
        stock_value = sum(i.price or 0 for i in items)
        lost = sum(w.price or 0 for w in wasted)
        summary_strip([
            ("Items in stock", str(len(items)), INDIGO),
            ("Est. runway", f"{days_left} days", EMERALD),
            ("Value in stock", f"{CUR}{stock_value:,.2f}", SKY) if stock_value else None,
            ("Lost to waste", f"{CUR}{lost:,.2f}", RED) if lost else None,
        ])

        expiring = sorted([i for i in items if i.expiration_date and (i.expiration_date - date.today()).days <= 3],
                          key=lambda x: x.expiration_date)
        if expiring:
            with card_box_accent().classes("w-full gap-1"):
                section_header("Use these first", subtitle="Going off in the next few days")
                with ui.column().classes("w-full gap-0"):
                    for i in expiring:
                        text, color = _expiry(i.expiration_date)
                        with ui.element("div").classes("b-nudge").on("click", lambda iid=i.id: open_item(iid)):
                            ui.element("span").classes("dot").style(f"background:{color or AMBER}")
                            ui.label(f"{i.name} · {text}").classes("b-nudge-text")
                            with ui.element("div").classes("b-nudge-cta"):
                                ui.label("Open")
                                ui.icon("chevron_right")

        with sheet_dialog("Add to the pantry", adder=adder):
            render_add_form()

        if not items:
            with card_box().classes("w-full"):
                empty_state("Your pantry is empty — add what's in stock above.", "kitchen")

        # Soonest-to-expire first within each location; undated items sink.
        def expiry_sort_key(item):
            return (item.expiration_date is None, item.expiration_date or date.max)

        for location in LOCATIONS:
            location_items = sorted([i for i in items if i.location == location], key=expiry_sort_key)
            if not location_items:
                continue
            loc_icon, loc_color = LOCATION_ICONS.get(location, ("inventory_2", TEXT_DIM))
            loc_value = sum(i.price or 0 for i in location_items)
            with ui.element("div").classes("b-day"):
                ui.label(f"{location.capitalize()} · {len(location_items)}")
                ui.label(f"{CUR}{loc_value:,.2f}" if loc_value else "")
            with ui.column().classes(LIST_GROUP):
                for i in location_items:
                    text, urgency = _expiry(i.expiration_date)
                    qty = (f"{i.quantity:g}{i.unit}" if i.unit != "unit"
                           else f"×{i.quantity:g}" if i.quantity and i.quantity != 1 else None)
                    bits = [qty,
                            i.macro_group if i.macro_group and i.macro_group != "other" else None, text]
                    list_row(loc_icon, urgency or loc_color, i.name, " · ".join(b for b in bits if b),
                             f"{CUR}{i.price:,.2f}" if i.price else "", lambda _, iid=i.id: open_item(iid))

    content()
