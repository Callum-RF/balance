"""Regression tests for the scheduled-transactions, recipes, and shopping/
pantry loop features. Each test runs against its own throwaway SQLite DB, so
the real app.db is never touched.

Run from the project root:  python -m pytest tests/ -q
"""
import os
import sys
import tempfile
from datetime import date, datetime

from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta  # noqa: E402

import backend.recurring as recurring  # noqa: E402
import backend.recipes as recipes  # noqa: E402
import backend.cashflow as cashflow  # noqa: E402
from backend.routers.forecast import calibrate_tdee  # noqa: E402
from backend.networth import compute_net_worth, snapshot_if_due  # noqa: E402
import backend.streaks as streaks  # noqa: E402
from backend.report import monthly_report, report_html  # noqa: E402
from backend.models import (  # noqa: E402
    ScheduledTransaction, Transaction, Income, Recipe, RecipeItem,
    PantryItem, FoodLog, Subscription, WeightLog, Account, NetWorthSnapshot,
    NutrientGoals, WaterLog, BudgetTarget, Category,
)


def _fresh_engine():
    eng = create_engine(f"sqlite:///{tempfile.mktemp(suffix='.db')}")
    SQLModel.metadata.create_all(eng)
    return eng


# ---- scheduled transactions -------------------------------------------------
def test_advance_dates():
    assert recurring.advance(date(2026, 1, 31), "monthly") == date(2026, 2, 28)
    assert recurring.advance(date(2026, 1, 15), "weekly") == date(2026, 1, 22)
    assert recurring.advance(date(2024, 2, 29), "yearly") == date(2025, 2, 28)
    assert recurring.advance(date(2026, 12, 15), "monthly") == date(2027, 1, 15)


def test_process_due_auto_catches_up_missed_periods():
    recurring.engine = _fresh_engine()
    with Session(recurring.engine) as s:
        s.add(ScheduledTransaction(kind="expense", amount=9.99, description="Netflix",
              cadence="monthly", next_date=date(2026, 5, 26), auto_post=True))
        s.add(ScheduledTransaction(kind="income", amount=2000, description="Employer",
              source="Salary", cadence="monthly", next_date=date(2026, 7, 25), auto_post=True))
        s.commit()
    posted = recurring.process_due_auto(today=date(2026, 7, 26))
    with Session(recurring.engine) as s:
        assert posted == 4
        assert len(s.exec(select(Transaction)).all()) == 3   # 3 monthly catch-ups
        assert len(s.exec(select(Income)).all()) == 1


def test_post_now_and_skip():
    recurring.engine = _fresh_engine()
    with Session(recurring.engine) as s:
        s.add(ScheduledTransaction(kind="expense", amount=5, description="Manual",
              cadence="weekly", next_date=date(2026, 7, 20), auto_post=False))
        s.commit()
        iid = s.exec(select(ScheduledTransaction)).first().id
    recurring.post_now(iid)
    with Session(recurring.engine) as s:
        assert s.get(ScheduledTransaction, iid).next_date == date(2026, 7, 27)
        assert len(s.exec(select(Transaction)).all()) == 1
    recurring.skip_next(iid)
    with Session(recurring.engine) as s:
        assert s.get(ScheduledTransaction, iid).next_date == date(2026, 8, 3)
        assert len(s.exec(select(Transaction)).all()) == 1  # skip did not post


# ---- recipes ----------------------------------------------------------------
def test_recipe_totals_and_scaled_logging():
    recipes.engine = _fresh_engine()
    with Session(recipes.engine) as s:
        r = Recipe(name="Bowl", servings=2); s.add(r); s.commit(); s.refresh(r)
        rid = r.id
        s.add(RecipeItem(recipe_id=rid, food_name="Chicken", quantity_g=150,
                         calories=300, protein_g=20, carbs_g=40, fat_g=10, fiber_g=4))
        s.add(RecipeItem(recipe_id=rid, food_name="Rice", quantity_g=100,
                         calories=200, protein_g=10, carbs_g=30, fat_g=5, fiber_g=2))
        s.commit()
        items = s.exec(select(RecipeItem)).all()
    totals, grams = recipes.recipe_totals(items)
    assert totals["calories"] == 500 and grams == 250 and totals["fiber_g"] == 6

    fid = recipes.log_recipe(rid, servings_eaten=1, meal_type="dinner")  # scale 0.5
    with Session(recipes.engine) as s:
        e = s.get(FoodLog, fid)
        assert e.food_name == "Bowl" and e.calories == 250 and e.protein_g == 15
        assert e.quantity_g == 125 and e.meal_type == "dinner"


