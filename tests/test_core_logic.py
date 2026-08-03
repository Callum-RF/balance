"""Regression tests for Balance's core calculation logic.

Run from the project root:  python -m pytest tests/ -q
Covers the pure-logic pieces most likely to break silently: period windows,
custom-range resolution, recurring-payment detection, BMR math, and expiry
labeling. No database rows are created.
"""
import os
import sys
from datetime import date, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.routers.stats import period_bounds  # noqa: E402
from backend.routers.forecast import estimate_bmr, ACTIVITY_MULTIPLIERS  # noqa: E402
from frontend.ui import (  # noqa: E402
    resolve_window, previous_window, detect_recurring_transactions,
    expiry_meta, friendly_range,
)


# ---------------------------------------------------------------- period_bounds
def test_daily_bounds():
    d = date(2026, 7, 24)
    assert period_bounds("daily", d) == (d, d)


def test_weekly_bounds_monday_start():
    start, end = period_bounds("weekly", date(2026, 7, 24))  # a Friday
    assert start == date(2026, 7, 20) and end == date(2026, 7, 26)
    assert start.weekday() == 0 and (end - start).days == 6


def test_monthly_bounds():
    assert period_bounds("monthly", date(2026, 2, 10)) == (date(2026, 2, 1), date(2026, 2, 28))


def test_6month_bounds_and_year_boundary():
    start, end = period_bounds("6month", date(2026, 7, 23))
    assert (start, end) == (date(2026, 2, 1), date(2026, 7, 31))
    start, end = period_bounds("6month", date(2026, 1, 15))
    assert (start, end) == (date(2025, 8, 1), date(2026, 1, 31))


def test_yearly_and_2year_bounds():
    assert period_bounds("yearly", date(2026, 7, 1)) == (date(2026, 1, 1), date(2026, 12, 31))
    assert period_bounds("2year", date(2026, 7, 1)) == (date(2025, 1, 1), date(2026, 12, 31))


# --------------------------------------------------------------- resolve_window
def test_custom_window_passthrough():
    s, e = resolve_window("custom", date.today(), custom_range=(date(2025, 7, 5), date(2026, 7, 19)))
    assert (s, e) == (date(2025, 7, 5), date(2026, 7, 19))


def test_custom_window_reversed_dates_swapped():
    s, e = resolve_window("custom", date.today(), custom_range=(date(2026, 7, 19), date(2025, 7, 5)))
    assert (s, e) == (date(2025, 7, 5), date(2026, 7, 19))


def test_custom_window_missing_range_falls_back_to_month():
    ref = date(2026, 7, 24)
    assert resolve_window("custom", ref, custom_range=None) == period_bounds("monthly", ref)


def test_previous_window_custom_matches_span():
    prev = previous_window("custom", date(2026, 7, 5), 30)
    assert prev == (date(2026, 6, 5), date(2026, 7, 4))
    assert (prev[1] - prev[0]).days + 1 == 30


def test_previous_window_all_time_is_none():
    assert previous_window("all_time", date(2026, 1, 1), 100) is None


# ------------------------------------------------- detect_recurring_transactions
def _tx(days_ago, amount, merchant, is_sub=False):
    return SimpleNamespace(date=date.today() - timedelta(days=days_ago), amount=amount,
                           merchant=merchant, is_subscription_payment=is_sub,
                           category_id=None)


def test_detects_monthly_recurring():
    txns = [_tx(d, 120.0, "British Gas") for d in (5, 35, 65, 95)]
    found = detect_recurring_transactions(txns, [])
    assert len(found) == 1
    c = found[0]
    assert c["merchant"] == "British Gas" and c["cadence"] == "monthly" and c["count"] == 4


def test_ignores_existing_subscriptions_and_flagged_rows():
    txns = [_tx(d, 120.0, "British Gas") for d in (5, 35, 65)]
    assert detect_recurring_transactions(txns, ["british gas"]) == []
    flagged = [_tx(d, 15.99, "Netflix", is_sub=True) for d in (5, 35, 65)]
    assert detect_recurring_transactions(flagged, []) == []


def test_rejects_irregular_amounts():
    txns = [_tx(5, 20.0, "Cafe"), _tx(35, 80.0, "Cafe"), _tx(65, 45.0, "Cafe")]
    assert detect_recurring_transactions(txns, []) == []


def test_rejects_irregular_cadence():
    txns = [_tx(1, 30.0, "Shop"), _tx(4, 30.0, "Shop"), _tx(90, 30.0, "Shop")]
    assert detect_recurring_transactions(txns, []) == []


def test_excluded_categories_never_suggested():
    txns = [_tx(d, 58.0, "Esso") for d in (5, 35, 65, 95)]
    for t in txns:
        t.category_id = 42  # pretend this is the Fuel category
    assert detect_recurring_transactions(txns, [], exclude_category_ids={42}) == []
    # same pattern without the exclusion is still detected
    assert len(detect_recurring_transactions(txns, [])) == 1


# ------------------------------------------------------------------ forecast BMR
def test_mifflin_st_jeor_male():
    # 84kg, 178cm, 34y male: 10*84 + 6.25*178 - 5*34 + 5 = 1787.5
    assert estimate_bmr(84, 178, 34, "male") == 1787.5


def test_mifflin_st_jeor_female_and_default():
    assert estimate_bmr(84, 178, 34, "female") == 1787.5 - 166
    male, female = estimate_bmr(84, 178, 34, "male"), estimate_bmr(84, 178, 34, "female")
    assert estimate_bmr(84, 178, 34, None) == (male + female) / 2


def test_activity_multipliers_ordering():
    vals = [ACTIVITY_MULTIPLIERS[k] for k in ("sedentary", "light", "moderate", "active", "very_active")]
    assert vals == sorted(vals) and vals[0] == 1.2


# ------------------------------------------------------------------ expiry_meta
def test_expiry_meta_labels():
    today = date.today()
    assert expiry_meta(None) is None
    assert expiry_meta(today)[0] == "expires today"
    assert expiry_meta(today - timedelta(days=3))[0] == "expired 3d ago"
    assert expiry_meta(today + timedelta(days=2))[0] == "2d left"
    assert expiry_meta(today + timedelta(days=5))[0] == "5d left"


# --------------------------------------------------------------- friendly_range
def test_friendly_range_formats():
    assert friendly_range(date(2026, 7, 1), date(2026, 7, 31), "monthly") == "July 2026"
    assert friendly_range(date(2026, 1, 1), date(2026, 12, 31), "yearly") == "2026"
    assert "–" in friendly_range(date(2026, 7, 20), date(2026, 7, 26), "weekly")
