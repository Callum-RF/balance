"""Feature-module registry — the single source of truth for optional app areas,
shared by the frontend (nav + Settings toggles) and the DB backfill in
`database.py`.

`default_on` is the **lean shipped default** for a *fresh* install: optional
areas ship OFF so a new user lands on the focused money x health core
(dashboard + transactions + food log) rather than 17 tabs. Existing installs are
backfilled to all-on on upgrade (see `_backfill_modules_defaults`) so nobody
loses a section they were already using.
"""

# key: (label, tier, default_on)
MODULES = {
    "income":        ("Income",               "money",  False),
    "networth":      ("Accounts & Net Worth", "money",  False),
    "subscriptions": ("Subscriptions",        "money",  False),
    "scheduled":     ("Scheduled",            "money",  False),
    "prices":        ("Prices",               "money",  False),
    "forecast":      ("Forecast",             "money",  False),
    "savings":       ("Savings Goals",        "money",  False),
    "recipes":       ("Recipes",              "health", False),
    "pantry":        ("Pantry",               "health", False),
    "shopping":      ("Shopping",             "health", False),
    "import":        ("Import Statement",     "power",  False),
    "reports":       ("Monthly Report",       "power",  False),
}

# Ordered (tier_key, tier_label) for grouping the Settings > Modules toggles.
MODULE_TIERS = [("money", "Money"), ("health", "Health"), ("power", "Power / Advanced")]

# Marker written into AppSettings.modules_json once the lean-default migration
# has been applied to an install, so the one-time backfill of existing installs
# to all-on runs exactly once (and a fresh install is seeded already stamped).
MODULES_SENTINEL = "_lean_v2"
