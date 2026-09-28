"""The pantry page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    NutrientGoals,
    PantryItem,
)
from backend.timeutil import utcnow

from ..common import CUR, LOCATION_ICONS, MACRO_GROUP_ICONS
from ..components import (
    card_box,
    date_field,
    page_header,
    render_expiry_badge,
    section_header,
    summary_strip,
)
from ..theme import (
    AMBER,
    EMERALD,
    INDIGO,
    RED,
    SKY,
    SURFACE_2,
    TEXT_DIM,
    alpha,
)


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
                    item.resolved_at = utcnow()
                    session.add(item)
                    session.commit()
            content.refresh()

        expiring = [i for i in items if i.expiration_date and (i.expiration_date - date.today()).days <= 7]
        if expiring:
            with card_box().classes("w-full gap-2").style(f"border-color:{alpha(AMBER, '66')}"):
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
