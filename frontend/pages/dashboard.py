"""The dashboard page."""
from datetime import date, datetime, timedelta

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    BudgetTarget,
    Category,
    FoodLog,
    Income,
    NutrientGoals,
    PantryItem,
    Subscription,
    Transaction,
    WaterLog,
)
from backend.nutrient_info import CAFFEINE_LIKE_SUBSTANCES
from backend.routers.stats import NUTRIENT_FIELDS, period_bounds

from .. import theme as _theme
from ..common import (
    CUR,
    _period_total,
    format_date_header,
    friendly_range,
    module_enabled,
    open_add,
    previous_window,
    resolve_window,
    set_page_refresh,
)
from ..components import (
    badge,
    card_box,
    card_box_accent,
    empty_state,
    period_delta_badge,
    progress_row,
    ring_gauge,
    section_header,
    summary_strip,
    thin_meter,
)
from ..theme import (
    AMBER,
    BORDER,
    CHART_PALETTE,
    EMERALD,
    INDIGO,
    RED,
    SKY,
    SURFACE,
    SURFACE_2,
    TEXT_DIM,
    VIOLET,
    echart,
)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def dashboard():
    """The home page. Wrapped in a refreshable so adding something from the +
    sheet redraws it in place (see common.set_page_refresh)."""
    body = ui.refreshable(_dashboard_body)
    body()
    set_page_refresh(body.refresh)


def _dashboard_body():
    today = date.today()
    now = datetime.now()
    yesterday = today - timedelta(days=1)

    with Session(engine) as session:
        goals = session.exec(select(NutrientGoals)).first() or NutrientGoals()
        food_today = session.exec(select(FoodLog).where(FoodLog.date == today)).all()
        spend_today = sum(t.amount for t in session.exec(select(Transaction).where(Transaction.date == today)).all())
        y_food = session.exec(select(FoodLog).where(FoodLog.date == yesterday)).all()
        y_spend = sum(t.amount for t in session.exec(select(Transaction).where(Transaction.date == yesterday)).all())
        month_start, month_end = period_bounds("monthly", today)
        month_transactions = session.exec(
            select(Transaction).where(Transaction.date >= month_start, Transaction.date <= month_end)
        ).all()
        month_income = session.exec(
            select(Income).where(Income.date >= month_start, Income.date <= month_end)
        ).all()
        overall_budget = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711
        category_budgets = session.exec(select(BudgetTarget).where(BudgetTarget.category_id != None)).all()  # noqa: E711
        categories = {c.id: c.name for c in session.exec(select(Category)).all()}
        # "First run" = a genuinely fresh install (nothing logged yet). Drives the
        # welcome card; clears itself the moment anything is logged.
        first_run = (session.exec(select(Transaction)).first() is None
                     and session.exec(select(FoodLog)).first() is None)

    month_spend_by_category: dict = {}
    for t in month_transactions:
        month_spend_by_category[t.category_id] = month_spend_by_category.get(t.category_id, 0) + t.amount
    spent_this_month = sum(t.amount for t in month_transactions)
    income_this_month = sum(i.amount for i in month_income)
    net_this_month = income_this_month - spent_this_month
    income_module = module_enabled("income")
    days_left = max((month_end - today).days, 0)
    has_budget = bool(overall_budget and overall_budget.monthly_amount)
    budget_left = (overall_budget.monthly_amount - spent_this_month) if has_budget else 0

    # --- Greeting: a time-aware line, so there's a reason to open it at any hour ---
    t_cal = sum(f.calories or 0 for f in food_today)
    y_cal = sum(f.calories or 0 for f in y_food)
    protein_today = sum(f.protein_g or 0 for f in food_today)
    h = now.hour
    if 5 <= h < 12:
        greeting = "Good morning"
        focus = (f"Yesterday: {CUR}{y_spend:,.0f} spent · {y_cal:,.0f} kcal. Log breakfast to start the day."
                 if (y_spend or y_cal) else "A fresh day — log a meal or an expense to get going.")
    elif 12 <= h < 18:
        greeting = "Good afternoon"
        if goals.protein_g and protein_today < goals.protein_g:
            focus = f"{protein_today:,.0f}g protein so far — {goals.protein_g - protein_today:,.0f}g to go. Logged lunch?"
        elif goals.protein_g:
            focus = f"Protein goal already hit ({protein_today:,.0f}g) — nice. {CUR}{spend_today:,.0f} spent so far."
        else:
            focus = f"{CUR}{spend_today:,.0f} spent so far today."
    else:
        greeting = "Good evening"
        focus = f"Today: {CUR}{spend_today:,.0f} spent · {t_cal:,.0f} kcal. Round off dinner and tomorrow's plan."
    with ui.column().classes("gap-1"):
        ui.label(f"{today:%A} {today.day} {today:%B}").classes("b-eyebrow")
        ui.label(greeting).classes("b-title")
        ui.label(focus).classes("b-subtitle")

    if first_run:
        with card_box_accent().classes("w-full"):
            section_header("Welcome to Balance",
                           subtitle="What you spend and what it does to your body — in one place.")
            ui.label("Log one expense and one meal and this page comes alive: you'll see how your money and "
                     "your health line up. Targets start with sensible defaults you can change any time.").classes("text-sm")
            with ui.row().classes("gap-2 flex-wrap"):
                ui.button("Add your first expense", icon="add",
                          on_click=lambda: open_add("expense")).props("unelevated no-caps color=primary")
                ui.button("Log your first meal", icon="restaurant",
                          on_click=lambda: open_add("food")).props("unelevated no-caps color=primary")

    with ui.element("div").classes("b-dash-grid"):
        # ============ left: today ============
        with ui.column().classes("b-dash-col"):
            _today_card(today, goals, overall_budget, spent_this_month, days_left)

        # ============ right: what's worth knowing, the month, money x food ============
        with ui.column().classes("b-dash-col"):
            _worth_knowing(today, goals, food_today, protein_today, categories, category_budgets,
                           overall_budget, month_spend_by_category, spent_this_month, month_start, month_end,
                           days_left)
            with card_box().classes("w-full gap-2"):
                with section_header("This month", subtitle=today.strftime("%B %Y")):
                    ui.label(f"{days_left} day{'s' if days_left != 1 else ''} left" if days_left
                             else "Last day").classes("text-xs").style(f"color:{TEXT_DIM}")
                summary_strip([
                    ("Spent", f"{CUR}{spent_this_month:,.0f}", AMBER),
                    has_budget and ("Left in budget" if budget_left >= 0 else "Over budget",
                                    f"{CUR}{abs(budget_left):,.0f}", EMERALD if budget_left >= 0 else RED),
                    income_module and ("Net", f"{'+' if net_this_month >= 0 else '−'}{CUR}{abs(net_this_month):,.0f}",
                                       EMERALD if net_this_month >= 0 else RED),
                ], width_class="compact")
                if has_budget:
                    thin_meter(spent_this_month, overall_budget.monthly_amount,
                               RED if budget_left < 0 else (AMBER if spent_this_month >= 0.8 * overall_budget.monthly_amount
                                                            else EMERALD))
                    if category_budgets:
                        with ui.expansion("Budget by category").props("dense").classes("w-full"):
                            for cb in sorted(category_budgets, key=lambda b: categories.get(b.category_id, "")):
                                progress_row(categories.get(cb.category_id, "Uncategorized"),
                                             month_spend_by_category.get(cb.category_id, 0),
                                             cb.monthly_amount, f" {CUR}", is_limit=True)
            _money_and_food(today, categories)

    # --- streaks, as one line; and the way to the longer view ---
    from backend.streaks import compute_streaks
    live = [s for s in compute_streaks(today) if s["streak"] > 0]
    with ui.element("div").classes("b-dash-foot"):
        if live:
            with ui.element("div").classes("b-streakline"):
                ui.icon("local_fire_department").style(f"color:{AMBER}")
                phrase = {"water": "hitting water", "calories": "within calories", "budget": "under daily budget"}
                ui.label(" · ".join(f"{s['streak']} day{'s' if s['streak'] != 1 else ''} "
                                    f"{phrase.get(s['key'], s['label'].lower())}" for s in live))
        ui.space()
        for label, route in (("Spending trends", "/transactions"), ("Nutrition trends", "/food-log")):
            with ui.link(target=route).classes("b-trendlink"):
                ui.label(label)
                ui.icon("arrow_forward")


