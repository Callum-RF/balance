"""Seed 12 months of realistic demo data across EVERY Balance feature.

Run from the project root:  python scripts/seed_year.py

Wipes existing operational rows first (keeps Categories, AppSettings, and the
singleton Profile/Goals rows), then regenerates a full 12-month dataset --
including the newer features: scheduled transactions, recipes, shopping list,
savings goals, accounts and net-worth history.
"""
import os
import random
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import (  # noqa: E402
    Category, Transaction, Income, FoodLog, WaterLog, WeightLog,
    UserProfile, BudgetTarget, PantryItem, Subscription, PriceObservation,
    ScheduledTransaction, Recipe, RecipeItem, ShoppingListItem, SavingsGoal,
    Account, NetWorthSnapshot,
)

random.seed(7)
today = date.today()
start = today - timedelta(days=365)


def d(days_ago):
    return today - timedelta(days=days_ago)


def add_months(dt, n):
    m = dt.month - 1 + n
    y = dt.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(dt.day, monthrange(y, m)[1]))


with Session(engine) as s:
    cats = {c.name: c.id for c in s.exec(select(Category)).all()}
cid = cats.get

# --- wipe operational tables (keep Category / AppSettings / Profile / Goals) ---
with Session(engine) as s:
    for M in (Transaction, Income, FoodLog, WaterLog, WeightLog, BudgetTarget,
              PantryItem, Subscription, PriceObservation, ScheduledTransaction,
              RecipeItem, Recipe, ShoppingListItem, SavingsGoal, Account, NetWorthSnapshot):
        for r in s.exec(select(M)).all():
            s.delete(r)
    s.commit()

# ---------------------------------------------------------------- transactions
TAGS = ["", "", "", "Alone", "With friends", "With family", "Work"]
GROCERS = ["Tesco", "Sainsbury's", "Aldi", "M&S Food", "Lidl"]
COFFEE = ["Costa Coffee", "Pret A Manger", "Greggs", "Starbucks"]
DINING = ["Nando's", "Wagamama", "Deliveroo", "Pizza Express", "Franco Manca"]
FUEL = ["Shell", "BP", "Esso"]
TRANSPORT = ["TFL", "Uber", "Trainline"]

tx = []
cur = date(start.year, start.month, 1)
while cur <= today:
    y, m = cur.year, cur.month
    last = monthrange(y, m)[1]
    for dd, amt, merch, cat, pay in [
        (1, 975.0, "Landlord Ltd", "Rent/Mortgage", "Bank Transfer"),
        (15, round(random.uniform(105, 145), 2), "British Gas", "Utilities", "Bank Transfer"),
        (3, 33.0, "PureGym", "Fitness", "Bank Transfer"),
    ]:
        day = date(y, m, min(dd, last))
        if start <= day <= today:
            tx.append((day, amt, merch, cat, pay, ""))
    cur = add_months(date(y, m, 1), 1)

day = start
while day <= today:
    wd = day.weekday()
    if wd in (1, 4, 6) and random.random() < 0.85:
        tx.append((day, round(random.uniform(22, 68), 2), random.choice(GROCERS), "Groceries", "Card", random.choice(TAGS)))
    if wd < 5 and random.random() < 0.55:
        tx.append((day, round(random.uniform(2.5, 6.5), 2), random.choice(COFFEE), "Coffee/Snacks", random.choice(["Card", "Card", "Cash"]), random.choice(TAGS)))
    if wd in (4, 5) and random.random() < 0.5:
        tx.append((day, round(random.uniform(16, 58), 2), random.choice(DINING), "Dining Out", "Card", random.choice(["With friends", "With family", "Alone"])))
    if random.random() < 0.10:
        tx.append((day, round(random.uniform(48, 74), 2), random.choice(FUEL), "Fuel", "Card", ""))
    if wd < 5 and random.random() < 0.15:
        tx.append((day, round(random.uniform(2.4, 18), 2), random.choice(TRANSPORT), "Public Transport", "Card", "Work"))
    if random.random() < 0.06:
        cat, merch, lo, hi = random.choice([
            ("Books", "Waterstones", 8, 22), ("Games", "Steam", 5, 40),
            ("Household", "IKEA", 10, 60), ("Pharmacy", "Boots", 4, 25),
            ("Gifts", "Card Factory", 5, 45), ("Hobbies", "Odeon", 9, 30)])
        tx.append((day, round(random.uniform(lo, hi), 2), merch, cat, "Card", random.choice(TAGS)))
    day += timedelta(days=1)

