"""The recipes page: meals you make, logged to the diary in one tap."""
from datetime import datetime

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
    list_row,
    page_header,
    pill_toggle,
    section_header,
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
    SKY,
    SURFACE,
    TEXT_DIM,
    VIOLET,
)

MEALS = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}
PORTIONS = {0.5: "½", 1.0: "1", 1.5: "1½", 2.0: "2"}


def _meal_now():
    h = datetime.now().hour
    return "breakfast" if h < 11 else "lunch" if h < 15 else "dinner" if h < 21 else "snack"


def recipes_page():
    from backend.recipes import log_recipe, mark_recipe_ingredients_used, recipe_totals

    adder = {}
    page_header("Recipes", "Meals you make, logged to your diary in one tap.",
                action=("New recipe", "add", lambda: adder["open"]()))
    undo_container = ui.column().classes("w-full")

    # --- new recipe: name it, then it opens so you can add ingredients ---------------
    with sheet_dialog("New recipe", "Name it and say how many servings it makes; add ingredients next.",
                      adder=adder):
        r_name = ui.input(label="Recipe (e.g. Chicken stir-fry)").props("dense").classes("w-full")
        r_serv = ui.number(label="Servings it makes", value=2, min=1, format="%g").props("dense").classes("w-40")

        def create():
            if not (r_name.value or "").strip():
                ui.notify("Give the recipe a name.", type="warning")
                return
            with Session(engine) as session:
                r = Recipe(name=r_name.value.strip(), servings=r_serv.value or 1)
                session.add(r)
                session.commit()
                rid = r.id
            adder["close"]()
            r_name.value = ""
            content.refresh()
            open_recipe(rid)

        with ui.row().classes("w-full justify-end"):
            ui.button("Create", on_click=create).props("color=primary unelevated no-caps")

    def load(rid):
        with Session(engine) as session:
            r = session.get(Recipe, rid)
            items = session.exec(select(RecipeItem).where(RecipeItem.recipe_id == rid)).all()
            return (r.model_dump() if r else None), items

    # --- one recipe: log it, see and change its ingredients ------------------------------
    def open_recipe(rid):
        with ui.dialog() as dlg, ui.card().classes(
                f"bg-[{SURFACE}] border border-[{BORDER}] gap-3 w-full max-w-lg"):
            body = ui.column().classes("w-full gap-3")

        def render():
            r, items = load(rid)
            body.clear()
            if not r:
                dlg.close()
                return
            totals, _grams = recipe_totals(items)
            per = r["servings"] or 1
            with body:
                with ui.row().classes("w-full items-start no-wrap"):
                    with ui.column().classes("flex-1 min-w-0 gap-0"):
                        section_header(r["name"], subtitle=f"Makes {per:g} serving{'s' if per != 1 else ''} · "
                                                           f"{len(items)} ingredient{'s' if len(items) != 1 else ''}")
                    ui.button(icon="close", on_click=dlg.close).props("flat round dense").classes("b-icon-btn")
                if items:
                    summary_strip([
                        ("Per serving", f"{totals['calories'] / per:,.0f} kcal", INDIGO),
                        ("Protein", f"{totals['protein_g'] / per:,.0f}g", EMERALD),
                        ("Carbs", f"{totals['carbs_g'] / per:,.0f}g", AMBER),
                        ("Fat", f"{totals['fat_g'] / per:,.0f}g", VIOLET),
                    ], width_class="compact")
                    choice = {"portion": 1.0, "meal": _meal_now()}
                    with ui.column().classes("w-full gap-2"):
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.label("Servings").classes("text-xs w-16").style(f"color:{TEXT_DIM}")
                            pill_toggle(PORTIONS, 1.0, lambda k: choice.update(portion=k))
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.label("Meal").classes("text-xs w-16").style(f"color:{TEXT_DIM}")
                            pill_toggle(MEALS, choice["meal"], lambda k: choice.update(meal=k))
                        use_pantry = ui.checkbox("Also mark the ingredients used from the pantry").props("dense")

                        def log_it():
                            log_recipe(rid, servings_eaten=choice["portion"], meal_type=choice["meal"])
                            msg = f"Logged {r['name']} to today's {choice['meal']}."
                            if use_pantry.value:
                                n = mark_recipe_ingredients_used(rid)
                                msg += f" {n} pantry item{'s' if n != 1 else ''} used." if n else " Nothing matched in the pantry."
                            dlg.close()
                            ui.notify(msg, type="positive")

                        ui.button("Log to today", icon="restaurant", on_click=log_it).props(
                            "unelevated no-caps color=primary").classes("self-start")

                with ui.element("div").classes("b-day").style("margin-top:4px"):
                    ui.label("Ingredients")
                    ui.label(f"{totals['calories']:,.0f} kcal in total" if items else "")
                if items:
                    with ui.column().classes(LIST_GROUP):
                        for it in items:
                            with ui.element("div").classes("b-row").style("cursor:default"):
                                with ui.element("div").classes("b-row-text"):
                                    ui.label(it.food_name).classes("b-row-title")
                                    ui.label(f"{it.quantity_g:g} g · {it.calories or 0:,.0f} kcal · "
                                             f"{it.protein_g or 0:,.0f}g protein").classes("b-row-sub")
                                ui.button(icon="close", on_click=lambda _, iid=it.id: remove_item(iid)).props(
                                    "flat round dense").classes("b-icon-btn").tooltip("Remove")
                else:
                    ui.label("No ingredients yet — add the first below.").classes("b-hint").style("margin:0")

                with ui.expansion("Add an ingredient", icon="add", value=not items).classes("w-full"):
                    ingredient_form()

                with ui.row().classes("w-full items-center"):
                    ui.button("Delete recipe", icon="delete_outline", on_click=delete_recipe).props(
                        "flat no-caps color=negative")

        def ingredient_form():
            with ui.column().classes("w-full gap-1"):
                with ui.row().classes("w-full items-end gap-2 no-wrap"):
                    i_name = ui.input(label="Ingredient").props("dense").classes("flex-1 min-w-0")
                    i_qty = ui.number(label="Grams", value=100, format="%g").props("dense").classes("w-24")
                bc = ui.input(label="Barcode (optional) — fills in the nutrition").props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-4 gap-2"):
                    i_cal = ui.number(label="kcal").props("dense")
                    i_p = ui.number(label="Protein").props("dense")
                    i_c = ui.number(label="Carbs").props("dense")
                    i_f = ui.number(label="Fat").props("dense")
                extra = {"fiber_g": None, "sugar_g": None, "sodium_mg": None,
                         "saturated_fat_g": None, "trans_fat_g": None, "caffeine_mg": None}
                note = ui.label().classes("text-xs").style(f"color:{TEXT_DIM}")

                def lookup(_=None):
                    if not bc.value:
                        return
                    with Session(engine) as session:
                        item = lookup_barcode(session, bc.value)
                    if not item or item.calories_per_100g is None:
                        note.set_text("Not found in Open Food Facts.")
                        return
                    f = (i_qty.value or 100) / 100.0
                    i_name.value = item.name or i_name.value
                    i_cal.value = round((item.calories_per_100g or 0) * f, 1)
                    i_p.value = round((item.protein_per_100g or 0) * f, 1)
                    i_c.value = round((item.carbs_per_100g or 0) * f, 1)
                    i_f.value = round((item.fat_per_100g or 0) * f, 1)
                    for key, attr in (("fiber_g", "fiber_per_100g"), ("sugar_g", "sugar_per_100g"),
                                      ("sodium_mg", "sodium_per_100g"), ("saturated_fat_g", "saturated_fat_per_100g"),
                                      ("trans_fat_g", "trans_fat_per_100g"), ("caffeine_mg", "caffeine_per_100g")):
                        extra[key] = round((getattr(item, attr) or 0) * f, 1)
                    note.set_text(f"Found: {item.name}")

                with bc.add_slot("append"):
                    ui.icon("search").classes("cursor-pointer text-sm").style(f"color:{TEXT_DIM}").on("click", lookup)
                bc.on("keydown.enter", lookup)

                def add():
                    if not (i_name.value or "").strip():
                        ui.notify("Name the ingredient.", type="warning")
                        return
                    with Session(engine) as session:
                        session.add(RecipeItem(
                            recipe_id=rid, food_name=i_name.value.strip(), quantity_g=i_qty.value or 0,
                            barcode=bc.value or None, calories=i_cal.value, protein_g=i_p.value,
                            carbs_g=i_c.value, fat_g=i_f.value, **extra,
                        ))
                        session.commit()
                    render()
                    content.refresh()

                ui.button("Add ingredient", icon="add", on_click=add).props(
                    "flat dense no-caps color=primary").classes("self-start")

        def remove_item(iid):
            with Session(engine) as session:
                it = session.get(RecipeItem, iid)
                if it:
                    session.delete(it)
                    session.commit()
            render()
            content.refresh()

        def delete_recipe():
            with Session(engine) as session:
                r = session.get(Recipe, rid)
                if not r:
                    return
                items = session.exec(select(RecipeItem).where(RecipeItem.recipe_id == rid)).all()
                snap_r = r.model_dump(exclude={"id"})
                snap_items = [it.model_dump(exclude={"id", "recipe_id"}) for it in items]
                for it in items:
                    session.delete(it)
                session.delete(r)
                session.commit()
            dlg.close()

            def undo():
                with Session(engine) as session:
                    r2 = Recipe(**snap_r)
                    session.add(r2)
                    session.commit()
                    for it in snap_items:
                        session.add(RecipeItem(recipe_id=r2.id, **it))
                    session.commit()
                ui.notify("Restored.", type="positive")
                content.refresh()

            content.refresh()
            undo_banner(undo_container, f"Deleted {snap_r['name']}.", undo)

        render()
        dlg.open()

    # --- the list ----------------------------------------------------------------------
    @ui.refreshable
    def content():
        with Session(engine) as session:
            recipes = session.exec(select(Recipe)).all()
            all_items = session.exec(select(RecipeItem)).all()
        by_recipe = {}
        for it in all_items:
            by_recipe.setdefault(it.recipe_id, []).append(it)

        summary_strip([
            ("Saved recipes", str(len(recipes)), VIOLET),
            ("Ingredients", str(len(all_items)), SKY) if all_items else None,
        ])
        if not recipes:
            with card_box().classes("w-full"):
                empty_state("No recipes yet — tap New recipe, add the ingredients once, then log the whole "
                            "meal in one tap whenever you make it.", "menu_book")
            return
        with ui.column().classes(LIST_GROUP):
            for r in sorted(recipes, key=lambda r: r.name.lower()):
                items = by_recipe.get(r.id, [])
                totals, _ = recipe_totals(items)
                per = r.servings or 1
                sub = (f"{totals['protein_g'] / per:,.0f}g protein · makes {per:g} · {len(items)} ingredients"
                       if items else "No ingredients yet")
                list_row("menu_book", VIOLET, r.name, sub,
                         f"{totals['calories'] / per:,.0f} kcal" if items else "",
                         lambda _, rid=r.id: open_recipe(rid))
        ui.label("kcal and protein are per serving. Tap a recipe to log it or change its ingredients.").classes(
            "b-hint")

    content()