def _today_card(today, goals, overall_budget, spent_this_month, days_left):
    """Today, navigable day by day: what you've spent, your macros, anything
    over a limit, and water."""
    LIMIT_FIELDS = [
        ("Added sugar", "added_sugar_g", "sugar_limit_g", "g"),
        ("Saturated fat", "saturated_fat_g", "saturated_fat_limit_g", "g"),
        ("Trans fat", "trans_fat_g", "trans_fat_limit_g", "g"),
        ("Sodium", "sodium_mg", "sodium_limit_mg", "mg"),
        ("Alcohol", "alcohol_g", "alcohol_limit_g", "g"),
        ("Caffeine", "caffeine_mg", "caffeine_limit_mg", "mg"),
    ]
    view_state = {"date": today}
    today_card = card_box().classes("w-full")

    # What a day can take and stay on budget: the budget left, spread over the days left.
    pace = over_by = None
    if overall_budget and overall_budget.monthly_amount:
        left_before_today = overall_budget.monthly_amount - (spent_this_month - sum(t.amount for t in _tx_on(today)))
        if left_before_today > 0:
            pace = left_before_today / max(days_left + 1, 1)
        else:
            over_by = spent_this_month - overall_budget.monthly_amount

    def shift_day(delta):
        new_date = view_state["date"] + timedelta(days=delta)
        if new_date <= today:  # never into the future
            view_state["date"] = new_date
            render_today()

    def render_today():
        today_card.clear()
        sel = view_state["date"]
        is_today = sel == today
        with Session(engine) as session:
            foods = session.exec(select(FoodLog).where(FoodLog.date == sel)).all()
            waters = session.exec(select(WaterLog).where(WaterLog.date == sel)).all()
        spent = sum(t.amount for t in _tx_on(sel))
        n_tx = len(_tx_on(sel))

        cals = sum(f.calories or 0 for f in foods)
        protein = sum(f.protein_g or 0 for f in foods)
        carbs = sum(f.carbs_g or 0 for f in foods)
        fat = sum(f.fat_g or 0 for f in foods)
        limit_totals = {field: sum(getattr(f, field) or 0 for f in foods) for _, field, _, _ in LIMIT_FIELDS}
        water_ml = sum(w.amount_ml for w in waters)
        flagged = []
        for name, field, limit_key, unit in LIMIT_FIELDS:
            lim, cur = getattr(goals, limit_key), limit_totals[field]
            if lim and cur > lim:
                flagged.append((f"{name} {cur:,.0f}/{lim:,.0f}{unit}", RED))
            elif lim and cur / lim >= 0.8:
                flagged.append((f"{name} {cur:,.0f}/{lim:,.0f}{unit}", AMBER))

        with today_card:
            hdr = section_header(format_date_header(sel), subtitle=sel.strftime("%A, %d %B"))
            with hdr:
                # A fixed control group so nothing shifts as you page days.
                today_btn = ui.button("Today", on_click=lambda: (view_state.update(date=today), render_today())).props(
                    "flat dense no-caps").classes("text-xs")
                ui.button(icon="chevron_left", on_click=lambda: shift_day(-1)).props("flat round dense").tooltip("Previous day")
                nxt = ui.button(icon="chevron_right", on_click=lambda: shift_day(1)).props("flat round dense")
                if is_today:
                    today_btn.style("visibility:hidden")
                    nxt.props("disable")
                else:
                    nxt.tooltip("Next day")

            # Spent: tap through to the day's transactions.
            with ui.element("div").classes("b-nudge").on("click", lambda: ui.navigate.to("/transactions")):
                ui.icon("receipt_long").classes("text-lg").style(f"color:{AMBER}")
                with ui.column().classes("b-nudge-text gap-0"):
                    ui.label(f"{CUR}{spent:,.2f} spent" + (f" · {n_tx} transaction{'s' if n_tx != 1 else ''}" if n_tx else "")).classes(
                        "font-semibold")
                    if is_today and pace is not None:
                        ui.label(f"{CUR}{pace:,.0f} a day keeps you on budget"
                                 + (" — over for today" if spent > pace else "")).classes("text-xs").style(
                            f"color:{RED if spent > pace else TEXT_DIM}")
                    elif is_today and over_by is not None:
                        ui.label(f"This month is {CUR}{over_by:,.0f} over budget").classes("text-xs").style(
                            f"color:{RED}")
                with ui.element("div").classes("b-nudge-cta"):
                    ui.icon("chevron_right")

            with ui.grid().classes("w-full grid-cols-2 sm:grid-cols-4 gap-2 gap-y-4 mt-1 justify-items-center"):
                ring_gauge("Calories", cals, goals.calories, "kcal", INDIGO)
                ring_gauge("Protein", protein, goals.protein_g, "g", EMERALD)
                ring_gauge("Carbs", carbs, goals.carbs_g, "g", AMBER)
                ring_gauge("Fat", fat, goals.fat_g, "g", VIOLET)

            if flagged:
                with ui.row().classes("w-full gap-2 flex-wrap items-center"):
                    ui.label("Watch:").classes("text-xs").style(f"color:{TEXT_DIM}")
                    for text, color in flagged:
                        badge(text, color)
            with ui.expansion("All limits & caffeine-like substances").props("dense").classes("w-full"):
                for name, field, limit_key, unit in LIMIT_FIELDS:
                    progress_row(name, limit_totals[field], getattr(goals, limit_key), unit, is_limit=True, info_key=limit_key)
                ui.separator().classes("my-2")
                ui.label("Not tracked with a daily total (no standard serving data), but worth being mindful of "
                         "if you have them regularly:").classes("text-xs mb-1").style(f"color:{TEXT_DIM}")
                for sub in CAFFEINE_LIKE_SUBSTANCES:
                    with ui.row().classes("w-full gap-2 items-start py-1"):
                        ui.label(sub["name"]).classes("text-sm font-semibold w-24 shrink-0")
                        ui.label(sub["note"]).classes("text-xs").style(f"color:{TEXT_DIM}")

            # --- water: log for today, read-only for a past day ---
            with ui.row().classes("w-full items-center gap-2 no-wrap mt-1"):
                ui.icon("water_drop").classes("text-lg").style(f"color:{SKY}")
                ui.label("Water").classes("text-sm font-semibold")
                ui.label(f"{water_ml:,.0f} / {(goals.water_ml or 0):,.0f} ml").classes("text-xs ml-auto").style(f"color:{TEXT_DIM}")
            thin_meter(water_ml, goals.water_ml, SKY)
            if is_today:
                with ui.element("div").classes("b-water mt-1"):
                    for amount in [200, 330, 500, 750]:
                        with ui.element("div").classes("b-pill").on("click", lambda amt=amount: add_water(amt)):
                            ui.icon("water_drop")
                            ui.label(f"{amount} ml")
                    if waters:
                        ui.button("Undo", icon="undo", on_click=undo_water).props(
                            "flat dense no-caps color=grey").tooltip("Remove the last glass")

    def add_water(amount_ml):
        with Session(engine) as session:
            session.add(WaterLog(date=today, amount_ml=amount_ml))
            session.commit()
        render_today()

    def undo_water():
        with Session(engine) as session:
            last = session.exec(select(WaterLog).where(WaterLog.date == today).order_by(WaterLog.id.desc())).first()
            if last:
                session.delete(last)
                session.commit()
        render_today()

    render_today()


