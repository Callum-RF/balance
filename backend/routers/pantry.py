from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import PantryItem, PantryItemCreate, PantryItemRead, PantryItemUpdate, NutrientGoals

router = APIRouter(prefix="/api/pantry", tags=["pantry"])


@router.get("/", response_model=List[PantryItemRead])
def list_pantry(
    location: Optional[str] = None,
    status: Optional[str] = "active",
    session: Session = Depends(get_session),
):
    query = select(PantryItem)
    if location:
        query = query.where(PantryItem.location == location)
    if status:
        query = query.where(PantryItem.status == status)
    return session.exec(query.order_by(PantryItem.expiration_date)).all()


@router.post("/", response_model=PantryItemRead)
def add_pantry_item(item: PantryItemCreate, session: Session = Depends(get_session)):
    db_item = PantryItem.model_validate(item)
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item


@router.patch("/{item_id}", response_model=PantryItemRead)
def update_pantry_item(item_id: int, update: PantryItemUpdate, session: Session = Depends(get_session)):
    item = session.get(PantryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    data = update.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(item, key, value)
    if "status" in data and data["status"] in ("consumed", "thrown_away", "expired"):
        item.resolved_at = datetime.utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{item_id}")
def delete_pantry_item(item_id: int, session: Session = Depends(get_session)):
    item = session.get(PantryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    session.delete(item)
    session.commit()
    return {"ok": True}


@router.get("/expiring")
def expiring_soon(days: int = 7, session: Session = Depends(get_session)):
    cutoff = date.today() + timedelta(days=days)
    items = session.exec(
        select(PantryItem)
        .where(PantryItem.status == "active")
        .where(PantryItem.expiration_date != None)  # noqa: E711
        .where(PantryItem.expiration_date <= cutoff)
        .order_by(PantryItem.expiration_date)
    ).all()
    return items


@router.get("/waste-summary")
def waste_summary(start: Optional[date] = None, end: Optional[date] = None, session: Session = Depends(get_session)):
    query = select(PantryItem).where(PantryItem.status.in_(["thrown_away", "expired"]))
    items = session.exec(query).all()
    if start:
        items = [i for i in items if i.resolved_at and i.resolved_at.date() >= start]
    if end:
        items = [i for i in items if i.resolved_at and i.resolved_at.date() <= end]
    total_lost = round(sum(i.price or 0 for i in items), 2)
    return {
        "total_items_wasted": len(items),
        "total_value_lost": total_lost,
        "items": items,
    }


@router.get("/runway")
def pantry_runway(session: Session = Depends(get_session)):
    """
    Rough estimate of how many days current active pantry stock will last,
    based on total stored calories vs your daily calorie goal. A simple
    approximation, not a meal-plan-aware forecast.
    """
    items = session.exec(select(PantryItem).where(PantryItem.status == "active")).all()
    goals = session.exec(select(NutrientGoals)).first()
    daily_calorie_goal = goals.calories if goals and goals.calories else 2000

    total_calories = sum(i.calories or 0 for i in items)
    total_protein = sum(i.protein_g or 0 for i in items)
    total_carbs = sum(i.carbs_g or 0 for i in items)
    total_fat = sum(i.fat_g or 0 for i in items)

    days_remaining = round(total_calories / daily_calorie_goal, 1) if daily_calorie_goal else None

    return {
        "total_calories": round(total_calories, 1),
        "total_protein_g": round(total_protein, 1),
        "total_carbs_g": round(total_carbs, 1),
        "total_fat_g": round(total_fat, 1),
        "daily_calorie_goal": daily_calorie_goal,
        "estimated_days_remaining": days_remaining,
    }
