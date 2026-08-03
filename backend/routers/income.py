from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import Income, IncomeCreate, IncomeRead, IncomeUpdate

router = APIRouter(prefix="/api/income", tags=["income"])


@router.get("/", response_model=List[IncomeRead])
def list_income(
    start: Optional[date] = None,
    end: Optional[date] = None,
    source: Optional[str] = None,
    session: Session = Depends(get_session),
):
    query = select(Income)
    if start:
        query = query.where(Income.date >= start)
    if end:
        query = query.where(Income.date <= end)
    if source:
        query = query.where(Income.source == source)
    query = query.order_by(Income.date.desc())
    return session.exec(query).all()


@router.post("/", response_model=IncomeRead)
def create_income(income: IncomeCreate, session: Session = Depends(get_session)):
    db_income = Income.model_validate(income)
    session.add(db_income)
    session.commit()
    session.refresh(db_income)
    return db_income


@router.patch("/{income_id}", response_model=IncomeRead)
def update_income(income_id: int, update: IncomeUpdate, session: Session = Depends(get_session)):
    income = session.get(Income, income_id)
    if not income:
        raise HTTPException(status_code=404, detail="Income entry not found")
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(income, key, value)
    session.add(income)
    session.commit()
    session.refresh(income)
    return income


@router.delete("/{income_id}")
def delete_income(income_id: int, session: Session = Depends(get_session)):
    income = session.get(Income, income_id)
    if not income:
        raise HTTPException(status_code=404, detail="Income entry not found")
    session.delete(income)
    session.commit()
    return {"ok": True}