def _tx_on(day):
    with Session(engine) as session:
        return session.exec(select(Transaction).where(Transaction.date == day)).all()


def _worth_knowing(today, goals, food_today, protein_today, categories, category_budgets, overall_budget,
                   month_spend_by_category, spent_this_month, month_start, month_end, days_left):
    """One card for everything worth a look: what needs doing (budgets, meals,
    renewals) and what's changed since last month. Most pressing first."""
    items = []  # (rank, text, color, cta, route)  -- rank: 0 red, 1 amber, 2 the rest

    def add(text, color, cta=None, route=None):
        items.append((0 if color == RED else 1 if color == AMBER else 2, text, color, cta, route))

    groceries_id = next((cid for cid, n in categories.items() if n == "Groceries"), None)
    grocery_budget = next((b for b in category_budgets if groceries_id and b.category_id == groceries_id), None)

    def budget_item(label, spent, target):
        if spent > target:
            add(f"{label} {CUR}{spent:,.0f}/{CUR}{target:,.0f} — {CUR}{spent - target:,.0f} over budget", RED,
                "Review", "/transactions")
        else:
            per_day = (target - spent) / max(days_left, 1)
            tail = (f", {CUR}{per_day:,.0f}/day for {days_left} days to stay under" if days_left
                    else " — last day of the month")
            add(f"{label} {CUR}{spent:,.0f}/{CUR}{target:,.0f}{tail}",
                AMBER if spent / target >= 0.8 else EMERALD, "Review", "/transactions")

    if grocery_budget:
        budget_item("Groceries", month_spend_by_category.get(groceries_id, 0), grocery_budget.monthly_amount)
    elif overall_budget and overall_budget.monthly_amount:
        budget_item("Budget", spent_this_month, overall_budget.monthly_amount)
    else:
        add("Set a monthly budget to track your spending", INDIGO, "Set budget", "/profile")

    if not food_today:
        add("No meals logged today", INDIGO, "Log meal", "food")
    elif goals.protein_g and (goals.protein_g - protein_today) > 10 and datetime.now().hour >= 15:
        add(f"Protein {goals.protein_g - protein_today:,.0f}g short today ({protein_today:,.0f}/{goals.protein_g:,.0f}g)",
            AMBER, "Log meal", "food")

    if module_enabled("subscriptions"):
        with Session(engine) as session:
            subs = session.exec(select(Subscription).where(Subscription.active == True)).all()  # noqa: E712
        due = [s for s in subs if s.next_payment_date and today <= s.next_payment_date <= today + timedelta(days=7)]
        if due:
            add(f"{len(due)} subscription{'s' if len(due) != 1 else ''} renew{'s' if len(due) == 1 else ''} this week "
                f"({CUR}{sum(s.amount for s in due):,.0f})", AMBER, "View", "/subscriptions")

    # What's changed: this month so far vs the same point last month (pro-rated,
    # so mid-month isn't automatically "down").
    prev_start, prev_end = period_bounds("monthly", month_start - timedelta(days=1))
    with Session(engine) as session:
        prev_tx = session.exec(select(Transaction).where(Transaction.date >= prev_start, Transaction.date <= prev_end)).all()
    prev_by_cat: dict = {}
    for t in prev_tx:
        prev_by_cat[t.category_id] = prev_by_cat.get(t.category_id, 0) + t.amount
    prorate = min(((today - month_start).days + 1) / ((prev_end - prev_start).days + 1), 1.0)
    changes = []
    for cat_id, cur_amt in month_spend_by_category.items():
        prev_amt = prev_by_cat.get(cat_id, 0) * prorate
        delta = cur_amt - prev_amt
        if prev_amt > 0 and abs(delta) >= 15 and abs(delta) / prev_amt >= 0.25:
            name = categories.get(cat_id, "Uncategorized")
            pct = delta / prev_amt * 100
            if prev_amt < 25 or abs(pct) > 300:   # a tiny base makes percentages absurd
                text = f"{name}: {CUR}{abs(delta):,.0f} {'more' if delta > 0 else 'less'} than this point last month"
            else:
                text = f"{name} {'up' if delta > 0 else 'down'} {abs(pct):.0f}% on this point last month"
            changes.append((abs(delta), text, AMBER if delta > 0 else EMERALD))
    prev_total = sum(prev_by_cat.values()) * prorate
    if prev_total > 0:
        total_delta = spent_this_month - prev_total
        if abs(total_delta) / prev_total >= 0.15 and abs(total_delta) >= 30:
            changes.append((abs(total_delta) * 10, f"Spending overall {'up' if total_delta > 0 else 'down'} "
                            f"{abs(total_delta / prev_total * 100):.0f}% on this point last month",
                            AMBER if total_delta > 0 else EMERALD))
    for _, text, color in sorted(changes, key=lambda c: -c[0])[:2]:
        add(text, color, "See", "/transactions")

    items.sort(key=lambda i: i[0])

    def go(target):
        # A route is a page; anything else is a quick-add kind ("food").
        ui.navigate.to(target) if target.startswith("/") else open_add(target)

    with card_box_accent().classes("w-full gap-1"):
        section_header("Worth knowing")
        if not items:
            with ui.row().classes("items-center gap-2 py-1"):
                ui.icon("check_circle").classes("text-lg").style(f"color:{EMERALD}")
                ui.label("You're on track — nothing needs a look.").classes("text-sm")
        rows = ui.column().classes("w-full gap-0")
        extra = ui.column().classes("w-full gap-0 b-off")
        for n, (_rank, text, color, cta, route) in enumerate(items):
            with (rows if n < 4 else extra):
                row = ui.element("div").classes("b-nudge")
                if route:
                    row.on("click", lambda r=route: go(r))
                with row:
                    ui.element("span").classes("dot").style(f"background:{color}")
                    ui.label(text).classes("b-nudge-text")
                    if cta and route:
                        with ui.element("div").classes("b-nudge-cta"):
                            ui.label(cta)
                            ui.icon("chevron_right")
        if len(items) > 4:
            more = ui.button(f"{len(items) - 4} more", on_click=lambda: (extra.classes(remove="b-off"),
                                                                      more.set_visibility(False))).props(
                "flat dense no-caps color=primary").classes("self-start")


