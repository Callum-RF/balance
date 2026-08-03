from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import WaterLog, WaterLogCreate, WaterLogRead

router = APIRouter(prefix="/api/water", tags=["water"])


@router.get("/", response_model=List[WaterLogRead])
def list_water(
    start: Optional[date] = None,
    end: Optional[date] = None,
    session: Session = Depends(get_session),
):
    query = select(WaterLog)
    if start:
        query = query.where(WaterLog.date >= start)
    if end:
        query = query.where(WaterLog.date <= end)
    return session.exec(query.order_by(WaterLog.date.desc())).all()


@router.get("/total")
def water_total(target_date: date = None, session: Session = Depends(get_session)):
    target_date = target_date or date.today()
    entries = session.exec(select(WaterLog).where(WaterLog.date == target_date)).all()
    return {"date": target_date, "total_ml": sum(e.amount_ml for e in entries)}


@router.post("/", response_model=WaterLogRead)
def log_water(entry: WaterLogCreate, session: Session = Depends(get_session)):
    db_entry = WaterLog.model_validate(entry)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


@router.delete("/{entry_id}")
def delete_water(entry_id: int, session: Session = Depends(get_session)):
    entry = session.get(WaterLog, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Water log entry not found")
    session.delete(entry)
    session.commit()
    return {"ok": True}
