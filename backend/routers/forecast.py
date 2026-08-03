"""
Caloric ROI forecast: projects where your weight and spending are headed
if your recent habits continue, using explicit, visible assumptions
rather than a black box.

Methodology (deliberately simple and stated up front, not hidden):
- Maintenance calories estimated via the Mifflin-St Jeor equation, scaled
  by an activity multiplier. This is a population-average formula, not a
  measurement of your actual metabolism -- real TDEE varies by +/-10-20%
  between individuals even with identical stats.
- "Recent habits" = trailing 30-day average daily calories and daily
  spend, calculated the same way as the rest of the app's daily averages
  (total / 30, not total / days-with-data).
- Weight change projected using the ~7,700 kcal-per-kg rule of thumb.
  This is a widely used approximation, not a precise prediction -- actual
  weight change is affected by water retention, muscle gain, metabolic
  adaptation, and more.
- Spending projected by holding your trailing 30-day daily average
  constant, which won't capture one-off or seasonal expenses.

This is a projection of current trends, not a guarantee, medical advice,
or financial advice.
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import UserProfile, WeightLog, Transaction, FoodLog, BudgetTarget
from backend.routers.profile import calculate_age

router = APIRouter(prefix="/api/forecast", tags=["forecast"])

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

KCAL_PER_KG = 7700  # widely used rule-of-thumb approximation, not exact


def estimate_bmr(weight_kg: float, height_cm: float, age: int, sex: Optional[str]) -> float:
    """Mifflin-St Jeor equation. `sex` affects a constant offset only;
    if unspecified, the midpoint of the male/female constants is used."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "male":
        return base + 5
    if sex == "female":
        return base - 161
    return base - 78  # midpoint fallback when sex isn't specified


def calibrate_tdee(session: Session, days: int = 28, min_days: int = 14) -> Optional[dict]:
    """Estimate *actual* maintenance calories from logged weight change vs logged
    intake, using the energy-balance identity:  TDEE = avg_intake - (dW*7700)/days.

    This measures your real metabolism from your own data instead of a
    population-average formula. Returns None when there isn't enough data
    (need >= min_days of weight span and enough logged food days to be meaningful).
    """
    today = date.today()
    start = today - timedelta(days=days)
    weights = sorted(
        [w for w in session.exec(
            select(WeightLog).where(WeightLog.date >= start, WeightLog.date <= today)).all()
         if w.weight_kg],
        key=lambda w: w.date,
    )
    if len(weights) < 2:
        return None
    w0, w1 = weights[0], weights[-1]
    span = (w1.date - w0.date).days
    if span < min_days:
        return None

    foods = session.exec(select(FoodLog).where(FoodLog.date >= w0.date, FoodLog.date <= w1.date)).all()
    by_day = {}
    for f in foods:
        if f.calories:
            by_day[f.date] = by_day.get(f.date, 0) + f.calories
    logged_days = len(by_day)
    if logged_days < max(min_days // 2, 7):
        return None

    avg_intake = sum(by_day.values()) / logged_days
    weight_change = w1.weight_kg - w0.weight_kg
    daily_balance = weight_change * KCAL_PER_KG / span  # +ve if gaining (surplus)
    tdee = avg_intake - daily_balance
    if tdee <= 0:
        return None
    return {
        "tdee": round(tdee),
        "avg_intake": round(avg_intake),
        "weight_change_kg": round(weight_change, 2),
        "span_days": span,
        "logged_days": logged_days,
    }


def compute_forecast(session: Session, months: int) -> dict:
    profile = session.exec(select(UserProfile)).first()
    latest_weight = session.exec(select(WeightLog).order_by(WeightLog.date.desc())).first()
    age = calculate_age(profile.date_of_birth) if profile else None

    missing = []
    if not profile or not profile.height_cm:
        missing.append("height")
    if not age:
        missing.append("date of birth")
    if not latest_weight:
        missing.append("a logged weight")

    if missing:
        return {"available": False, "missing_fields": missing}

    activity_level = profile.activity_level or "moderate"
    multiplier = ACTIVITY_MULTIPLIERS.get(activity_level, 1.55)
    bmr = estimate_bmr(latest_weight.weight_kg, profile.height_cm, age, profile.sex)
    tdee_formula = bmr * multiplier

    # Prefer a TDEE calibrated from the user's own weight+intake history when
    # there's enough data -- it's a real measurement, not a population estimate.
    calibrated = calibrate_tdee(session)
    tdee = calibrated["tdee"] if calibrated else tdee_formula
    tdee_source = "calibrated" if calibrated else "formula"

    window_start = date.today() - timedelta(days=30)
    food_entries = session.exec(select(FoodLog).where(FoodLog.date >= window_start)).all()
    avg_daily_calories = sum(f.calories or 0 for f in food_entries) / 30

    transactions = session.exec(select(Transaction).where(Transaction.date >= window_start)).all()
    avg_daily_spend = sum(t.amount for t in transactions) / 30

    daily_calorie_delta = avg_daily_calories - tdee
    overall_budget = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711

    days = months * 30
    projected_weight_change_kg = round((daily_calorie_delta * days) / KCAL_PER_KG, 2)
    projected_end_weight_kg = round(latest_weight.weight_kg + projected_weight_change_kg, 1)
    projected_total_spend = round(avg_daily_spend * days, 2)
    projected_budget_pace = round(overall_budget.monthly_amount * months, 2) if overall_budget else None

    weight_series = [
        {
            "month": m,
            "projected_weight_kg": round(latest_weight.weight_kg + (daily_calorie_delta * m * 30) / KCAL_PER_KG, 1),
        }
        for m in range(0, months + 1)
    ]
    spend_series = [
        {"month": m, "cumulative_spend": round(avg_daily_spend * m * 30, 2)}
        for m in range(0, months + 1)
    ]

    return {
        "available": True,
        "months": months,
        "current_weight_kg": latest_weight.weight_kg,
        "bmr": round(bmr, 0),
        "tdee": round(tdee, 0),
        "tdee_formula": round(tdee_formula, 0),
        "tdee_source": tdee_source,
        "calibrated": calibrated,
        "activity_level": activity_level,
        "avg_daily_calories": round(avg_daily_calories, 0),
        "daily_calorie_delta": round(daily_calorie_delta, 0),
        "projected_weight_change_kg": projected_weight_change_kg,
        "projected_end_weight_kg": projected_end_weight_kg,
        "avg_daily_spend": round(avg_daily_spend, 2),
        "projected_total_spend": projected_total_spend,
        "monthly_budget_target": overall_budget.monthly_amount if overall_budget else None,
        "projected_budget_pace": projected_budget_pace,
        "projected_over_under_budget": (
            round(projected_total_spend - projected_budget_pace, 2) if projected_budget_pace is not None else None
        ),
        "weight_series": weight_series,
        "spend_series": spend_series,
    }


@router.get("/")
def get_forecast(months: int = 6, session: Session = Depends(get_session)):
    return compute_forecast(session, months)
