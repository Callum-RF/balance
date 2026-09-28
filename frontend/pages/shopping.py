"""The shopping page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    Category,
    PantryItem,
    PriceObservation,
    ShoppingListItem,
    Transaction,
)

from ..common import CUR, _category_label
from ..components import (
    badge,
    card_box,
    empty_state,
    page_header,
    section_header,
    summary_strip,
)
from ..theme import (
    AMBER,
    EMERALD,
    INDIGO,
    TEXT,
    TEXT_DIM,
)


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