FOOD_CATEGORIES = ("Groceries", "Eating Out")


def _money_and_food(today, categories):
    """The money x health card: what your eating costs, and where the money and
    the calories really go. Last four weeks, so a big shop doesn't skew it."""
    start = today - timedelta(days=27)
    food_ids = {cid for cid, n in categories.items() if n in FOOD_CATEGORIES}
    out_ids = {cid for cid, n in categories.items() if n == "Eating Out"}
    with Session(engine) as session:
        tx = session.exec(select(Transaction).where(Transaction.date >= start, Transaction.date <= today)).all()
        foods = session.exec(select(FoodLog).where(FoodLog.date >= start, FoodLog.date <= today)).all()
        pantry = session.exec(select(PantryItem)).all()
    food_spend = sum(t.amount for t in tx if t.category_id in food_ids)
    out_spend = sum(t.amount for t in tx if t.category_id in out_ids)
    home_spend = food_spend - out_spend
    kcal = sum(f.calories or 0 for f in foods)
    out_kcal = sum(f.calories or 0 for f in foods if f.eaten_out)
    home_kcal = kcal - out_kcal
    days_logged = len({f.date for f in foods if f.calories})

    with card_box().classes("w-full gap-2"):
        section_header("Money & food", subtitle="Last 4 weeks — what your eating costs")
        if days_logged < 5 or food_spend <= 0:
            ui.label("Log your meals and your food shopping (Groceries, Eating Out) for a week or two and this "
                     "shows what your eating costs — per calorie, at home and out.").classes("b-hint").style("margin:0")
        else:
            per_k = food_spend / kcal * 1000 if kcal else None
            summary_strip([
                ("Food spend", f"{CUR}{food_spend:,.0f}", AMBER, f"{CUR}{food_spend / 28:,.2f} a day"),
                ("Per 1,000 kcal", f"{CUR}{per_k:,.2f}" if per_k else "—", INDIGO,
                 f"across {days_logged} days logged"),
            ], width_class="compact")
            # Eating out: its share of the money against its share of the calories.
            if out_spend > 0 and kcal > 0 and out_kcal == 0:
                ui.label(f"Eating out is {out_spend / food_spend:.0%} of your food spend. Turn on “Eaten out” when "
                         "you log a meal from a restaurant or takeaway to see what those calories cost next to "
                         "cooking at home.").classes("b-hint").style("margin:0")
            elif out_spend > 0 and kcal > 0:
                spend_share, kcal_share = out_spend / food_spend, out_kcal / kcal
                with ui.column().classes("w-full gap-1"):
                    ui.label("Eating out").classes("text-sm font-semibold")
                    for label, share, color in (("of your food spend", spend_share, AMBER),
                                                ("of your calories", kcal_share, EMERALD)):
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            ui.label(f"{share:.0%}").classes("text-sm font-bold w-10")
                            with ui.element("div").classes("b-bar flex-1").style("margin-top:0"):
                                ui.element("div").style(f"width:{share * 100:.1f}%; background:{color}")
                            ui.label(label).classes("text-xs w-32").style(f"color:{TEXT_DIM}")
                if out_kcal > 0 and home_kcal > 0 and home_spend > 0:
                    out_per, home_per = out_spend / out_kcal * 1000, home_spend / home_kcal * 1000
                    ratio = out_per / home_per if home_per else 0
                    tone = AMBER if ratio >= 1.5 else TEXT_DIM
                    ui.label(f"Out costs {CUR}{out_per:,.2f} per 1,000 kcal, home {CUR}{home_per:,.2f}"
                             + (f" — {ratio:.1f}× as much." if ratio >= 1.5 else ".")).classes(
                        "text-sm").style(f"color:{tone}")
            # Best value protein, from priced pantry items.
            value = sorted(((it.protein_g / it.price, it.name) for it in pantry
                            if it.price and it.price > 0 and it.protein_g and it.protein_g > 0), reverse=True)
            if value:
                score, name = value[0]
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.icon("fitness_center").classes("text-base").style(f"color:{EMERALD}")
                    ui.label(f"Best value protein in your pantry: {name}, {score:,.0f}g per {CUR}1").classes("text-sm")


