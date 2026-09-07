# Screenshots

The main [`README.md`](../../README.md) references these image files. Add PNGs
here with these exact names:

| File | Page | Notes |
|---|---|---|
| `dashboard.png` | Dashboard (top) | Filled ring gauges, attention nudges, budget bar |
| `money-health.png` | Dashboard (mid) | Best-value-protein + Insights + Savings chart |
| `transactions.png` | Transactions | Summary strip + categorised log |
| `food-log.png` | Food Log | Summary strip + meals by day |
| `forecast.png` | Forecast | Calibrated-TDEE card + projection charts |
| `pantry.png` | Pantry | Summary strip + expiring-soon + stock |

## Regenerating the demo dataset

Screenshots use generated demo data (no real personal data). To reproduce:

```bash
# 1. Stop the app so the DB file is free, then back it up
#    (VACUUM INTO gives a clean single-file snapshot)
# 2. Seed ~6 months of realistic demo data:
PYTHONPATH=. python scripts/seed_demo.py
# 3. Start the app, take the screenshots
# 4. Restore your real DB by copying the snapshot back over data/app.db
#    and deleting data/app.db-wal / data/app.db-shm
```

`scripts/seed_demo.py` wipes operational rows first (keeps categories and the
singleton profile/goals), so only run it against a database you've backed up.
