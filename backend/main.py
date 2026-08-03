from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import create_db_and_tables
from backend.backup import start_scheduler
from backend.recurring import start_scheduler as start_recurring_scheduler
from backend.routers import (
    categories, transactions, food_log, stats,
    profile, water, budget, pantry, subscriptions, prices, reference, forecast, income,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    start_scheduler()             # background daily backups of app.db
    start_recurring_scheduler()   # background auto-posting of scheduled transactions
    yield


app = FastAPI(title="Balance", lifespan=lifespan)

app.include_router(categories.router)
app.include_router(transactions.router)
app.include_router(food_log.router)
app.include_router(stats.router)
app.include_router(profile.router)
app.include_router(water.router)
app.include_router(budget.router)
app.include_router(pantry.router)
app.include_router(subscriptions.router)
app.include_router(prices.router)
app.include_router(reference.router)
app.include_router(forecast.router)
app.include_router(income.router)


@app.get("/api/status")
def api_status():
    return {"status": "ok", "message": "Balance API"}
# (WAL journaling, startup integrity check, and background backups are wired in
#  via backend.database and backend.backup, initialised in lifespan above.)
