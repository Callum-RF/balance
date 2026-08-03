from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import PriceObservation, PriceObservationCreate, PriceObservationRead, PriceObservationUpdate

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("/", response_model=List[PriceObservationRead])
def list_prices(item_name: Optional[str] = None, session: Session = Depends(get_session)):
    query = select(PriceObservation)
    if item_name:
        query = query.where(PriceObservation.item_name == item_name)
    return session.exec(query.order_by(PriceObservation.date)).all()


@router.post("/", response_model=PriceObservationRead)
def record_price(observation: PriceObservationCreate, session: Session = Depends(get_session)):
    db_obs = PriceObservation.model_validate(observation)
    session.add(db_obs)
    session.commit()
    session.refresh(db_obs)
    return db_obs


@router.patch("/{observation_id}", response_model=PriceObservationRead)
def update_price(observation_id: int, update: PriceObservationUpdate, session: Session = Depends(get_session)):
    obs = session.get(PriceObservation, observation_id)
    if not obs:
        raise HTTPException(status_code=404, detail="Price observation not found")
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(obs, key, value)
    session.add(obs)
    session.commit()
    session.refresh(obs)
    return obs


@router.delete("/{observation_id}")
def delete_price(observation_id: int, session: Session = Depends(get_session)):
    obs = session.get(PriceObservation, observation_id)
    if not obs:
        raise HTTPException(status_code=404, detail="Price observation not found")
    session.delete(obs)
    session.commit()
    return {"ok": True}


@router.get("/history")
def price_history(item_name: str, session: Session = Depends(get_session)):
    """Chronological price points plus monthly averages, for a line graph."""
    observations = session.exec(
        select(PriceObservation).where(PriceObservation.item_name == item_name).order_by(PriceObservation.date)
    ).all()

    monthly = defaultdict(list)
    for o in observations:
        key = f"{o.date.year}-{o.date.month:02d}"
        monthly[key].append(o.price)

    monthly_averages = [
        {"month": month, "average_price": round(sum(prices) / len(prices), 2)}
        for month, prices in sorted(monthly.items())
    ]

    first_price = observations[0].price if observations else None
    last_price = observations[-1].price if observations else None
    change_pct = (
        round(((last_price - first_price) / first_price) * 100, 1)
        if first_price and last_price and first_price != 0
        else None
    )

    return {
        "item_name": item_name,
        "observations": observations,
        "monthly_averages": monthly_averages,
        "change_pct_since_first_observation": change_pct,
    }


@router.get("/items")
def tracked_items(session: Session = Depends(get_session)):
    """Distinct item names that have at least one price observation."""
    observations = session.exec(select(PriceObservation)).all()
    names = sorted({o.item_name for o in observations})
    return {"items": names}
