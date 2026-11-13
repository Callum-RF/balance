"""Where Balance lives on the shared Ensemble address.

Every Ensemble app sits under a path of one address (https://<host>/balance/)
so the installed Ensemble app contains them all: a separate port is a separate
site to a phone, which is what put Chrome's address bar over each app.

Set BALANCE_PREFIX="" to serve at the root of its own address instead.
"""
import os

PREFIX = os.environ.get("BALANCE_PREFIX", "/balance").rstrip("/")
