"""The Ensemble launcher's Balance tile: the summary itself, the PIN lock, and
who is allowed to read it cross-origin. Uses an in-memory database."""
import os
import sys
from datetime import date

from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models import AppSettings, FoodLog, NutrientGoals, Transaction  # noqa: E402
from backend.routers.glance import allowed_origin, glance  # noqa: E402

TODAY = date(2026, 9, 28)


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_spend_this_month_and_calories_today():
    with _session() as s:
        s.add(Transaction(date=date(2026, 9, 2), amount=250.0))
        s.add(Transaction(date=date(2026, 9, 27), amount=162.4))
        s.add(Transaction(date=date(2026, 8, 30), amount=999.0))      # last month
        s.add(FoodLog(date=TODAY, food_name="Oats", calories=450))
        s.add(FoodLog(date=TODAY, food_name="Chicken", calories=1400))
        s.add(FoodLog(date=date(2026, 9, 27), food_name="Pizza", calories=900))  # yesterday
        s.add(NutrientGoals(calories=2600))
        s.commit()
        g = glance(s, TODAY)
    assert g == {"locked": False, "primary": "£412 spent this month",
                 "secondary": "1,850 of 2,600 kcal today"}


def test_small_amounts_keep_pence_and_currency_follows_settings():
    with _session() as s:
        s.add(AppSettings(currency="€"))
        s.add(Transaction(date=TODAY, amount=12.5))
        s.commit()
        g = glance(s, TODAY)
    assert g["primary"] == "€12.50 spent this month"
    assert g["secondary"] == "No food logged today"


def test_pin_lock_hides_every_figure():
    with _session() as s:
        s.add(AppSettings(pin_hash="x", pin_salt="y"))
        s.add(Transaction(date=TODAY, amount=500.0))
        s.commit()
        g = glance(s, TODAY)
    assert g["locked"] is True
    assert "500" not in str(g) and "spent" not in str(g)


def test_only_the_launcher_and_localhost_may_read_it():
    assert allowed_origin("https://balance.taildd6c4b.ts.net") == "https://balance.taildd6c4b.ts.net"
    assert allowed_origin("http://localhost:8600") == "http://localhost:8600"
    assert allowed_origin("http://127.0.0.1:8600") == "http://127.0.0.1:8600"
    for bad in ("https://evil.example", "https://balance.taildd6c4b.ts.net.evil.com",
                "https://other.taildd6c4b.ts.net", "http://localhost.evil.com", None, ""):
        assert allowed_origin(bad) is None, bad


def test_route_echoes_only_allowed_origins():
    from fastapi.testclient import TestClient
    from sqlmodel.pool import StaticPool

    from backend.database import get_session
    from backend.main import app

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def memory_session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = memory_session
    try:
        client = TestClient(app)   # no `with`: skips startup (real DB, schedulers)
        ok = client.get("/api/glance", headers={"Origin": "https://balance.taildd6c4b.ts.net"})
        assert ok.status_code == 200
        assert ok.headers["access-control-allow-origin"] == "https://balance.taildd6c4b.ts.net"
        assert ok.headers["cache-control"] == "no-store"
        assert ok.json()["primary"].endswith("spent this month")
        bad = client.get("/api/glance", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in bad.headers
    finally:
        app.dependency_overrides.clear()
