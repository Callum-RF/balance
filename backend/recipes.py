"""Recipes / composed meals -> food-diary logging.

A recipe is a set of ingredients with absolute nutrient totals. Logging a
recipe sums those totals, scales by (servings eaten / servings the recipe
makes), and writes a single aggregated FoodLog entry named after the recipe --
so a whole meal is one tap and one clean line in the diary.
"""
from datetime import date as date_type, datetime

from sqlmodel import Session, select

from backend.database import engine
from backend.models import FoodLog, PantryItem, Recipe, RecipeItem
from backend.timeutil import utcnow

NUTRIENTS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g",
             "sodium_mg", "saturated_fat_g", "trans_fat_g", "added_sugar_g",
             "alcohol_g", "caffeine_mg")


def recipe_totals(items):
    """Sum absolute nutrient totals and grams across a recipe's ingredients."""
    totals = {n: 0.0 for n in NUTRIENTS}
    grams = 0.0
    for it in items:
        grams += it.quantity_g or 0
        for n in NUTRIENTS:
            v = getattr(it, n, None)
            if v:
                totals[n] += v
    return totals, grams


def log_recipe(recipe_id: int, servings_eaten: float = 1.0, meal_type: str = None,
               on_date: date_type = None, tag: str = None):
    """Write one aggregated FoodLog entry for `servings_eaten` of the recipe.
    Returns the new FoodLog id, or None if the recipe is missing."""
    on_date = on_date or date_type.today()
    with Session(engine) as session:
        recipe = session.get(Recipe, recipe_id)
        if not recipe:
            return None
        items = session.exec(select(RecipeItem).where(RecipeItem.recipe_id == recipe_id)).all()
        totals, grams = recipe_totals(items)
        scale = (servings_eaten or 0) / (recipe.servings or 1)
        entry = FoodLog(
            date=on_date, meal_type=meal_type, food_name=recipe.name,
            quantity_g=round(grams * scale, 1), tag=tag,
            **{n: round(totals[n] * scale, 2) for n in NUTRIENTS},
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry.id


def mark_recipe_ingredients_used(recipe_id: int) -> int:
    """Best-effort: for each ingredient, mark the oldest matching *active* pantry
    item as consumed. Name match is case-insensitive substring (either way).
    Returns how many pantry items were depleted. Conservative -- at most one
    pantry item per ingredient, and only active items are touched."""
    depleted = 0
    with Session(engine) as session:
        items = session.exec(select(RecipeItem).where(RecipeItem.recipe_id == recipe_id)).all()
        for it in items:
            name = (it.food_name or "").strip().lower()
            if not name:
                continue
            active = session.exec(
                select(PantryItem).where(PantryItem.status == "active")
            ).all()
            active.sort(key=lambda p: p.created_at or datetime.min)  # oldest first (FIFO)
            match = next(
                (p for p in active
                 if name in (p.name or "").lower() or (p.name or "").lower() in name),
                None,
            )
            if match:
                match.status = "consumed"
                match.resolved_at = utcnow()
                session.add(match)
                session.commit()  # commit so the next ingredient re-queries without it
                depleted += 1
    return depleted
