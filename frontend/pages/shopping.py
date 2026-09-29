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
    card_box,
    card_box_accent,
    empty_state,
    page_header,
    pill_toggle,
    section_header,
    summary_strip,
)
from ..theme import (
    AMBER,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    TEXT_DIM,
)

# Where an item goes once bought. Misc is for things that aren't food (soap,
# batteries...): ticking those off doesn't put them in the pantry.
PLACES = {"fridge": "Fridge", "freezer": "Freezer", "pantry": "Pantry", "misc": "Misc"}


def shopping_page():
    page_header("Shopping List", "What to buy, linked to pantry and spend.")

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
        default_shop_cat = next((c.id for c in categories if c.name == "Shopping"), default_grocery_cat)

        summary_strip([
            ("To buy", str(len(to_buy)), INDIGO),
            ("Completed", str(len(items) - len(to_buy)), EMERALD) if items else None,
        ])

        def _toggle(iid, val, label):
            # Only the checkout card redraws, so you can tick several in a row.
            with Session(engine) as session:
                it = session.get(ShoppingListItem, iid)
                if it:
                    it.done = val
                    session.add(it); session.commit()
            label.style("text-decoration:line-through; opacity:.6" if val else "text-decoration:none; opacity:1")
            checkout.refresh()

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

        # --- add bar: type and press Enter; where it goes and how many are optional ---
        where = {"value": "pantry"}

        def add_item():
            name = (add_name.value or "").strip()
            if not name:
                return
            with Session(engine) as session:
                session.add(ShoppingListItem(name=name, quantity_note=(add_qty.value or "").strip() or None,
                                             location=where["value"], source="manual"))
                session.commit()
            content.refresh()

        with ui.column().classes("w-full gap-2"):
            with ui.element("div").classes("b-toolbar"):
                add_name = ui.input(placeholder="Add an item, e.g. Milk 2L").props(
                    "dense outlined").classes("b-field")
                with add_name.add_slot("prepend"):
                    ui.icon("add_shopping_cart").classes("text-lg").style(f"color:{TEXT_DIM}")
                add_name.on("keydown.enter", add_item)
                ui.button("Add", on_click=add_item).props("unelevated no-caps color=primary").classes("b-head-btn")
            with ui.row().classes("w-full items-center gap-2"):
                pill_toggle(PLACES, "pantry", lambda k: where.update(value=k))
                add_qty = ui.input(placeholder="How many? (optional)").props("dense borderless").classes("w-44")

        if not items:
            with card_box().classes("w-full"):
                empty_state("Your list is empty -- add items above, or pull from Suggestions below.", "shopping_cart")
        # The list, grouped by where things go once bought; ticked ones sink.
        for place, place_label in PLACES.items():
            group = [i for i in items if (i.location if i.location in PLACES else "pantry") == place]
            if not group:
                continue
            left = sum(1 for i in group if not i.done)
            with ui.element("div").classes("b-day"):
                ui.label(place_label if place != "misc" else "Misc · not food")
                ui.label(f"{left} to buy" if left else "all ticked")
            with ui.column().classes(LIST_GROUP):
                for i in sorted(group, key=lambda x: (x.done, (x.name or "").lower())):
                    with ui.element("div").classes("b-row").style("cursor:default; padding-left:8px"):
                        box = ui.checkbox(value=i.done).props("color=primary")
                        with ui.element("div").classes("b-row-text"):
                            title = ui.label(i.name).classes("b-row-title").style(
                                "text-decoration:line-through; opacity:.6" if i.done else "")
                            sub = " · ".join(x for x in (i.quantity_note,
                                                          None if i.source == "manual" else f"from {i.source}") if x)
                            if sub:
                                ui.label(sub).classes("b-row-sub")
                        box.on_value_change(lambda e, iid=i.id, t=title: _toggle(iid, e.value, t))
                        ui.button(icon="close", on_click=lambda _, iid=i.id: _del(iid)).props(
                            "flat round dense").classes("b-icon-btn").tooltip("Remove")

        @ui.refreshable
        def checkout():
            with Session(engine) as session:
                ticked = session.exec(select(ShoppingListItem).where(ShoppingListItem.done == True)).all()  # noqa: E712
            if not ticked:
                return
            food = [t for t in ticked if t.location != "misc"]
            n = len(ticked)
            with card_box_accent().classes("w-full"):
                section_header(f"Bought {n} ticked item{'s' if n != 1 else ''}?",
                               subtitle=("Food goes into your pantry, misc just comes off the list -- and you can "
                                         "record what you spent in one go." if food and len(food) < n else
                                         "They come off the list, and you can record what you spent." if not food else
                                         "Move them into your pantry, and record what you spent in one go."))
                with ui.row().classes("w-full items-end gap-2 no-wrap"):
                    spend_input = ui.number(label="Total spent (optional)", format="%.2f").props(
                        f'dense prefix="{CUR}"').classes("flex-1")
                    spend_cat = ui.select(category_options, value=default_grocery_cat if food else default_shop_cat,
                                          label="Category").props("dense options-dense").classes("flex-1 min-w-0")

                def buy_checked():
                    moved = cleared = 0
                    with Session(engine) as session:
                        rows = session.exec(select(ShoppingListItem).where(ShoppingListItem.done == True)).all()  # noqa: E712
                        for it in rows:
                            if it.location == "misc":
                                cleared += 1
                            else:
                                session.add(PantryItem(name=it.name, location=it.location or "pantry",
                                                       quantity=1, unit="unit", status="active", purchase_date=today))
                                moved += 1
                            session.delete(it)
                        if spend_input.value:
                            session.add(Transaction(date=today, amount=spend_input.value,
                                                    merchant="Groceries" if moved else "Shopping",
                                                    category_id=spend_cat.value, notes="From shopping list"))
                        session.commit()
                    parts = []
                    if moved:
                        parts.append(f"moved {moved} to the pantry")
                    if cleared:
                        parts.append(f"ticked off {cleared} misc")
                    msg = " and ".join(parts).capitalize() + (" -- spend logged." if spend_input.value else ".")
                    ui.notify(msg, type="positive")
                    content.refresh()

                def clear_checked():
                    with Session(engine) as session:
                        for it in session.exec(select(ShoppingListItem).where(ShoppingListItem.done == True)).all():  # noqa: E712
                            session.delete(it)
                        session.commit()
                    content.refresh()

                with ui.row().classes("w-full items-center gap-2"):
                    ui.button("Add to pantry" if food else "Done", icon="kitchen" if food else "check",
                              on_click=buy_checked).props("unelevated no-caps color=primary")
                    ui.button("Just clear them", on_click=clear_checked).props("flat no-caps").style(
                        f"color:{TEXT_DIM}")

        checkout()

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
            with card_box_accent().classes("w-full gap-1"):
                section_header("Suggestions",
                               subtitle="Running low, used up or expiring -- and things you buy repeatedly")
                with ui.column().classes("w-full gap-0"):
                    for nm, loc, src, reason in suggestions[:20]:
                        with ui.element("div").classes("b-nudge").on(
                                "click", lambda n=nm, l=loc, s=src: _add_suggestion(n, l, s)):
                            ui.element("span").classes("dot").style(
                                f"background:{AMBER if 'expir' in reason else INDIGO}")
                            with ui.column().classes("b-nudge-text gap-0"):
                                ui.label(nm).classes("font-semibold")
                                ui.label(reason.replace(" -- ", " · ")).classes("text-xs").style(f"color:{TEXT_DIM}")
                            with ui.element("div").classes("b-nudge-cta"):
                                ui.label("Add")
                                ui.icon("add")

    content()
