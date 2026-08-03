from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import FoodLog, FoodLogCreate, FoodLogRead, FoodItemCache
from backend.services.openfoodfacts import lookup_barcode

router = APIRouter(prefix="/api/food-log", tags=["food-log"])


@router.get("/", response_model=List[FoodLogRead])
def list_food_log(
    start: Optional[date] = None,
    end: Optional[date] = None,
    session: Session = Depends(get_session),
):
    query = select(FoodLog)
    if start:
        query = query.where(FoodLog.date >= start)
    if end:
        query = query.where(FoodLog.date <= end)
    query = query.order_by(FoodLog.date.desc())
    return session.exec(query).all()


@router.get("/barcode/{barcode}")
def get_barcode_nutrition(barcode: str, session: Session = Depends(get_session)):
    """Look up nutrition-per-100g for a barcode (cached, else via Open Food Facts)."""
    item = lookup_barcode(session, barcode)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found for this barcode")
    return item


@router.post("/", response_model=FoodLogRead)
def create_food_log(entry: FoodLogCreate, session: Session = Depends(get_session)):
    data = entry.model_dump()

    # If a barcode was given but macros weren't filled in manually, pull them
    # from the (cached) Open Food Facts lookup and scale by quantity_g.
    if data.get("barcode") and data.get("calories") is None:
        cached = lookup_barcode(session, data["barcode"])
        if cached:
            factor = data.get("quantity_g", 100.0) / 100.0
            data["calories"] = _scale(cached.calories_per_100g, factor)
            data["protein_g"] = _scale(cached.protein_per_100g, factor)
            data["carbs_g"] = _scale(cached.carbs_per_100g, factor)
            data["fat_g"] = _scale(cached.fat_per_100g, factor)
            data["fiber_g"] = _scale(cached.fiber_per_100g, factor)
            data["sugar_g"] = _scale(cached.sugar_per_100g, factor)
            data["sodium_mg"] = _scale(cached.sodium_per_100g, factor)
            if not data.get("food_name"):
                data["food_name"] = cached.name

    db_entry = FoodLog(**data)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


@router.delete("/{entry_id}")
def delete_food_log(entry_id: int, session: Session = Depends(get_session)):
    entry = session.get(FoodLog, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Food log entry not found")
    session.delete(entry)
    session.commit()
    return {"ok": True}


def _scale(value: Optional[float], factor: float) -> Optional[float]:
    return round(value * factor, 2) if value is not None else None
