from datetime import date, date as date_type, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import (
    UserProfile, UserProfileUpdate,
    WeightLog, WeightLogCreate,
    NutrientGoals, NutrientGoalsUpdate,
)

router = APIRouter(prefix="/api", tags=["profile"])


def _get_or_create_profile(session: Session) -> UserProfile:
    profile = session.exec(select(UserProfile)).first()
    if not profile:
        profile = UserProfile()
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


def _get_or_create_goals(session: Session) -> NutrientGoals:
    goals = session.exec(select(NutrientGoals)).first()
    if not goals:
        goals = NutrientGoals()
        session.add(goals)
        session.commit()
        session.refresh(goals)
    return goals


def calculate_age(dob: Optional[date_type]) -> Optional[int]:
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


@router.get("/profile")
def get_profile(session: Session = Depends(get_session)):
    profile = _get_or_create_profile(session)
    latest_weight = session.exec(select(WeightLog).order_by(WeightLog.date.desc())).first()
    return {
        **profile.model_dump(),
        "age": calculate_age(profile.date_of_birth),
        "latest_weight_kg": latest_weight.weight_kg if latest_weight else None,
        "latest_weight_date": latest_weight.date if latest_weight else None,
    }


@router.put("/profile")
def update_profile(update: UserProfileUpdate, session: Session = Depends(get_session)):
    profile = _get_or_create_profile(session)
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return {**profile.model_dump(), "age": calculate_age(profile.date_of_birth)}


WEIGHT_TREND_WINDOWS = {
    "1d": 1, "3d": 3, "1w": 7, "1m": 30, "3m": 90, "6m": 180, "1y": 365,
}


def compute_weight_trend(session: Session, window_days: int) -> dict:
    """
    Rolling-average weight trend: for each logged entry, averages it with
    any other entries in the trailing `window_days`. Smooths out normal
    day-to-day fluctuation (water, food, sodium) so the underlying trend
    is easier to see than raw scale readings alone. window_days=1 is just
    the raw data with no smoothing.
    """
    entries = session.exec(select(WeightLog).order_by(WeightLog.date)).all()
    if not entries:
        return {"available": False, "points": []}

    points = []
    for i, entry in enumerate(entries):
        window_start = entry.date - timedelta(days=window_days - 1)
        window_entries = [e for e in entries[: i + 1] if e.date >= window_start]
        rolling_avg = sum(e.weight_kg for e in window_entries) / len(window_entries)
        points.append({
            "date": entry.date,
            "raw_weight_kg": entry.weight_kg,
            "rolling_avg_kg": round(rolling_avg, 2),
        })

    first_avg = points[0]["rolling_avg_kg"]
    last_avg = points[-1]["rolling_avg_kg"]
    return {
        "available": True,
        "window_days": window_days,
        "points": points,
        "latest_weight_kg": entries[-1].weight_kg,
        "latest_rolling_avg_kg": last_avg,
        "change_since_first_kg": round(last_avg - first_avg, 2),
        "num_entries": len(entries),
    }


@router.get("/weight/trend")
def weight_trend(window: str = "1w", session: Session = Depends(get_session)):
    window_days = WEIGHT_TREND_WINDOWS.get(window, 7)
    return compute_weight_trend(session, window_days)


@router.get("/weight", response_model=List[WeightLog])
def list_weight(limit: int = 90, session: Session = Depends(get_session)):
    return session.exec(select(WeightLog).order_by(WeightLog.date.desc()).limit(limit)).all()


@router.post("/weight", response_model=WeightLog)
def log_weight(entry: WeightLogCreate, session: Session = Depends(get_session)):
    db_entry = WeightLog.model_validate(entry)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


@router.delete("/weight/{entry_id}")
def delete_weight(entry_id: int, session: Session = Depends(get_session)):
    entry = session.get(WeightLog, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Weight entry not found")
    session.delete(entry)
    session.commit()
    return {"ok": True}


@router.get("/goals")
def get_goals(session: Session = Depends(get_session)):
    return _get_or_create_goals(session)


@router.put("/goals")
def update_goals(update: NutrientGoalsUpdate, session: Session = Depends(get_session)):
    goals = _get_or_create_goals(session)
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(goals, key, value)
    session.add(goals)
    session.commit()
    session.refresh(goals)
    return goals