with Session(engine) as s:
    for dt, amt, merch, cat, pay, tag in tx:
        s.add(Transaction(date=dt, amount=amt, merchant=merch, category_id=cid(cat), payment_method=pay, tag=tag or None))
    s.commit()

# ---------------------------------------------------------------------- income
inc = []
cur = date(start.year, start.month, 1)
while cur <= today:
    y, m = cur.year, cur.month
    last = monthrange(y, m)[1]
    day = date(y, m, min(25, last))
    if start <= day <= today:
        inc.append((day, round(random.uniform(2600, 2720), 2), "Salary", "Acme Corp"))
    cur = add_months(date(y, m, 1), 1)
for _ in range(16):
    src, payer, lo, hi = random.choice([
        ("Freelance", "Side client", 120, 420), ("Gift", "Family", 20, 80),
        ("Refund", "Amazon", 8, 45), ("Interest", "Savings", 3, 18)])
    inc.append((d(random.randint(0, 364)), round(random.uniform(lo, hi), 2), src, payer))
with Session(engine) as s:
    for dt, amt, src, payer in inc:
        s.add(Income(date=dt, amount=amt, source=src, payer=payer))
    s.commit()

# -------------------------------------------------------------------- food log
MEALS = {
    "breakfast": [("Porridge with banana", 320, 10, 55, 6, 5, 1.5, 90, 0),
                  ("Greek yogurt & granola", 360, 18, 42, 12, 8, 4, 80, 0),
                  ("Scrambled eggs on toast", 400, 22, 30, 20, 1, 6, 620, 0)],
    "lunch": [("Chicken salad wrap", 480, 32, 45, 18, 2, 4, 780, 0),
              ("Tuna pasta", 520, 30, 62, 14, 3, 3, 540, 0),
              ("Sushi box", 430, 20, 65, 8, 6, 1, 700, 0)],
    "dinner": [("Salmon, rice & broccoli", 620, 42, 60, 22, 0, 4.5, 420, 0),
               ("Spaghetti bolognese", 690, 34, 78, 24, 6, 9, 680, 0),
               ("Chicken curry & rice", 700, 40, 82, 22, 8, 7, 950, 0)],
    "snack": [("Protein bar", 210, 20, 22, 7, 12, 3, 120, 0),
              ("Apple", 80, 0, 21, 0, 0, 0, 1, 0),
              ("Glass of red wine", 125, 0, 4, 0, 1, 0, 5, 0)],
}
with Session(engine) as s:
    for da in range(365):
        dt = d(da)
        for meal in ("breakfast", "lunch", "dinner"):
            n, cal, p, c, f, asug, sat, sod, caf = random.choice(MEALS[meal])
            s.add(FoodLog(date=dt, meal_type=meal, food_name=n, quantity_g=random.choice([120, 150, 180, 200]),
                          calories=cal, protein_g=p, carbs_g=c, fat_g=f, sugar_g=asug + random.uniform(0, 6),
                          fiber_g=random.uniform(1, 6), sodium_mg=sod, saturated_fat_g=sat, added_sugar_g=asug,
                          caffeine_mg=caf, alcohol_g=0))
        if random.random() < 0.5:
            n, cal, p, c, f, asug, sat, sod, caf = random.choice(MEALS["snack"])
            s.add(FoodLog(date=dt, meal_type="snack", food_name=n, quantity_g=100, calories=cal, protein_g=p,
                          carbs_g=c, fat_g=f, added_sugar_g=asug, saturated_fat_g=sat, sodium_mg=sod,
                          caffeine_mg=caf, alcohol_g=14 if "wine" in n.lower() else 0))
    s.commit()

