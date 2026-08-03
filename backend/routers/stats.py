import calendar
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import Transaction, Category, FoodLog

router = APIRouter(prefix="/api/stats", tags=["stats"])

Period = Literal["daily", "weekly", "monthly", "6month", "yearly", "2year"]


def period_bounds(period: Period, ref_date: date) -> tuple[date, date]:
    """Return (start, end) inclusive dates for the period containing ref_date."""
    if period == "daily":
        return ref_date, ref_date
    if period == "weekly":
        start = ref_date - timedelta(days=ref_date.weekday())  # Monday
        end = start + timedelta(days=6)
        return start, end
    if period == "monthly":
        start = ref_date.replace(day=1)
        last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
        end = ref_date.replace(day=last_day)
        return start, end
    if period == "6month":
        # the six calendar months ending with ref_date's month, inclusive
        last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
        end = ref_date.replace(day=last_day)
        month_index = ref_date.year * 12 + (ref_date.month - 1) - 5  # 5 months back
        start = date(month_index // 12, month_index % 12 + 1, 1)
        return start, end
    if period == "yearly":
        return ref_date.replace(month=1, day=1), ref_date.replace(month=12, day=31)
    if period == "2year":
        return date(ref_date.year - 1, 1, 1), date(ref_date.year, 12, 31)
    raise ValueError(f"Unknown period: {period}")


@router.get("/expenses")
def expense_stats(
    period: Period = Query("monthly"),
    ref_date: Optional[date] = None,
    session: Session = Depends(get_session),
):
    ref_date = ref_date or date.today()
    start, end = period_bounds(period, ref_date)
    num_days = (end - start).days + 1

    transactions = session.exec(
        select(Transaction).where(Transaction.date >= start, Transaction.date <= end)
    ).all()

    total = round(sum(t.amount for t in transactions), 2)

    categories = {c.id: c.name for c in session.exec(select(Category)).all()}
    by_category: dict[str, float] = {}
    for t in transactions:
        name = categories.get(t.category_id, "Uncategorized")
        by_category[name] = round(by_category.get(name, 0) + t.amount, 2)

    return {
        "period": period,
        "start": start,
        "end": end,
        "total": total,
        "daily_average": round(total / num_days, 2),
        "num_transactions": len(transactions),
        "by_category": [
            {"category": name, "total": amt} for name, amt in sorted(by_category.items(), key=lambda x: -x[1])
        ],
    }


NUTRIENT_FIELDS = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg"]


@router.get("/nutrition")
def nutrition_stats(
    period: Period = Query("monthly"),
    ref_date: Optional[date] = None,
    session: Session = Depends(get_session),
):
    ref_date = ref_date or date.today()
    start, end = period_bounds(period, ref_date)
    num_days = (end - start).days + 1

    entries = session.exec(
        select(FoodLog).where(FoodLog.date >= start, FoodLog.date <= end)
    ).all()

    totals = {field: 0.0 for field in NUTRIENT_FIELDS}
    for e in entries:
        for field in NUTRIENT_FIELDS:
            value = getattr(e, field)
            if value is not None:
                totals[field] += value

    totals = {k: round(v, 2) for k, v in totals.items()}
    averages = {k: round(v / num_days, 2) for k, v in totals.items()}

    return {
        "period": period,
        "start": start,
        "end": end,
        "num_entries": len(entries),
        "totals": totals,
        "daily_averages": averages,
    }
