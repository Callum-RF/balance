"""Small time helpers."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a *naive* datetime.

    A non-deprecated drop-in for the old ``datetime.utcnow()``: it keeps the
    same naive-UTC representation the database and the rest of the app already
    use, while avoiding the ``DeprecationWarning`` on modern Python.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