# --------------------------------------------------- water, weight, profile, budgets
with Session(engine) as s:
    for da in range(120):  # daily water for the last ~4 months (drives the streak)
        for amt in random.sample([200, 330, 500, 500, 750], k=random.randint(4, 5)):
            s.add(WaterLog(date=d(da), amount_ml=amt))
    w, dt = 84.0, start
    while dt <= today:  # weekly weigh-ins trending gently down over the year
        s.add(WeightLog(date=dt, weight_kg=round(w + random.uniform(-0.3, 0.3), 1)))
        w -= random.uniform(0.04, 0.16)
        dt += timedelta(days=7)
    p = s.exec(select(UserProfile)).first() or UserProfile()
    p.date_of_birth, p.height_cm, p.sex, p.activity_level = date(1992, 4, 15), 178, "male", "active"
    s.add(p)
    s.add(BudgetTarget(category_id=None, monthly_amount=1650.0))
    s.add(BudgetTarget(category_id=cid("Groceries"), monthly_amount=260.0))
    s.add(BudgetTarget(category_id=cid("Dining Out"), monthly_amount=150.0))
    s.commit()

# ------------------------------------------------- pantry, subscriptions, prices
with Session(engine) as s:
    for name, loc, grp, qty, unit, exp, price, cal, prot in [
        ("Milk 2L", "fridge", "dairy", 1, "unit", 3, 1.65, 1400, 68),
        ("Chicken breast", "freezer", "protein", 600, "g", 45, 4.50, 990, 186),
        ("Spinach", "fridge", "produce", 1, "unit", 1, 1.20, 70, 6),
        ("Rice 1kg", "pantry", "carbs", 1, "kg", 210, 2.10, 3600, 74),
        ("Yoghurt multipack", "fridge", "dairy", 6, "unit", 6, 3.00, 900, 60),
        ("Frozen peas", "freezer", "produce", 500, "g", 180, 1.10, 405, 27),
        ("Eggs (12)", "fridge", "protein", 12, "unit", 14, 2.80, 900, 78)]:
        s.add(PantryItem(name=name, location=loc, macro_group=grp, quantity=qty, unit=unit,
                         purchase_date=d(random.randint(1, 10)), expiration_date=today + timedelta(days=exp),
                         price=price, calories=cal, protein_g=prot, status="active"))
    s.add(PantryItem(name="Bread loaf", location="pantry", macro_group="carbs", quantity=1, unit="unit",
                     expiration_date=d(2), price=1.30, status="expired", resolved_at=datetime.utcnow()))
    s.add(PantryItem(name="Lettuce", location="fridge", macro_group="produce", quantity=1, unit="unit",
                     expiration_date=d(1), price=0.85, status="thrown_away", resolved_at=datetime.utcnow()))
    s.add(Subscription(name="Netflix", amount=15.99, billing_cycle="monthly", next_payment_date=today + timedelta(days=12), category_id=cid("Streaming"), payments_made=0))
    s.add(Subscription(name="Spotify", amount=11.99, billing_cycle="monthly", next_payment_date=today + timedelta(days=20), category_id=cid("Streaming"), payments_made=0))
    s.add(Subscription(name="Amazon Prime", amount=95.0, billing_cycle="yearly", next_payment_date=today + timedelta(days=200), category_id=cid("Subscriptions"), payments_made=0))
    s.add(Subscription(name="Sofa installments", amount=45.0, billing_cycle="monthly", next_payment_date=today + timedelta(days=8), category_id=cid("Household"), total_payments=12, payments_made=5))
    for name, base, drift in [("Milk 2L", 1.45, 0.03), ("Olive Oil 1L", 4.80, 0.16), ("Coffee beans 1kg", 11.9, 0.28)]:
        pr, dt = base, start
        while dt <= today:
            s.add(PriceObservation(item_name=name, price=round(pr, 2), date=dt, store=random.choice(["Tesco", "Sainsbury's", "Aldi"])))
            pr += random.uniform(0, drift)
            dt += timedelta(days=random.randint(18, 32))
    s.commit()

# --------------------------------------------- scheduled / recurring transactions
with Session(engine) as s:
    s.add(ScheduledTransaction(kind="income", amount=2680.0, description="Acme Corp", source="Salary",
                               cadence="monthly", next_date=add_months(today.replace(day=25), 0 if today.day < 25 else 1),
                               auto_post=True))
    s.add(ScheduledTransaction(kind="expense", amount=975.0, description="Landlord Ltd", category_id=cid("Rent/Mortgage"),
                               cadence="monthly", next_date=add_months(today.replace(day=1), 1), auto_post=True))
    s.add(ScheduledTransaction(kind="expense", amount=33.0, description="PureGym", category_id=cid("Fitness"),
                               cadence="monthly", next_date=today + timedelta(days=6), auto_post=True))
    s.add(ScheduledTransaction(kind="expense", amount=120.0, description="Electricity (variable)", category_id=cid("Utilities"),
                               cadence="monthly", next_date=today, auto_post=False))  # shows in "Due now"
    s.commit()

