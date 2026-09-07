"""Seed ~6 months of realistic demo data across every Balance feature.

Run from the project root:  python scripts/seed_demo.py
Wipes existing operational rows first (keeps Categories + the singleton
Profile/Goals rows), then regenerates a full 6-month dataset.
"""
import os
import random
import sys
from calendar import monthrange
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import (  # noqa: E402
    Category, Transaction, Income, FoodLog, WaterLog, WeightLog,
    UserProfile, BudgetTarget, PantryItem, Subscription, PriceObservation,
)
from backend.timeutil import utcnow  # noqa: E402

random.seed(42)
today = date.today()
start = today - timedelta(days=182)

with Session(engine) as s:
    cats = {c.name: c.id for c in s.exec(select(Category)).all()}
cid = cats.get

def d(days_ago):
    return today - timedelta(days=days_ago)

with Session(engine) as s:
    for M in (Transaction, Income, FoodLog, WaterLog, WeightLog,
              BudgetTarget, PantryItem, Subscription, PriceObservation):
        for r in s.exec(select(M)).all():
            s.delete(r)
    s.commit()

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
        (1, 950.0, "Landlord Ltd", "Bills & Utilities", "Bank Transfer"),
        (15, round(random.uniform(105, 140), 2), "British Gas", "Bills & Utilities", "Bank Transfer"),
        (3, 33.0, "PureGym", "Health & Fitness", "Bank Transfer"),
    ]:
        day = date(y, m, min(dd, last))
        if start <= day <= today:
            tx.append((day, amt, merch, cat, pay, ""))
    m2 = m + 1
    cur = date(y + (m2 > 12), 1 if m2 > 12 else m2, 1)

day = start
while day <= today:
    wd = day.weekday()
    if wd in (1, 4, 6) and random.random() < 0.85:
        tx.append((day, round(random.uniform(22, 68), 2), random.choice(GROCERS), "Groceries", "Card", random.choice(TAGS)))
    if wd < 5 and random.random() < 0.55:
        tx.append((day, round(random.uniform(2.5, 6.5), 2), random.choice(COFFEE), "Eating Out", random.choice(["Card", "Card", "Cash"]), random.choice(TAGS)))
    if wd in (4, 5) and random.random() < 0.5:
        tx.append((day, round(random.uniform(16, 58), 2), random.choice(DINING), "Eating Out", "Card", random.choice(["With friends", "With family", "Alone"])))
    if random.random() < 0.10:
        tx.append((day, round(random.uniform(48, 72), 2), random.choice(FUEL), "Transport", "Card", ""))
    if wd < 5 and random.random() < 0.15:
        tx.append((day, round(random.uniform(2.4, 18), 2), random.choice(TRANSPORT), "Transport", "Card", "Work"))
    if random.random() < 0.06:
        cat, merch, lo, hi = random.choice([
            ("Entertainment", "Waterstones", 8, 22), ("Entertainment", "Steam", 5, 40),
            ("Shopping", "IKEA", 10, 60), ("Health & Fitness", "Boots", 4, 25),
            ("Shopping", "Card Factory", 5, 45), ("Entertainment", "Odeon", 9, 30)])
        tx.append((day, round(random.uniform(lo, hi), 2), merch, cat, "Card", random.choice(TAGS)))
    day += timedelta(days=1)

with Session(engine) as s:
    for dt, amt, merch, cat, pay, tag in tx:
        s.add(Transaction(date=dt, amount=amt, merchant=merch, category_id=cid(cat), payment_method=pay, tag=tag or None))
    s.commit()

inc = []
cur = date(start.year, start.month, 1)
while cur <= today:
    y, m = cur.year, cur.month
    last = monthrange(y, m)[1]
    day = date(y, m, min(28, last))
    if start <= day <= today:
        inc.append((day, round(random.uniform(2600, 2720), 2), "Salary", "Acme Corp"))
    m2 = m + 1
    cur = date(y + (m2 > 12), 1 if m2 > 12 else m2, 1)
for _ in range(8):
    src, payer, lo, hi = random.choice([
        ("Freelance", "Side client", 120, 420), ("Gift", "Family", 20, 80),
        ("Refund", "Amazon", 8, 45), ("Interest", "Savings", 3, 14)])
    inc.append((d(random.randint(0, 182)), round(random.uniform(lo, hi), 2), src, payer))
with Session(engine) as s:
    for dt, amt, src, payer in inc:
        s.add(Income(date=dt, amount=amt, source=src, payer=payer))
    s.commit()

