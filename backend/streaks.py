"""Habit streaks: consecutive days of hitting your goals.

Computes current streaks for water intake, staying within calories, and staying
under the daily budget, from the existing logs. A streak is the run of
consecutive qualifying days ending today (or yesterday, so an unfinished today
doesn't break it).
"""
from datetime import date, timedelta

from sqlmodel import Session, select

from backend.database import engine
from backend.models import BudgetTarget, FoodLog, NutrientGoals, Transaction, WaterLog


def _daily_totals(rows, value_fn):
    by_day = {}
    for r in rows:
        by_day[r.date] = by_day.get(r.date, 0) + (value_fn(r) or 0)
    return by_day


def current_streak(qualifying: set, today: date) -> int:
    """Consecutive qualifying days ending at today, or at yesterday if today
    hasn't qualified yet (so a not-yet-finished today keeps the streak alive)."""
    d = today
    if d not in qualifying:
        d = today - timedelta(days=1)
        if d not in qualifying:
            return 0
    streak = 0
    while d in qualifying:
        streak += 1
        d -= timedelta(days=1)
    return streak


def compute_streaks(today: date = None, window: int = 180) -> list:
    today = today or date.today()
    start = today - timedelta(days=window)
    with Session(engine) as session:
        goals = session.exec(select(NutrientGoals)).first()
        foods = session.exec(select(FoodLog).where(FoodLog.date >= start)).all()
        waters = session.exec(select(WaterLog).where(WaterLog.date >= start)).all()
        txns = session.exec(select(Transaction).where(Transaction.date >= start)).all()
        budget = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711

    out = []
    if goals and goals.water_ml:
        by_day = _daily_totals(waters, lambda w: w.amount_ml)
        qual = {d for d, v in by_day.items() if v >= goals.water_ml}
        out.append({"key": "water", "label": "Water goal", "icon": "water_drop",
                    "streak": current_streak(qual, today)})
    if goals and goals.calories:
        by_day = _daily_totals(foods, lambda f: f.calories)
        qual = {d for d, v in by_day.items() if 0 < v <= goals.calories}
        out.append({"key": "calories", "label": "Within calories", "icon": "local_fire_department",
                    "streak": current_streak(qual, today)})
    if budget and budget.monthly_amount:
        daily_budget = budget.monthly_amount / 30
        spend = _daily_totals(txns, lambda t: t.amount)
        qual = set()
        d = start
        while d <= today:
            if spend.get(d, 0) <= daily_budget:
                qual.add(d)
            d += timedelta(days=1)
        out.append({"key": "budget", "label": "Under daily budget", "icon": "savings",
                    "streak": current_streak(qual, today)})
    return out
