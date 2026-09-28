"""The recipes page."""

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    Recipe,
    RecipeItem,
)
from backend.services.openfoodfacts import lookup_barcode

from ..components import (
    card_box,
    empty_state,
    page_header,
    section_header,
    summary_strip,
)
from ..theme import (
    SKY,
    TEXT,
    TEXT_DIM,
    VIOLET,
)


def recipes_page():
    from backend.recipes import log_recipe, mark_recipe_ingredients_used, recipe_totals

    page_header("Recipes", "Meals from your pantry, costed per serving.", icon="menu_book")

    @ui.refreshable
    def content():
        with Session(engine) as session:
            recipes = session.exec(select(Recipe)).all()
            all_items = session.exec(select(RecipeItem)).all()
        items_by_recipe = {}
        for it in all_items:
            items_by_recipe.setdefault(it.recipe_id, []).append(it)

        summary_strip([
            ("Saved recipes", str(len(recipes)), VIOLET),
            ("Ingredients", str(len(all_items)), SKY) if all_items else None,
        ])

        def _del_recipe(rid):
            with Session(engine) as session:
                for it in session.exec(select(RecipeItem).where(RecipeItem.recipe_id == rid)).all():
                    session.delete(it)
                r = session.get(Recipe, rid)
                if r:
                    session.delete(r)
                session.commit()
            ui.notify("Recipe deleted.", type="info")
            content.refresh()

        def _del_item(iid):
            with Session(engine) as session:
                it = session.get(RecipeItem, iid)
                if it:
                    session.delete(it)
                session.commit()
            content.refresh()

        with ui.expansion("New recipe", icon="add").classes("w-full"):
            with ui.column().classes("gap-1 max-w-xl w-full"):
                r_name = ui.input(label="Recipe name (e.g. Spaghetti Bolognese)").props("dense").classes("w-full")
                r_serv = ui.number(label="Servings it makes", value=1, format="%g").props("dense").classes("w-40")

                def add_recipe():
                    if not r_name.value:
                        ui.notify("Give the recipe a name.", type="warning"); return
                    with Session(engine) as session:
                        session.add(Recipe(name=r_name.value, servings=r_serv.value or 1))
                        session.commit()
                    ui.notify("Recipe created -- add ingredients below.", type="positive")
                    content.refresh()
                ui.button("Create recipe", on_click=add_recipe).props("color=primary unelevated")

        if not recipes:
            with card_box().classes("w-full"):
                empty_state("No recipes yet -- create one above, then add ingredients to log the whole meal in one tap.", "menu_book")

        for r in recipes:
            items = items_by_recipe.get(r.id, [])
            totals, grams = recipe_totals(items)
            servings = r.servings or 1
            with card_box().classes("w-full"):
                with section_header(r.name, icon="menu_book", icon_color=VIOLET,
                                    subtitle=f"Makes {servings:g} serving(s) · {len(items)} ingredient(s)"):
                    ui.button(icon="delete", on_click=lambda _, rid=r.id: _del_recipe(rid)).props("flat round dense color=red")
                ui.label(
                    f"Per serving: {totals['calories'] / servings:,.0f} kcal · "
                    f"P {totals['protein_g'] / servings:,.0f}g · C {totals['carbs_g'] / servings:,.0f}g · "
                    f"F {totals['fat_g'] / servings:,.0f}g"
                ).classes("text-xs").style(f"color:{TEXT_DIM}")

                for it in items:
                    with ui.row().classes("w-full items-center justify-between gap-2 py-1"):
                        ui.label(f"{it.food_name} · {it.quantity_g:g}g · {it.calories or 0:,.0f} kcal").classes(
                            "text-sm min-w-0").style(f"color:{TEXT}")
                        ui.button(icon="close", on_click=lambda _, iid=it.id: _del_item(iid)).props("flat round dense").style(f"color:{TEXT_DIM}")

                with ui.expansion("Add ingredient", icon="add").classes("w-full"):
                    with ui.column().classes("gap-1 w-full"):
                        with ui.row().classes("w-full items-end gap-2 no-wrap"):
                            bc = ui.input(label="Barcode (optional)").props("dense").classes("flex-grow")
                            i_name = ui.input(label="Ingredient").props("dense").classes("flex-grow")
                            i_qty = ui.number(label="Grams", value=100, format="%g").props("dense").classes("w-24")
                        with ui.grid().classes("w-full grid-cols-2 sm:grid-cols-4 gap-2"):
                            i_cal = ui.number(label="Calories").props("dense")
                            i_p = ui.number(label="Protein (g)").props("dense")
                            i_c = ui.number(label="Carbs (g)").props("dense")
                            i_f = ui.number(label="Fat (g)").props("dense")
                        extra = {"fiber_g": None, "sugar_g": None, "sodium_mg": None,
                                 "saturated_fat_g": None, "trans_fat_g": None, "caffeine_mg": None}
                        lookup_note = ui.label().classes("text-xs").style(f"color:{TEXT_DIM}")

                        def do_lookup(_=None, bc=bc, i_name=i_name, i_qty=i_qty, i_cal=i_cal,
                                      i_p=i_p, i_c=i_c, i_f=i_f, extra=extra, note=lookup_note):
                            if not bc.value:
                                return
                            with Session(engine) as session:
                                item = lookup_barcode(session, bc.value)
                            if not item or item.calories_per_100g is None:
                                note.set_text("Not found in Open Food Facts"); return
                            f = (i_qty.value or 100) / 100.0
                            i_name.value = item.name or i_name.value
                            i_cal.value = round((item.calories_per_100g or 0) * f, 1)
                            i_p.value = round((item.protein_per_100g or 0) * f, 1)
                            i_c.value = round((item.carbs_per_100g or 0) * f, 1)
                            i_f.value = round((item.fat_per_100g or 0) * f, 1)
                            extra["fiber_g"] = round((item.fiber_per_100g or 0) * f, 1)
                            extra["sugar_g"] = round((item.sugar_per_100g or 0) * f, 1)
                            extra["sodium_mg"] = round((item.sodium_per_100g or 0) * f, 1)
                            extra["saturated_fat_g"] = round((item.saturated_fat_per_100g or 0) * f, 1)
                            extra["trans_fat_g"] = round((item.trans_fat_per_100g or 0) * f, 1)
                            extra["caffeine_mg"] = round((item.caffeine_per_100g or 0) * f, 1)
                            note.set_text(f"Found: {item.name}")

                        with bc.add_slot("append"):
                            ui.icon("search").classes("cursor-pointer text-sm").style(f"color:{TEXT_DIM}").on("click", do_lookup)

                        def add_ingredient(_=None, rid=r.id, bc=bc, i_name=i_name, i_qty=i_qty,
                                           i_cal=i_cal, i_p=i_p, i_c=i_c, i_f=i_f, extra=extra):
                            if not i_name.value:
                                ui.notify("Name the ingredient.", type="warning"); return
                            with Session(engine) as session:
                                session.add(RecipeItem(
                                    recipe_id=rid, food_name=i_name.value, quantity_g=i_qty.value or 0,
                                    barcode=bc.value or None, calories=i_cal.value, protein_g=i_p.value,
                                    carbs_g=i_c.value, fat_g=i_f.value, **extra,
                                ))
                                session.commit()
                            ui.notify("Ingredient added.", type="positive")
                            content.refresh()
                        ui.button("Add ingredient", icon="add", on_click=add_ingredient).props("flat dense no-caps color=primary")

                if items:
                    with ui.row().classes("w-full items-end gap-2 mt-2 flex-wrap"):
                        eat_qty = ui.number(label="Servings eaten", value=1, format="%g").props("dense").classes("w-32")
                        meal_sel = ui.select({"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"},
                                             value="dinner", label="Meal").props("dense options-dense").classes("w-36")
                        use_pantry = ui.checkbox("Use from pantry").props("dense").tooltip(
                            "Also mark matching active pantry items as consumed")

                        def log_it(_=None, rid=r.id, eat_qty=eat_qty, meal_sel=meal_sel, use_pantry=use_pantry):
                            log_recipe(rid, servings_eaten=eat_qty.value or 1, meal_type=meal_sel.value)
                            msg = "Logged to your food diary."
                            if use_pantry.value:
                                n = mark_recipe_ingredients_used(rid)
                                msg += f" {n} pantry item(s) marked used." if n else " No matching pantry items."
                            ui.notify(msg, type="positive")
                        ui.button("Log to diary", icon="restaurant", on_click=log_it).props("unelevated no-caps color=primary")

    content()
