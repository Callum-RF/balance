# Screenshots

The main [`README.md`](../../README.md) references these image files.
`scripts/capture_screenshots.py` regenerates all of them (dark theme, 2x).

| File | Page | Shows |
|---|---|---|
| `dashboard.png` | Home | Today (spend, macro rings, water), Worth knowing, This month, Money & food |
| `money-health.png` | Home, Money & food card | Food spend vs calories, eating out vs at home, best-value protein |
| `transactions.png` | Transactions | Figures, the log by day, the summary beside it |
| `food-log.png` | Food Log | Today by meal against targets, earlier days, nutrition summary |
| `forecast.png` | Forecast | Calibrated maintenance, weight and spending projections |
| `pantry.png` | Pantry | Figures, use-these-first, stock by location |

## Regenerating them

They're public, so they only ever show generated demo data. Seed it into a
throwaway database and serve that on port 8001 -- never point this at your real
`data/app.db` (`scripts/seed_demo.py` wipes the tables it fills):

```bash
# a separate database, no backups, its own session storage, its own port
set BALANCE_DB=%TEMP%alance-demo.db
set BALANCE_NO_BACKUP=1
set NICEGUI_STORAGE_PATH=%TEMP%alance-demo-storage
python scripts/seed_demo.py
set BALANCE_PORT=8001
python run.py
```

Turn on every page in the demo's Settings (Pages → All on) and pick the Dark
theme, then in another terminal from the project root:

```bash
python scripts/capture_screenshots.py      # BALANCE_URL defaults to :8001
```