def render_monthly_net(container=None):
    """Income minus spending per month for the last six months (bars), and how
    it adds up (line). Used on the Savings page."""
    today = date.today()
    month_keys = []
    y, m = today.year, today.month
    for _ in range(6):
        month_keys.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    month_keys.reverse()
    six_start = date(month_keys[0][0], month_keys[0][1], 1)
    with Session(engine) as session:
        tx6 = session.exec(select(Transaction).where(Transaction.date >= six_start)).all()
        inc6 = session.exec(select(Income).where(Income.date >= six_start)).all()
    spend_by_m, inc_by_m = {}, {}
    for t in tx6:
        spend_by_m[(t.date.year, t.date.month)] = spend_by_m.get((t.date.year, t.date.month), 0) + t.amount
    for i in inc6:
        inc_by_m[(i.date.year, i.date.month)] = inc_by_m.get((i.date.year, i.date.month), 0) + i.amount
    if not (any(inc_by_m.values()) or any(spend_by_m.values())):
        return
    net_series = [round(inc_by_m.get(k, 0) - spend_by_m.get(k, 0), 2) for k in month_keys]
    saved_total = sum(net_series)
    cumulative, run = [], 0.0
    for v in net_series:
        run += v
        cumulative.append(round(run, 2))
    with card_box().classes("w-full"):
        with section_header("Monthly net", subtitle="Income minus spending (bars) and how it adds up (line)"):
            badge(f"{'+' if saved_total >= 0 else '−'}{CUR}{abs(saved_total):,.0f} in 6 months",
                  EMERALD if saved_total >= 0 else RED)
        echart({
            "backgroundColor": "transparent",
            "grid": {"left": 55, "right": 55, "top": 30, "bottom": 28},
            "legend": {"top": 0, "textStyle": {"color": TEXT_DIM, "fontSize": 10}, "itemWidth": 14, "itemHeight": 8},
            "xAxis": {"type": "category", "data": [date(k[0], k[1], 1).strftime("%b") for k in month_keys],
                      "axisLine": {"lineStyle": {"color": BORDER}}, "axisLabel": {"color": TEXT_DIM, "fontSize": 10}},
            "yAxis": [
                {"type": "value", "axisLine": {"show": False},
                 "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                 "splitLine": {"lineStyle": {"color": BORDER}}},
                {"type": "value", "axisLine": {"show": False},
                 "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"}, "splitLine": {"show": False}},
            ],
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "series": [
                {"name": "Monthly net", "type": "bar",
                 "data": [{"value": v, "itemStyle": {"color": EMERALD if v >= 0 else RED, "borderRadius": [3, 3, 0, 0]}}
                          for v in net_series],
                 "markLine": {"silent": True, "symbol": "none", "lineStyle": {"color": TEXT_DIM, "type": "dashed"},
                              "label": {"show": False}, "data": [{"yAxis": 0}]}},
                {"name": "Total", "type": "line", "yAxisIndex": 1, "data": cumulative, "smooth": True,
                 "symbolSize": 5, "lineStyle": {"color": INDIGO, "width": 3}, "itemStyle": {"color": INDIGO},
                 "areaStyle": {"color": "rgba(99,102,241,0.08)"}},
            ],
        }).classes("w-full h-52")


