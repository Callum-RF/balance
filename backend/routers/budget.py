from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import BudgetTarget, BudgetTargetCreate, BudgetTargetRead, Transaction, Category
from backend.routers.stats import period_bounds

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.get("/", response_model=List[BudgetTargetRead])
def list_budgets(session: Session = Depends(get_session)):
    return session.exec(select(BudgetTarget)).all()


@router.post("/", response_model=BudgetTargetRead)
def set_budget(target: BudgetTargetCreate, session: Session = Depends(get_session)):
    # one target per category (or one overall target where category_id is None)
    existing = session.exec(
        select(BudgetTarget).where(BudgetTarget.category_id == target.category_id)
    ).first()
    if existing:
        existing.monthly_amount = target.monthly_amount
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    db_target = BudgetTarget.model_validate(target)
    session.add(db_target)
    session.commit()
    session.refresh(db_target)
    return db_target


@router.delete("/{target_id}")
def delete_budget(target_id: int, session: Session = Depends(get_session)):
    target = session.get(BudgetTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Budget target not found")
    session.delete(target)
    session.commit()
    return {"ok": True}


@router.get("/progress")
def budget_progress(ref_date: Optional[date] = None, session: Session = Depends(get_session)):
    """Monthly spend vs target, overall and per category with a target set."""
    ref_date = ref_date or date.today()
    start, end = period_bounds("monthly", ref_date)

    transactions = session.exec(
        select(Transaction).where(Transaction.date >= start, Transaction.date <= end)
    ).all()
    categories = {c.id: c.name for c in session.exec(select(Category)).all()}
    targets = session.exec(select(BudgetTarget)).all()

    spend_by_category: dict = {}
    total_spend = 0.0
    for t in transactions:
        spend_by_category[t.category_id] = spend_by_category.get(t.category_id, 0) + t.amount
        total_spend += t.amount

    results = []
    for target in targets:
        spent = spend_by_category.get(target.category_id, 0.0)
        results.append({
            "category_id": target.category_id,
            "category_name": categories.get(target.category_id, "Overall") if target.category_id else "Overall",
            "target": target.monthly_amount,
            "spent": round(spent, 2),
            "remaining": round(target.monthly_amount - spent, 2),
            "percent_used": round((spent / target.monthly_amount) * 100, 1) if target.monthly_amount else 0,
        })

    overall_target = next((t for t in targets if t.category_id is None), None)
    return {
        "start": start,
        "end": end,
        "total_spent": round(total_spend, 2),
        "overall_target": overall_target.monthly_amount if overall_target else None,
        "by_category": results,
    }