def test_mark_recipe_ingredients_used_is_conservative():
    recipes.engine = _fresh_engine()
    with Session(recipes.engine) as s:
        r = Recipe(name="Dinner", servings=1); s.add(r); s.commit(); s.refresh(r)
        rid = r.id
        s.add(RecipeItem(recipe_id=rid, food_name="Chicken", quantity_g=200))
        s.add(RecipeItem(recipe_id=rid, food_name="Rice", quantity_g=100))
        s.add(PantryItem(name="Chicken breast", status="active", created_at=datetime(2026, 1, 1)))
        s.add(PantryItem(name="Chicken thighs", status="active", created_at=datetime(2026, 2, 1)))
        s.add(PantryItem(name="Basmati rice", status="active", created_at=datetime(2026, 1, 1)))
        s.add(PantryItem(name="Milk", status="active", created_at=datetime(2026, 1, 1)))
        s.commit()
    depleted = recipes.mark_recipe_ingredients_used(rid)
    with Session(recipes.engine) as s:
        status = {p.name: p.status for p in s.exec(select(PantryItem)).all()}
    assert depleted == 2
    assert status["Chicken breast"] == "consumed"   # oldest match only
    assert status["Chicken thighs"] == "active"
    assert status["Basmati rice"] == "consumed"
    assert status["Milk"] == "active"               # unrelated item untouched


# ---- forward cashflow -------------------------------------------------------
def test_upcoming_cashflow_expands_and_excludes():
    cashflow.engine = _fresh_engine()
    with Session(cashflow.engine) as s:
        s.add(Subscription(name="Netflix", amount=9.99, billing_cycle="monthly",
                           next_payment_date=date(2026, 8, 5), active=True))
        s.add(Subscription(name="Domain", amount=100, billing_cycle="yearly",
                           next_payment_date=date(2026, 8, 10), active=True))
        s.add(Subscription(name="Paid off", amount=50, billing_cycle="monthly",
                           next_payment_date=date(2026, 8, 6), active=True,
                           total_payments=3, payments_made=3))
        s.add(Subscription(name="Inactive", amount=5, billing_cycle="monthly",
                           next_payment_date=date(2026, 8, 6), active=False))
        s.add(ScheduledTransaction(kind="income", amount=500, description="Pay",
                                   cadence="weekly", next_date=date(2026, 8, 3), active=True))
        s.add(ScheduledTransaction(kind="expense", amount=1200, description="Rent",
                                   cadence="monthly", next_date=date(2026, 8, 1), active=True))
        s.add(ScheduledTransaction(kind="expense", amount=99, description="FarOff",
                                   cadence="monthly", next_date=date(2026, 10, 1), active=True))
        s.commit()
    summary = cashflow.cashflow_summary(days=30, today=date(2026, 8, 1))
    labels = {e["label"] for e in summary["events"]}
    assert len(summary["events"]) == 8            # weekly Pay x5 + Netflix + Domain + Rent
    assert abs(summary["out"] - 1309.99) < 0.01
    assert abs(summary["in"] - 2500) < 0.01
    assert not (labels & {"Paid off", "Inactive", "FarOff"})
    assert summary["events"] == sorted(summary["events"], key=lambda e: e["date"])


# ---- weight-based TDEE calibration -----------------------------------------
def test_calibrate_tdee_from_energy_balance():
    eng = _fresh_engine()
    today = date.today()
    with Session(eng) as s:
        s.add(WeightLog(date=today - timedelta(days=28), weight_kg=80.0))
        s.add(WeightLog(date=today, weight_kg=79.0))          # -1 kg over 28 days
        for d in range(29):
            s.add(FoodLog(date=today - timedelta(days=28 - d), food_name="x", calories=2000))
        s.commit()
        calib = calibrate_tdee(s)
    # TDEE = avg_intake - (dW*7700)/days = 2000 - (-1*7700/28) = 2275
    assert calib is not None
    assert calib["span_days"] == 28 and calib["weight_change_kg"] == -1.0
    assert calib["avg_intake"] == 2000 and calib["tdee"] == 2275