MEALS = {
    "breakfast": [("Porridge with banana", 320, 10, 55, 6, 5, 1.5, 90, 0),
                  ("Greek yogurt & granola", 360, 18, 42, 12, 8, 4, 80, 0),
                  ("Scrambled eggs on toast", 400, 22, 30, 20, 1, 6, 620, 0)],
    "lunch": [("Chicken salad wrap", 480, 32, 45, 18, 2, 4, 780, 0),
              ("Tuna pasta", 520, 30, 62, 14, 3, 3, 540, 0),
              ("Sushi box", 430, 20, 65, 8, 6, 1, 700, 0)],
    "dinner": [("Salmon, rice & broccoli", 650, 42, 60, 22, 0, 4.5, 420, 0),
               ("Spaghetti bolognese", 700, 34, 78, 24, 6, 9, 680, 0),
               ("Chicken curry & rice", 720, 40, 82, 22, 8, 7, 950, 0)],
    "snack": [("Protein bar", 210, 20, 22, 7, 12, 3, 120, 0),
              ("Apple", 80, 0, 21, 0, 0, 0, 1, 0),
              ("Glass of red wine", 125, 0, 4, 0, 1, 0, 5, 0)],
}
with Session(engine) as s:
    for da in range(60):
        dt = d(da)
        for meal in ("breakfast", "lunch", "dinner"):
            n, cal, p, c, f, asug, sat, sod, caf = random.choice(MEALS[meal])
            s.add(FoodLog(date=dt, meal_type=meal, food_name=n, quantity_g=random.choice([120, 150, 180, 200]),
                          calories=cal, protein_g=p, carbs_g=c, fat_g=f, sugar_g=asug + random.uniform(0, 6),
                          fiber_g=random.uniform(1, 6), sodium_mg=sod, saturated_fat_g=sat, added_sugar_g=asug,
                          caffeine_mg=caf, alcohol_g=0))
        if random.random() < 0.6:
            n, cal, p, c, f, asug, sat, sod, caf = random.choice(MEALS["snack"])
            s.add(FoodLog(date=dt, meal_type="snack", food_name=n, quantity_g=100, calories=cal, protein_g=p,
                          carbs_g=c, fat_g=f, added_sugar_g=asug, saturated_fat_g=sat, sodium_mg=sod,
                          caffeine_mg=caf, alcohol_g=14 if "wine" in n.lower() else 0))
    s.commit()

with Session(engine) as s:
    for da in range(12):
        for amt in random.sample([200, 330, 500, 500, 750], k=random.randint(3, 5)):
            s.add(WaterLog(date=d(da), amount_ml=amt))
    w, dt = 84.2, start
    while dt <= today:
        s.add(WeightLog(date=dt, weight_kg=round(w + random.uniform(-0.3, 0.3), 1)))
        w -= random.uniform(0.05, 0.2)
        dt += timedelta(days=7)
    p = s.exec(select(UserProfile)).first() or UserProfile()
    p.date_of_birth, p.height_cm, p.sex, p.activity_level = date(1992, 4, 15), 178, "male", "active"
    s.add(p)
    s.add(BudgetTarget(category_id=None, monthly_amount=1650.0))
    s.add(BudgetTarget(category_id=cid("Groceries"), monthly_amount=260.0))
    s.add(BudgetTarget(category_id=cid("Eating Out"), monthly_amount=150.0))
    s.commit()

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
                     expiration_date=d(2), price=1.30, status="expired", resolved_at=utcnow()))
    s.add(PantryItem(name="Lettuce", location="fridge", macro_group="produce", quantity=1, unit="unit",
                     expiration_date=d(1), price=0.85, status="thrown_away", resolved_at=utcnow()))
    s.add(Subscription(name="Netflix", amount=15.99, billing_cycle="monthly", next_payment_date=today + timedelta(days=12), category_id=cid("Entertainment"), payments_made=0))
    s.add(Subscription(name="Spotify", amount=11.99, billing_cycle="monthly", next_payment_date=today + timedelta(days=20), category_id=cid("Entertainment"), payments_made=0))
    s.add(Subscription(name="Amazon Prime", amount=95.0, billing_cycle="yearly", next_payment_date=today + timedelta(days=200), category_id=cid("Subscriptions"), payments_made=0))
    s.add(Subscription(name="Sofa installments", amount=45.0, billing_cycle="monthly", next_payment_date=today + timedelta(days=8), category_id=cid("Shopping"), total_payments=12, payments_made=5))
    for name, base, drift in [("Milk 2L", 1.50, 0.04), ("Olive Oil 1L", 5.10, 0.22), ("Coffee beans 1kg", 12.5, 0.35)]:
        pr, dt = base, start
        while dt <= today:
            s.add(PriceObservation(item_name=name, price=round(pr, 2), date=dt, store=random.choice(["Tesco", "Sainsbury's", "Aldi"])))
            pr += random.uniform(0, drift)
            dt += timedelta(days=random.randint(18, 32))
    s.commit()

with Session(engine) as s:
    print("6-month demo data seeded:")
    for lbl, M in [("transactions", Transaction), ("income", Income), ("food log", FoodLog),
                   ("water log", WaterLog), ("weight log", WeightLog), ("pantry", PantryItem),
                   ("subscriptions", Subscription), ("price points", PriceObservation), ("budgets", BudgetTarget)]:
        print(f"  {lbl:14} {len(s.exec(select(M)).all())}")