def render_expenses(container, period, ref_date, custom_range=None):
    container.clear()
    start, end = resolve_window(period, ref_date, Transaction, Transaction.date, custom_range)
    with Session(engine) as session:
        transactions = session.exec(
            select(Transaction).where(Transaction.date >= start, Transaction.date <= end)
        ).all()
        categories = {c.id: c.name for c in session.exec(select(Category)).all()}

    total = sum(t.amount for t in transactions)
    num_days = (end - start).days + 1
    daily_avg = total / num_days

    prev_total = None
    pw = previous_window(period, start, num_days)
    if pw:
        prev_total = _period_total(Transaction, "amount", Transaction.date, *pw)

    by_category: dict = {}
    for t in transactions:
        name = categories.get(t.category_id, "Uncategorized")
        by_category[name] = by_category.get(name, 0) + t.amount

    with container:
        section_header("Expenses",
                       subtitle=friendly_range(start, end, period))
        with ui.row().classes("gap-8 mt-1 items-end"):
            with ui.column().classes("gap-0"):
                ui.label("Total").classes("text-xs").style(f"color:{TEXT_DIM}")
                total_label = ui.label(f"{CUR}{total:,.2f}").classes("text-2xl font-bold")
            with ui.column().classes("gap-0"):
                ui.label("Daily average").classes("text-xs").style(f"color:{TEXT_DIM}")
                daily_avg_label = ui.label(f"{CUR}{daily_avg:,.2f}").classes("text-2xl font-bold")
        if prev_total is not None:
            with ui.row().classes("mt-1"):
                period_delta_badge(total, prev_total, higher_is_worse=True)

        if by_category:
            sorted_items = sorted(by_category.items(), key=lambda x: -x[1])

            def recompute_from_legend(e):
                # e.args is the {category_name: is_selected} map ECharts sends
                # when a legend entry is toggled. Recompute the headline total
                # and daily average from only the still-selected categories, so
                # excluding e.g. rent updates the numbers, not just the pie.
                selected = (e.args or {}).get("selected", {})
                shown_total = sum(amt for name, amt in by_category.items() if selected.get(name, True))
                total_label.set_text(f"{CUR}{shown_total:,.2f}")
                daily_avg_label.set_text(f"{CUR}{shown_total / num_days:,.2f}")

            chart = echart({
                "backgroundColor": "transparent",
                "color": CHART_PALETTE,
                "tooltip": {"trigger": "item"},
                "legend": {
                    "type": "scroll", "bottom": 0, "left": "center",
                    "textStyle": {"color": TEXT_DIM, "fontSize": 11}, "itemWidth": 10, "itemHeight": 10,
                    "pageIconColor": TEXT_DIM, "pageIconInactiveColor": BORDER,
                    "pageTextStyle": {"color": TEXT_DIM},
                },
                "series": [{
                    "type": "pie", "radius": ["42%", "66%"], "center": ["50%", "43%"],
                    "data": [{"value": round(amt, 2), "name": name} for name, amt in sorted_items],
                    "label": {"show": False},
                    "itemStyle": {"borderColor": SURFACE, "borderWidth": 2},
                }],
            }).classes("w-full h-64 mt-2")
            chart.on("chart:legendselectchanged", recompute_from_legend,
                     js_handler="(e) => emit({selected: e.selected})")
            ui.label("Tap a category to include/exclude it from the total.").classes(
                "text-xs mt-1"
            ).style(f"color:{TEXT_DIM}")
        else:
            empty_state("No spending recorded in this period.", "shopping_cart")