def test_calibrate_tdee_needs_enough_data():
    eng = _fresh_engine()
    with Session(eng) as s:
        s.add(WeightLog(date=date.today(), weight_kg=80.0)); s.commit()
        assert calibrate_tdee(s) is None


# ---- accounts & net worth ---------------------------------------------------
def test_net_worth_and_daily_snapshot():
    eng = _fresh_engine()
    with Session(eng) as s:
        s.add(Account(name="Current", type="current", balance=1000))
        s.add(Account(name="Savings", type="savings", balance=5000))
        s.add(Account(name="Cash", type="cash", balance=200))
        s.add(Account(name="Visa", type="credit", balance=300))
        s.add(Account(name="Loan", type="loan", balance=10000))
        s.commit()
        nw = compute_net_worth(s)
        assert nw["assets"] == 6200 and nw["liabilities"] == 10300 and nw["net_worth"] == -4100
        snapshot_if_due(s, date(2026, 7, 26))
        snapshot_if_due(s, date(2026, 7, 26))          # same day -> update, not duplicate
        assert len(s.exec(select(NetWorthSnapshot)).all()) == 1
        snapshot_if_due(s, date(2026, 7, 27))          # new day -> new point
        assert len(s.exec(select(NetWorthSnapshot)).all()) == 2


# ---- habit streaks ----------------------------------------------------------
def test_current_streak_counts_and_keeps_today_alive():
    t = date(2026, 7, 26)
    assert streaks.current_streak({t, t - timedelta(1), t - timedelta(2)}, t) == 3
    assert streaks.current_streak({t - timedelta(1), t - timedelta(2)}, t) == 2  # today incomplete
    assert streaks.current_streak({t - timedelta(3)}, t) == 0                    # broken by gap


def test_compute_streaks_across_goals():
    streaks.engine = _fresh_engine()
    today = date.today()
    with Session(streaks.engine) as s:
        s.add(NutrientGoals(calories=2000, water_ml=2000))
        s.add(BudgetTarget(category_id=None, monthly_amount=3000))   # daily 100
        for k in range(3):
            d = today - timedelta(days=k)
            s.add(WaterLog(date=d, amount_ml=2000))
            s.add(FoodLog(date=d, food_name="meal", calories=1500))
        s.add(Transaction(date=today - timedelta(days=3), amount=500))  # breaks budget at -3
        s.commit()
    result = {r["key"]: r["streak"] for r in streaks.compute_streaks(today)}
    assert result == {"water": 3, "calories": 3, "budget": 3}


# ---- monthly report ---------------------------------------------------------
def test_monthly_report_and_html_export():
    eng = _fresh_engine()
    with Session(eng) as s:
        food = Category(name="Food"); s.add(food); s.commit(); s.refresh(food)
        s.add(Transaction(date=date(2026, 6, 3), amount=10, merchant="Tesco", category_id=food.id))
        s.add(Transaction(date=date(2026, 6, 9), amount=20, merchant="Tesco", category_id=food.id))
        s.add(Transaction(date=date(2026, 6, 15), amount=5, merchant="Cafe", category_id=None))
        s.add(Transaction(date=date(2026, 7, 1), amount=999, merchant="July", category_id=food.id))  # other month
        s.add(Income(date=date(2026, 6, 25), amount=1000, source="Salary"))
        s.add(FoodLog(date=date(2026, 6, 3), food_name="a", calories=2000))
        s.add(FoodLog(date=date(2026, 6, 9), food_name="b", calories=2000))
        s.add(NutrientGoals(calories=2000))
        s.add(BudgetTarget(category_id=None, monthly_amount=500))
        s.commit()
        data = monthly_report(s, 2026, 6)
    assert data["total_spent"] == 35 and data["total_income"] == 1000 and data["net"] == 965
    assert data["by_category"] == {"Food": 30, "Uncategorized": 5}
    assert data["top_merchants"] == [("Tesco", 30), ("Cafe", 5)]
    assert data["nutrition"]["days_logged"] == 2 and data["nutrition"]["avg_calories"] == 2000
    assert data["over_under_budget"] == -465 and data["transaction_count"] == 3
    html = report_html(data, "£")
    assert html.startswith("<!doctype html>") and "£1,000.00" in html and "Tesco" in html
