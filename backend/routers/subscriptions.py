from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import Subscription, SubscriptionCreate, SubscriptionRead, SubscriptionUpdate

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


@router.get("/", response_model=List[SubscriptionRead])
def list_subscriptions(active_only: bool = False, session: Session = Depends(get_session)):
    query = select(Subscription)
    if active_only:
        query = query.where(Subscription.active == True)  # noqa: E712
    return session.exec(query.order_by(Subscription.name)).all()


@router.post("/", response_model=SubscriptionRead)
def create_subscription(sub: SubscriptionCreate, session: Session = Depends(get_session)):
    db_sub = Subscription.model_validate(sub)
    session.add(db_sub)
    session.commit()
    session.refresh(db_sub)
    return db_sub


@router.patch("/{sub_id}", response_model=SubscriptionRead)
def update_subscription(sub_id: int, update: SubscriptionUpdate, session: Session = Depends(get_session)):
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(sub, key, value)
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


@router.delete("/{sub_id}")
def delete_subscription(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    session.delete(sub)
    session.commit()
    return {"ok": True}


@router.get("/monthly-total")
def monthly_total(session: Session = Depends(get_session)):
    subs = session.exec(select(Subscription).where(Subscription.active == True)).all()  # noqa: E712
    total = sum(s.amount if s.billing_cycle == "monthly" else s.amount / 12 for s in subs)
    return {"monthly_total": round(total, 2), "active_count": len(subs)}