def render_amount_trend(container, model, date_col, title, icon, color, period, ref_date,
                        empty_hint="Nothing recorded in this period.", custom_range=None):
    """Full-width bar chart of a money series per sub-bucket across the window
    -- per day for short windows, per month for long ones -- with a dashed
    average line. Reusable for spending (Transaction) and income (Income),
    since both share `.date` and `.amount`."""
    container.clear()
    start, end = resolve_window(period, ref_date, model, date_col, custom_range)
    with Session(engine) as session:
        rows = session.exec(select(model).where(date_col >= start, date_col <= end)).all()

    span_days = (end - start).days + 1
    with container:
        section_header(title, subtitle=friendly_range(start, end, period))
        if span_days <= 1:
            empty_state("Pick a longer period to see a trend.", icon)
            return
        if not rows:
            empty_state(empty_hint, icon)
            return

        daily = span_days <= 31
        labels, values = [], []
        if daily:
            by_day: dict = {}
            for r in rows:
                by_day[r.date] = by_day.get(r.date, 0) + r.amount
            d = start
            while d <= end:
                labels.append(d.strftime("%a") if span_days <= 7 else str(d.day))
                values.append(round(by_day.get(d, 0), 2))
                d += timedelta(days=1)
        else:
            by_month: dict = {}
            for r in rows:
                key = (r.date.year, r.date.month)
                by_month[key] = by_month.get(key, 0) + r.amount
            multi_year = start.year != end.year
            y, m = start.year, start.month
            while (y, m) <= (end.year, end.month):
                lbl = date(y, m, 1).strftime("%b %y") if multi_year else date(y, m, 1).strftime("%b")
                labels.append(lbl)
                values.append(round(by_month.get((y, m), 0), 2))
                m += 1
                if m > 12:
                    m, y = 1, y + 1

        rotate = 45 if len(labels) > 14 else 0
        echart({
            "backgroundColor": "transparent",
            "grid": {"left": 55, "right": 15, "top": 15, "bottom": 45 if rotate else 28},
            "xAxis": {
                "type": "category", "data": labels,
                "axisLine": {"lineStyle": {"color": BORDER}},
                "axisLabel": {"color": TEXT_DIM, "fontSize": 10, "rotate": rotate},
            },
            "yAxis": {
                "type": "value", "axisLine": {"show": False},
                "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                "splitLine": {"lineStyle": {"color": BORDER}},
            },
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "series": [{
                "type": "bar", "data": values,
                "itemStyle": {"color": color, "borderRadius": [3, 3, 0, 0]},
                "markLine": {
                    "silent": True, "symbol": "none",
                    "lineStyle": {"color": TEXT_DIM, "type": "dashed"},
                    "label": {"color": TEXT_DIM, "fontSize": 10, "formatter": "avg"},
                    "data": [{"type": "average"}],
                },
            }],
        }).classes("w-full h-48")


def render_income_summary(container, period, ref_date):
    container.clear()
    with Session(engine) as session:
        if period == "all_time":
            earliest = session.exec(select(Income).order_by(Income.date)).first()
            start = earliest.date if earliest else date.today()
            end = date.today()
        else:
            start, end = period_bounds(period, ref_date)
        entries = session.exec(
            select(Income).where(Income.date >= start, Income.date <= end)
        ).all()

    total = sum(i.amount for i in entries)
    num_days = (end - start).days + 1
    daily_avg = total / num_days

    prev_total = None
    if period != "all_time":
        prev_start, prev_end = period_bounds(period, start - timedelta(days=1))
        prev_total = _period_total(Income, "amount", Income.date, prev_start, prev_end)

    by_source: dict = {}
    for i in entries:
        by_source[i.source] = by_source.get(i.source, 0) + i.amount

    with container:
        section_header("Income", icon="payments", icon_color=EMERALD,
                       subtitle=friendly_range(start, end, period))
        with ui.row().classes("gap-8 mt-1 items-end"):
            with ui.column().classes("gap-0"):
                ui.label("Total").classes("text-xs").style(f"color:{TEXT_DIM}")
                ui.label(f"{CUR}{total:,.2f}").classes("text-2xl font-bold").style(f"color:{EMERALD}")
            with ui.column().classes("gap-0"):
                ui.label("Daily average").classes("text-xs").style(f"color:{TEXT_DIM}")
                ui.label(f"{CUR}{daily_avg:,.2f}").classes("text-2xl font-bold")
        if prev_total is not None:
            with ui.row().classes("mt-1"):
                period_delta_badge(total, prev_total, higher_is_worse=False)

        if by_source:
            sorted_items = sorted(by_source.items(), key=lambda x: -x[1])
            echart({
                "backgroundColor": "transparent",
                "color": CHART_PALETTE,
                "tooltip": {"trigger": "item"},
                "legend": {
                    "type": "scroll", "bottom": 0, "left": "center",
                    "textStyle": {"color": TEXT_DIM, "fontSize": 11}, "itemWidth": 10, "itemHeight": 10,
                    "pageIconColor": TEXT_DIM, "pageIconInactiveColor": BORDER,
                    "pageTextStyle": {"color": TEXT_DIM},
                },
                "series": [{
                    "type": "pie", "radius": ["42%", "66%"], "center": ["50%", "43%"],
                    "data": [{"value": round(amt, 2), "name": name} for name, amt in sorted_items],
                    "label": {"show": False},
                    "itemStyle": {"borderColor": SURFACE, "borderWidth": 2},
                }],
            }).classes("w-full h-64 mt-2")
        else:
            empty_state("No income logged in this period.", "payments")


