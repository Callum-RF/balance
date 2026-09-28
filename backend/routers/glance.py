"""At-a-glance summary for the Ensemble launcher's Balance tile.

The launcher is a static page on the tailnet root (a different port, so a
different origin), so this is the one route that answers cross-origin — and
only to the launcher's own origin (plus localhost for development), never to
anything else. If a PIN lock is set, it reports "locked" and no figures, so the
tile can't be used to read past the lock.
"""
import os
import re
from datetime import date

from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import AppSettings, FoodLog, NutrientGoals, Transaction
from backend.routers.stats import period_bounds

router = APIRouter(tags=["glance"])

# The Ensemble launcher's origin (the tailnet root). Overridable for another host.
ENSEMBLE_ORIGINS = {
    o.strip() for o in os.getenv(
        "ENSEMBLE_ORIGINS", "https://balance.taildd6c4b.ts.net"
    ).split(",") if o.strip()
}
_LOCAL = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")


def allowed_origin(origin: str | None) -> str | None:
    """The origin to echo back in Access-Control-Allow-Origin, or None."""
    if origin and (origin in ENSEMBLE_ORIGINS or _LOCAL.match(origin)):
        return origin
    return None


def _money(amount: float, cur: str) -> str:
    return f"{cur}{amount:,.0f}" if abs(amount) >= 100 else f"{cur}{amount:,.2f}"


def glance(session: Session, today: date | None = None) -> dict:
    today = today or date.today()
    settings = session.exec(select(AppSettings)).first()
    if settings and settings.pin_hash:
        return {"locked": True, "primary": "Locked", "secondary": "Open Balance to unlock"}
    cur = (settings.currency if settings else None) or "£"

    start, end = period_bounds("monthly", today)
    spent = sum(t.amount for t in session.exec(
        select(Transaction).where(Transaction.date >= start, Transaction.date <= end)
    ).all())

    kcal = sum(f.calories or 0 for f in session.exec(
        select(FoodLog).where(FoodLog.date == today)
    ).all())
    goals = session.exec(select(NutrientGoals)).first()
    goal = goals.calories if goals and goals.calories else None
    if kcal:
        secondary = (f"{kcal:,.0f} of {goal:,.0f} kcal today" if goal
                     else f"{kcal:,.0f} kcal today")
    else:
        secondary = "No food logged today"

    return {"locked": False, "primary": f"{_money(spent, cur)} spent this month",
            "secondary": secondary}


@router.get("/api/glance")
def glance_route(request: Request, response: Response,
                 session: Session = Depends(get_session)):
    origin = allowed_origin(request.headers.get("origin"))
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    response.headers["Cache-Control"] = "no-store"
    return glance(session)
