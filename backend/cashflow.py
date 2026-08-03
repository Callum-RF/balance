"""Forward cashflow: what known money movements are coming up.

Expands active Subscriptions and ScheduledTransactions across a forward window
so the app can answer "what's due soon, and can I cover it?" -- reusing the
recurrence math from backend.recurring. Read-only: it projects, never writes.
"""
from datetime import date, timedelta

from sqlmodel import Session, select

from backend.database import engine
from backend.models import ScheduledTransaction, Subscription
from backend.recurring import advance

_GUARD = 500  # cap recurrence expansion so a bad date can't loop forever


def upcoming_events(days: int = 30, today: date = None):
    """List known money movements in [today, today+days], soonest first.
    Each event: {date, label, amount, direction: 'in'|'out', source}."""
    today = today or date.today()
    end = today + timedelta(days=days)
    events = []

    with Session(engine) as session:
        subs = session.exec(select(Subscription).where(Subscription.active == True)).all()  # noqa: E712
        sched = session.exec(select(ScheduledTransaction).where(ScheduledTransaction.active == True)).all()  # noqa: E712

    for sub in subs:
        d = sub.next_payment_date
        if not d:
            continue
        # skip installment plans that are already paid off
        if sub.total_payments is not None and sub.payments_made >= sub.total_payments:
            continue
        cadence = "yearly" if sub.billing_cycle == "yearly" else "monthly"
        guard = 0
        while d <= end and guard < _GUARD:
            if d >= today:
                events.append({"date": d, "label": sub.name, "amount": sub.amount,
                               "direction": "out", "source": "subscription"})
            d = advance(d, cadence)
            guard += 1

    for it in sched:
        d = it.next_date
        if not d:
            continue
        label = it.description or ("Income" if it.kind == "income" else "Expense")
        direction = "in" if it.kind == "income" else "out"
        guard = 0
        while d <= end and guard < _GUARD:
            if d >= today:
                events.append({"date": d, "label": label, "amount": it.amount,
                               "direction": direction, "source": "scheduled"})
            d = advance(d, it.cadence)
            guard += 1

    events.sort(key=lambda e: e["date"])
    return events


def cashflow_summary(days: int = 30, today: date = None):
    """Totals for the window: money in, money out, and net."""
    events = upcoming_events(days, today)
    money_out = sum(e["amount"] for e in events if e["direction"] == "out")
    money_in = sum(e["amount"] for e in events if e["direction"] == "in")
    return {"events": events, "out": money_out, "in": money_in, "net": money_in - money_out}