def render_nutrition(container, period, ref_date, goals, custom_range=None):
    container.clear()
    start, end = resolve_window(period, ref_date, FoodLog, FoodLog.date, custom_range)
    with Session(engine) as session:
        entries = session.exec(
            select(FoodLog).where(FoodLog.date >= start, FoodLog.date <= end)
        ).all()

    num_days = (end - start).days + 1
    totals = {field: 0.0 for field in NUTRIENT_FIELDS}
    for e in entries:
        for field in NUTRIENT_FIELDS:
            value = getattr(e, field)
            if value is not None:
                totals[field] += value
    averages = {field: totals[field] / num_days for field in NUTRIENT_FIELDS}

    prev_avg_cal = None
    pw = previous_window(period, start, num_days)
    if pw:
        prev_days = (pw[1] - pw[0]).days + 1
        prev_total_cal = _period_total(FoodLog, "calories", FoodLog.date, *pw)
        prev_avg_cal = prev_total_cal / prev_days if prev_days else None

    with container:
        section_header("Nutrition",
                       subtitle=friendly_range(start, end, period))
        with ui.row().classes("gap-8 mt-1 items-end"):
            with ui.column().classes("gap-0"):
                ui.label("Total calories").classes("text-xs").style(f"color:{TEXT_DIM}")
                ui.label(f"{totals['calories']:,.0f} kcal").classes("text-2xl font-bold")
            with ui.column().classes("gap-0"):
                ui.label("Daily average").classes("text-xs").style(f"color:{TEXT_DIM}")
                ui.label(f"{averages['calories']:,.0f} kcal").classes("text-2xl font-bold")
        if prev_avg_cal:
            with ui.row().classes("mt-1"):
                period_delta_badge(averages["calories"], prev_avg_cal, neutral=True)

        if entries:
            macro_goals = [goals.protein_g or 0, goals.carbs_g or 0, goals.fat_g or 0]
            macro_actuals = [round(averages["protein_g"], 1), round(averages["carbs_g"], 1), round(averages["fat_g"], 1)]
            echart({
                "backgroundColor": "transparent",
                "color": [INDIGO, SURFACE_2],
                "grid": {"left": 55, "right": 20, "top": 30, "bottom": 20},
                "legend": {"data": ["Daily avg", "Goal"], "textStyle": {"color": TEXT_DIM, "fontSize": 11}, "top": 0},
                "xAxis": {
                    "type": "value", "axisLine": {"show": False},
                    "axisLabel": {"color": TEXT_DIM}, "splitLine": {"lineStyle": {"color": BORDER}},
                },
                "yAxis": {
                    "type": "category", "data": ["Protein", "Carbs", "Fat"],
                    "axisLine": {"lineStyle": {"color": BORDER}}, "axisLabel": {"color": TEXT_DIM},
                },
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "series": [
                    {"name": "Daily avg", "type": "bar", "data": macro_actuals, "itemStyle": {"color": INDIGO, "borderRadius": [0, 4, 4, 0]}},
                    {"name": "Goal", "type": "bar", "data": macro_goals, "itemStyle": {"color": SURFACE_2, "borderRadius": [0, 4, 4, 0]}},
                ],
            }).classes("w-full h-64 mt-2")

            rows = [
                {"nutrient": label, "total": f"{totals[field]:,.1f}{unit}", "daily_avg": f"{averages[field]:,.1f}{unit}"}
                for field, label, unit in [
                    ("fiber_g", "Fiber", "g"), ("sugar_g", "Sugar", "g"), ("sodium_mg", "Sodium", "mg"),
                ]
            ]
            with ui.expansion("Fiber, sugar, sodium").classes("w-full mt-1"):
                ui.table(
                    columns=[
                        {"name": "nutrient", "label": "Nutrient", "field": "nutrient"},
                        {"name": "total", "label": "Total", "field": "total"},
                        {"name": "daily_avg", "label": "Daily avg", "field": "daily_avg"},
                    ],
                    rows=rows,
                ).classes("w-full").props(f"{'dark ' if _theme.THEME_DARK else ''}flat dense")
        else:
            empty_state("No food logged in this period.", "restaurant")
