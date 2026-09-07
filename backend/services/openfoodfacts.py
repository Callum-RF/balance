"""
Looks up nutrition info for a barcode via the free Open Food Facts API,
caching results locally so we don't hit the API repeatedly for the same
product.
"""
from typing import Optional

import httpx
from sqlmodel import Session

from backend.models import FoodItemCache
from backend.timeutil import utcnow

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"

# Open Food Facts asks integrators to set a descriptive User-Agent.
HEADERS = {"User-Agent": "PersonalExpenseNutritionTracker/1.0 (personal use)"}


def _extract_nutrition(product: dict) -> dict:
    """Pull the per-100g fields we care about out of an OFF product payload."""
    nutriments = product.get("nutriments", {}) or {}
    return {
        "name": product.get("product_name") or product.get("generic_name") or "Unknown product",
        "calories_per_100g": nutriments.get("energy-kcal_100g"),
        "protein_per_100g": nutriments.get("proteins_100g"),
        "carbs_per_100g": nutriments.get("carbohydrates_100g"),
        "fat_per_100g": nutriments.get("fat_100g"),
        "fiber_per_100g": nutriments.get("fiber_100g"),
        "sugar_per_100g": nutriments.get("sugars_100g"),
        "sodium_per_100g": nutriments.get("sodium_100g"),
    }


def lookup_barcode(session: Session, barcode: str, force_refresh: bool = False) -> Optional[FoodItemCache]:
    """
    Return cached nutrition info for a barcode, fetching from Open Food
    Facts and caching it if it's not already stored (or force_refresh=True).
    Returns None if the product can't be found.
    """
    cached = session.get(FoodItemCache, barcode)
    if cached and not force_refresh:
        return cached

    try:
        resp = httpx.get(OFF_URL.format(barcode=barcode), headers=HEADERS, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return cached  # network/API problem: fall back to whatever we have cached, if anything

    if data.get("status") != 1:
        return cached  # product not found in OFF

    nutrition = _extract_nutrition(data.get("product", {}))

    if cached:
        for key, value in nutrition.items():
            setattr(cached, key, value)
        cached.last_updated = utcnow()
        item = cached
    else:
        item = FoodItemCache(barcode=barcode, **nutrition)

    session.add(item)
    session.commit()
    session.refresh(item)
    return item
