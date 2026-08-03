"""Net-worth computation and daily snapshots.

Assets minus liabilities across all accounts, plus a once-per-day snapshot so a
net-worth trend can be charted over time. Snapshot functions take a session so
they can run inside a page's existing transaction.
"""
from datetime import date

from sqlmodel import Session, select

from backend.models import Account, NetWorthSnapshot

ASSET_TYPES = {"current", "savings", "cash", "investment"}
LIABILITY_TYPES = {"credit", "loan"}

TYPE_LABELS = {
    "current": "Current", "savings": "Savings", "cash": "Cash",
    "investment": "Investment", "credit": "Credit card", "loan": "Loan",
}


def compute_net_worth(session: Session) -> dict:
    accounts = session.exec(select(Account)).all()
    assets = sum(a.balance or 0 for a in accounts if a.type in ASSET_TYPES)
    liabilities = sum(a.balance or 0 for a in accounts if a.type in LIABILITY_TYPES)
    return {"assets": assets, "liabilities": liabilities, "net_worth": assets - liabilities}


def snapshot_if_due(session: Session, today: date = None) -> dict:
    """Record (or refresh) today's net-worth snapshot -- one row per day, so the
    trend gets a daily point without piling up duplicates."""
    today = today or date.today()
    nw = compute_net_worth(session)
    existing = session.exec(select(NetWorthSnapshot).where(NetWorthSnapshot.date == today)).first()
    if existing:
        existing.net_worth = nw["net_worth"]
        existing.assets = nw["assets"]
        existing.liabilities = nw["liabilities"]
        session.add(existing)
    else:
        session.add(NetWorthSnapshot(date=today, net_worth=nw["net_worth"],
                                     assets=nw["assets"], liabilities=nw["liabilities"]))
    session.commit()
    return nw