# ------------------------------------------------------------------- recipes
with Session(engine) as s:
    def recipe(name, servings, items):
        r = Recipe(name=name, servings=servings)
        s.add(r); s.commit(); s.refresh(r)
        for fn, g, cal, p, c, f in items:
            s.add(RecipeItem(recipe_id=r.id, food_name=fn, quantity_g=g, calories=cal, protein_g=p, carbs_g=c, fat_g=f))
    recipe("Spaghetti Bolognese", 4, [
        ("Spaghetti", 400, 1480, 52, 300, 6), ("Beef mince", 500, 1250, 100, 0, 90),
        ("Tomato sauce", 400, 140, 6, 28, 1), ("Onion", 100, 40, 1, 9, 0)])
    recipe("Chicken Stir Fry", 2, [
        ("Chicken breast", 300, 495, 93, 0, 11), ("Mixed veg", 300, 120, 6, 24, 1),
        ("Rice", 200, 720, 15, 160, 2), ("Soy sauce", 30, 15, 2, 1, 0)])
    recipe("Overnight Oats", 1, [
        ("Oats", 60, 228, 8, 40, 4), ("Milk", 200, 96, 7, 10, 4),
        ("Banana", 120, 107, 1, 27, 0), ("Honey", 15, 46, 0, 12, 0)])
    s.commit()

# ---------------------------------------------------------------- shopping list
with Session(engine) as s:
    for name, qty, loc in [("Milk 2L", "1", "fridge"), ("Eggs", "a dozen", "fridge"),
                           ("Coffee beans 1kg", "1", "pantry"), ("Chicken breast", "1kg", "freezer")]:
        s.add(ShoppingListItem(name=name, quantity_note=qty, location=loc, source="manual"))
    s.commit()

# ---------------------------------------------------------------- savings goals
with Session(engine) as s:
    s.add(SavingsGoal(name="Emergency fund", target_amount=5000, saved_amount=3200, target_date=add_months(today, 6)))
    s.add(SavingsGoal(name="Holiday 2027", target_amount=2000, saved_amount=850, target_date=add_months(today, 4)))
    s.add(SavingsGoal(name="New laptop", target_amount=1500, saved_amount=1500, target_date=add_months(today, -1)))
    s.commit()

# --------------------------------------------- accounts + net-worth history
with Session(engine) as s:
    accounts = [("Monzo Current", "current", 2400.0), ("Marcus Savings", "savings", 8500.0),
                ("Cash", "cash", 120.0), ("Amex", "credit", 640.0)]
    for name, typ, bal in accounts:
        s.add(Account(name=name, type=typ, balance=bal))
    final_net = 2400 + 8500 + 120 - 640  # 10380
    dt = date(start.year, start.month, 1)
    months = []
    while dt <= today:
        months.append(dt)
        dt = add_months(dt, 1)
    n = len(months)
    for i, mdt in enumerate(months):
        frac = i / max(n - 1, 1)
        net = 6000 + (final_net - 6000) * frac + random.uniform(-180, 180)
        s.add(NetWorthSnapshot(date=mdt, net_worth=round(net, 2), assets=round(net + 640, 2), liabilities=640.0))
    s.commit()

# ------------------------------------------------------------------- summary
with Session(engine) as s:
    print("12-month demo data seeded:")
    for lbl, M in [("transactions", Transaction), ("income", Income), ("food log", FoodLog),
                   ("water log", WaterLog), ("weight log", WeightLog), ("pantry", PantryItem),
                   ("subscriptions", Subscription), ("price points", PriceObservation),
                   ("budgets", BudgetTarget), ("scheduled", ScheduledTransaction),
                   ("recipes", Recipe), ("recipe items", RecipeItem), ("shopping", ShoppingListItem),
                   ("savings goals", SavingsGoal), ("accounts", Account), ("networth pts", NetWorthSnapshot)]:
        print(f"  {lbl:14} {len(s.exec(select(M)).all())}")
