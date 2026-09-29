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
)
from ..components import (
    badge,
    card_box,
    card_box_accent,
    date_field,
    empty_state,
    period_delta_badge,
    pill_toggle,
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
    today = date.today()
    now = datetime.now()
    yesterday = today - timedelta(days=1)

    # Time-aware greeting -- a reason to open at any hour. Morning gives a
    # yesterday recap + a nudge to start the day; midday a protein/lunch check;
    # evening a today recap. Keeps the dashboard current instead of a static title.
    with Session(engine) as session:
        _g = session.exec(select(NutrientGoals)).first() or NutrientGoals()
        _t_food = session.exec(select(FoodLog).where(FoodLog.date == today)).all()
        _t_spend = sum(t.amount for t in session.exec(select(Transaction).where(Transaction.date == today)).all())
        _y_food = session.exec(select(FoodLog).where(FoodLog.date == yesterday)).all()
        _y_spend = sum(t.amount for t in session.exec(select(Transaction).where(Transaction.date == yesterday)).all())
    _t_cal = sum(f.calories or 0 for f in _t_food)
    _y_cal = sum(f.calories or 0 for f in _y_food)
    _protein_now = sum(f.protein_g or 0 for f in _t_food)
    _h = now.hour
    if 5 <= _h < 12:
        greeting = "Good morning"
        if _y_spend or _y_cal:
            focus = f"Yesterday: {CUR}{_y_spend:,.0f} spent · {_y_cal:,.0f} kcal. Log breakfast to start the day."
        else:
            focus = "A fresh day — log a meal or an expense to get going."
    elif 12 <= _h < 18:
        greeting = "Good afternoon"
        if _g.protein_g and _protein_now < _g.protein_g:
            focus = f"{_protein_now:,.0f}g protein so far — {_g.protein_g - _protein_now:,.0f}g to go. Logged lunch?"
        elif _g.protein_g:
            focus = f"Protein goal already hit ({_protein_now:,.0f}g) — nice. {CUR}{_t_spend:,.0f} spent so far."
        else:
            focus = f"{CUR}{_t_spend:,.0f} spent so far today."
    else:
        greeting = "Good evening"
        focus = f"Today: {CUR}{_t_spend:,.0f} spent · {_t_cal:,.0f} kcal. Round off dinner and tomorrow's plan."
    with ui.column().classes("gap-1"):
        ui.label(f"{today:%A} {today.day} {today:%B}").classes("b-eyebrow")
        ui.label(greeting).classes("b-title")
        ui.label(focus).classes("b-subtitle")

    with Session(engine) as session:
        goals = session.exec(select(NutrientGoals)).first() or NutrientGoals()
        food_today = session.exec(select(FoodLog).where(FoodLog.date == today)).all()
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
        # welcome card below; auto-clears the moment anything is logged.
        first_run = (session.exec(select(Transaction)).first() is None
                     and session.exec(select(FoodLog)).first() is None)

    month_spend_by_category: dict = {}
    for t in month_transactions:
        month_spend_by_category[t.category_id] = month_spend_by_category.get(t.category_id, 0) + t.amount

    spent_this_month = sum(t.amount for t in month_transactions)
    income_this_month = sum(i.amount for i in month_income)
    net_this_month = income_this_month - spent_this_month
    income_module = module_enabled("income")

    # --- First-run welcome: state the "why" and offer the first win, so a new
    # user understands the app before entering any data. Auto-hides once anything
    # is logged, so it never nags an established user. ---
    if first_run:
        with card_box_accent().classes("w-full"):
            ui.label("Welcome to Balance").classes("text-xl font-bold")
            ui.label("Track what you spend and what it does to your body — in one place.").classes(
                "text-sm").style(f"color:{TEXT_DIM}")
            ui.label(
                "Log one expense and one meal and the dashboard comes alive — you'll see how "
                "your money and your health line up. No lengthy setup: targets have sensible "
                "defaults you can tweak any time."
            ).classes("text-sm mt-2")
            with ui.row().classes("gap-2 flex-wrap mt-3"):
                ui.button("Add your first expense", icon="add",
                          on_click=lambda: open_add("expense")).props("unelevated no-caps color=primary")
                ui.button("Log your first meal", icon="restaurant",
                          on_click=lambda: open_add("food")).props("unelevated no-caps color=primary")
            ui.label("This welcome disappears once you start logging.").classes(
                "text-xs mt-2").style(f"color:{TEXT_DIM}")

    # --- The month in figures, then the budget bar. (Adding lives on the dock's
    # + button, so there are no add buttons here.) ---
    days_left = max((month_end - today).days, 0)
    has_budget = bool(overall_budget and overall_budget.monthly_amount)
    budget_left = (overall_budget.monthly_amount - spent_this_month) if has_budget else 0
    month_name = today.strftime("%B")
    summary_strip([
        (f"Spent in {month_name}", f"{CUR}{spent_this_month:,.0f}", AMBER),
        has_budget and ("Left in budget" if budget_left >= 0 else "Over budget",
                        f"{CUR}{abs(budget_left):,.0f}", EMERALD if budget_left >= 0 else RED),
        income_module and (f"Income in {month_name}", f"{CUR}{income_this_month:,.0f}", EMERALD),
        income_module and ("Net", f"{'+' if net_this_month >= 0 else '−'}{CUR}{abs(net_this_month):,.0f}",
                           EMERALD if net_this_month >= 0 else RED),
    ])
    if has_budget:
        with ui.element("div").classes("b-budget"):
            thin_meter(spent_this_month, overall_budget.monthly_amount,
                       RED if budget_left < 0 else (AMBER if spent_this_month >= 0.8 * overall_budget.monthly_amount
                                                    else EMERALD))
            with ui.element("div").classes("b-budget-cap"):
                ui.html(f"<span><b>{CUR}{spent_this_month:,.0f}</b> of {CUR}{overall_budget.monthly_amount:,.0f} budget</span>")
                ui.label(f"{days_left} day{'s' if days_left != 1 else ''} left" if days_left else "Last day of the month")
            if category_budgets:
                with ui.expansion("Budget by category").classes("w-full"):
                    for cb in sorted(category_budgets, key=lambda b: categories.get(b.category_id, "")):
                        progress_row(
                            categories.get(cb.category_id, "Uncategorized"),
                            month_spend_by_category.get(cb.category_id, 0),
                            cb.monthly_amount, f" {CUR}", is_limit=True,
                        )

    # --- Needs your attention: computed, verb-driven nudges (the actionable core) ---
    protein_today = sum(f.protein_g or 0 for f in food_today)
    groceries_id = next((cid for cid, n in categories.items() if n == "Groceries"), None)
    grocery_budget = next((b for b in category_budgets if groceries_id and b.category_id == groceries_id), None)

    nudges = []  # (icon, text, color, cta_label|None, route|None)

    def _budget_nudge(label, spent, target, route):
        if not target:
            return
        if spent > target:
            nudges.append(("account_balance_wallet",
                           f"{label} {CUR}{spent:,.0f}/{CUR}{target:,.0f} — {CUR}{spent - target:,.0f} over budget",
                           RED, "Review", route))
        else:
            per_day = (target - spent) / max(days_left, 1)
            tail = (f", {days_left} days left — {CUR}{per_day:,.0f}/day to stay under"
                    if days_left else " — last day of the month")
            nudges.append(("account_balance_wallet", f"{label} {CUR}{spent:,.0f}/{CUR}{target:,.0f}{tail}",
                           AMBER if spent / target >= 0.8 else EMERALD, "Review", route))

    if grocery_budget:
        _budget_nudge("Groceries", month_spend_by_category.get(groceries_id, 0), grocery_budget.monthly_amount, "/transactions")
    elif overall_budget and overall_budget.monthly_amount:
        _budget_nudge("Budget", spent_this_month, overall_budget.monthly_amount, "/transactions")
    else:
        nudges.append(("savings", "Set a monthly budget to track your spending", INDIGO, "Set budget", "/profile"))

    if not food_today:
        nudges.append(("restaurant", "No meals logged today", INDIGO, "Log meal", "food"))
    elif goals.protein_g and (goals.protein_g - protein_today) > 10:
        nudges.append(("fitness_center",
                       f"Protein {goals.protein_g - protein_today:,.0f}g short today "
                       f"({protein_today:,.0f}/{goals.protein_g:,.0f}g)",
                       AMBER, "Log meal", "food"))

    _eat_out_ids = [cid for cid, n in categories.items() if n == "Eating Out"]
    _eat_out = sum(month_spend_by_category.get(cid, 0) for cid in _eat_out_ids)
    if _eat_out >= 20:
        with Session(engine) as session:
            _eat_out_cal = sum(f.calories or 0 for f in session.exec(
                select(FoodLog).where(FoodLog.date >= month_start, FoodLog.date <= month_end,
                                      FoodLog.eaten_out == True)).all())  # noqa: E712
        _cal_bit = f" ≈ {_eat_out_cal:,.0f} kcal from meals out" if _eat_out_cal > 0 else ""
        nudges.append(("restaurant_menu",
                       f"{CUR}{_eat_out:,.0f} on eating out this month{_cal_bit} — cooking more saves both",
                       AMBER, "See", "/transactions"))

    if module_enabled("subscriptions"):
        with Session(engine) as session:
            _subs = session.exec(select(Subscription).where(Subscription.active == True)).all()  # noqa: E712
        _due = [s for s in _subs if s.next_payment_date and today <= s.next_payment_date <= today + timedelta(days=7)]
        if _due:
            nudges.append(("autorenew",
                           f"{len(_due)} subscription(s) renew this week ({CUR}{sum(s.amount for s in _due):,.0f})",
                           AMBER, "View", "/subscriptions"))

    # Two columns on a wide screen: today and what needs doing on the left,
    # the longer view on the right. One column on a phone.
    with ui.element("div").classes("b-dash-grid"):
        with ui.column().classes("b-dash-col"):
            def _go(target):
                # A route is a page; anything else is a quick-add kind ("food").
                ui.navigate.to(target) if target.startswith("/") else open_add(target)

            with card_box_accent().classes("w-full gap-1"):
                section_header("Needs your attention")
                if not nudges:
                    with ui.row().classes("items-center gap-2 py-1"):
                        ui.icon("check_circle").classes("text-lg").style(f"color:{EMERALD}")
                        ui.label("You're on track — nothing needs your attention.").classes("text-sm")
                with ui.column().classes("w-full gap-0"):
                    for _icon, _text, _color, _cta, _route in nudges[:5]:
                        row = ui.element("div").classes("b-nudge")
                        if _route:
                            row.on("click", lambda r=_route: _go(r))
                        with row:
                            ui.element("span").classes("dot").style(f"background:{_color}")
                            ui.label(_text).classes("b-nudge-text")
                            if _cta and _route:
                                with ui.element("div").classes("b-nudge-cta"):
                                    ui.label(_cta)
                                    ui.icon("chevron_right")

            # --- Today: nutrition, what to watch, and water -- navigable day by day ---
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

            def shift_day(delta):
                new_date = view_state["date"] + timedelta(days=delta)
                if new_date <= today:  # never navigate into the future
                    view_state["date"] = new_date
                    render_today()

            def render_today():
                today_card.clear()
                sel = view_state["date"]
                is_today = sel == today
                with Session(engine) as session:
                    foods = session.exec(select(FoodLog).where(FoodLog.date == sel)).all()
                    waters = session.exec(select(WaterLog).where(WaterLog.date == sel)).all()

                cals = sum(f.calories or 0 for f in foods)
                protein = sum(f.protein_g or 0 for f in foods)
                carbs = sum(f.carbs_g or 0 for f in foods)
                fat = sum(f.fat_g or 0 for f in foods)
                limit_totals = {field: sum(getattr(f, field) or 0 for f in foods) for _, field, _, _ in LIMIT_FIELDS}
                water_ml = sum(w.amount_ml for w in waters)

                flagged = []
                for name, field, limit_key, unit in LIMIT_FIELDS:
                    lim = getattr(goals, limit_key)
                    cur = limit_totals[field]
                    if not lim:
                        continue
                    if cur > lim:
                        flagged.append((f"{name} {cur:,.0f}/{lim:,.0f}{unit}", RED))
                    elif cur / lim >= 0.8:
                        flagged.append((f"{name} {cur:,.0f}/{lim:,.0f}{unit}", AMBER))

                with today_card:
                    hdr = section_header(format_date_header(sel), subtitle=sel.strftime("%A, %d %B"))
                    with hdr:
                        # Fixed control group so nothing shifts as you page days: the
                        # "Today" shortcut always occupies its slot (just hidden when
                        # you're already on today), and the chevrons stay put.
                        today_btn = ui.button("Today", on_click=lambda: (view_state.update(date=today), render_today())).props("flat dense no-caps").classes("text-xs")
                        ui.button(icon="chevron_left", on_click=lambda: shift_day(-1)).props("flat round dense").tooltip("Previous day")
                        nxt = ui.button(icon="chevron_right", on_click=lambda: shift_day(1)).props("flat round dense")
                        if is_today:
                            today_btn.style("visibility:hidden")
                            nxt.props("disable")
                        else:
                            nxt.tooltip("Next day")

                    with ui.grid().classes("w-full grid-cols-2 sm:grid-cols-4 gap-2 gap-y-4 mt-1 justify-items-center"):
                        ring_gauge("Calories", cals, goals.calories, "kcal", INDIGO)
                        ring_gauge("Protein", protein, goals.protein_g, "g", EMERALD)
                        ring_gauge("Carbs", carbs, goals.carbs_g, "g", AMBER)
                        ring_gauge("Fat", fat, goals.fat_g, "g", VIOLET)

                    # Surface only the limits actually worth watching as pills, rather
                    # than burying every limit in an always-collapsed expansion.
                    ui.label("Things to watch").classes("text-xs uppercase tracking-wide mt-2").style(f"color:{TEXT_DIM}")
                    if flagged:
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            for text, color in flagged:
                                badge(text, color)
                    else:
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("check_circle").classes("text-sm").style(f"color:{EMERALD}")
                            ui.label("Nothing over the limits." if not is_today else "Nothing over your limits today.").classes("text-xs").style(f"color:{TEXT_DIM}")
                    with ui.expansion("All limits & caffeine-like substances").classes("w-full mt-1"):
                        for name, field, limit_key, unit in LIMIT_FIELDS:
                            progress_row(name, limit_totals[field], getattr(goals, limit_key), unit, is_limit=True, info_key=limit_key)
                        ui.separator().classes("my-2")
                        ui.label(
                            "Not tracked with a daily total (no standard serving data), but worth being "
                            "mindful of if you consume them regularly:"
                        ).classes("text-xs mb-1").style(f"color:{TEXT_DIM}")
                        for sub in CAFFEINE_LIKE_SUBSTANCES:
                            with ui.row().classes("w-full gap-2 items-start py-1"):
                                ui.label(sub["name"]).classes("text-sm font-semibold w-24 shrink-0")
                                ui.label(sub["note"]).classes("text-xs").style(f"color:{TEXT_DIM}")

                    ui.separator().classes("my-2")

                    # --- water: log for today, read-only when reviewing a past day ---
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
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
                    last = session.exec(
                        select(WaterLog).where(WaterLog.date == today).order_by(WaterLog.id.desc())
                    ).first()
                    if last:
                        session.delete(last)
                        session.commit()
                render_today()

            render_today()

        with ui.column().classes("b-dash-col"):
            # --- Cost per macro: the signature money x health crossover. Pantry items
            # carry both price and protein, so we can rank what gives the most protein
            # per pound -- the "eat well on a budget" insight no single-purpose app has.
            # Shown only when there's enough priced pantry data to rank. ---
            with Session(engine) as session:
                _pantry = session.exec(select(PantryItem)).all()
            protein_value = [
                (it.protein_g / it.price, it.name, it.calories)
                for it in _pantry
                if it.price and it.price > 0 and it.protein_g and it.protein_g > 0
            ]
            if len(protein_value) >= 2:
                protein_value.sort(key=lambda x: -x[0])
                best = protein_value[:3]
                worst = protein_value[-1]
                with card_box().classes("w-full"):
                    section_header("Best value protein",
                                   subtitle=f"Most protein per {CUR}1 in your pantry — handy for a budget-friendly bulk")
                    for score, name, _cals in best:
                        with ui.row().classes("w-full items-center gap-2 py-1"):
                            ui.label(name).classes("text-sm font-semibold flex-grow")
                            ui.label(f"{score:,.0f}g protein / {CUR}1").classes("text-sm").style(f"color:{EMERALD}")
                    if worst not in best:
                        ui.separator().classes("my-1")
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.label(f"Worst value: {worst[1]}").classes("text-xs flex-grow").style(f"color:{TEXT_DIM}")
                            ui.label(f"{worst[0]:,.0f}g / {CUR}1").classes("text-xs").style(f"color:{AMBER}")

            # --- Insights: notable this-month-vs-last-month changes, computed not curated ---
            prev_month_start, prev_month_end = period_bounds("monthly", month_start - timedelta(days=1))
            with Session(engine) as session:
                prev_transactions = session.exec(
                    select(Transaction).where(Transaction.date >= prev_month_start, Transaction.date <= prev_month_end)
                ).all()
            prev_spend_by_category: dict = {}
            for t in prev_transactions:
                prev_spend_by_category[t.category_id] = prev_spend_by_category.get(t.category_id, 0) + t.amount

            # pro-rate last month to the same number of elapsed days so mid-month
            # comparisons aren't automatically "down vs last month"
            elapsed = (today - month_start).days + 1
            prev_days = (prev_month_end - prev_month_start).days + 1
            prorate = min(elapsed / prev_days, 1.0)

            insights = []
            for cat_id, cur_amt in month_spend_by_category.items():
                prev_amt = prev_spend_by_category.get(cat_id, 0) * prorate
                if prev_amt < 10 and cur_amt < 10:
                    continue
                delta = cur_amt - prev_amt
                if prev_amt > 0 and abs(delta) >= 15 and abs(delta) / prev_amt >= 0.25:
                    name = categories.get(cat_id, "Uncategorized")
                    pct = delta / prev_amt * 100
                    if prev_amt < 25 or abs(pct) > 300:
                        # tiny base makes percentages absurd ("up 1351%") -- use absolute phrasing
                        text = (f"{name} {CUR}{abs(delta):,.0f} {'more' if delta > 0 else 'less'} than last month "
                                f"({CUR}{cur_amt:,.0f} vs {CUR}{prev_amt:,.0f})")
                    else:
                        text = (f"{name} {'up' if delta > 0 else 'down'} {abs(pct):.0f}% vs last month "
                                f"({CUR}{cur_amt:,.0f} vs {CUR}{prev_amt:,.0f})")
                    insights.append((abs(delta), text, AMBER if delta > 0 else EMERALD))
            prev_total_prorated = sum(prev_spend_by_category.values()) * prorate
            if prev_total_prorated > 0:
                total_delta = spent_this_month - prev_total_prorated
                if abs(total_delta) / prev_total_prorated >= 0.15 and abs(total_delta) >= 30:
                    pct = total_delta / prev_total_prorated * 100
                    insights.append((abs(total_delta) * 10,  # weight overall change to the top
                                     f"Overall spending {'up' if total_delta > 0 else 'down'} {abs(pct):.0f}% "
                                     f"vs the same point last month", AMBER if total_delta > 0 else EMERALD))
            insights.sort(key=lambda x: -x[0])

            if insights:
                with card_box().classes("w-full"):
                    section_header("Insights",
                                   subtitle="Notable changes vs the same point last month")
                    for _, text, color in insights[:3]:
                        with ui.row().classes("items-start gap-2 no-wrap"):
                            ui.icon("trending_up" if color == AMBER else "trending_down").classes(
                                "text-base shrink-0 mt-0.5").style(f"color:{color}")
                            ui.label(text).classes("text-sm")

            # --- Savings: monthly net (income − spending) for the trailing 6 months ---
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
            net_series = [round(inc_by_m.get(k, 0) - spend_by_m.get(k, 0), 2) for k in month_keys]

            if any(inc_by_m.values()) or any(spend_by_m.values()):
                saved_total = sum(net_series)
                cumulative, _run = [], 0.0
                for v in net_series:
                    _run += v
                    cumulative.append(round(_run, 2))
                with card_box().classes("w-full"):
                    hdr = section_header("Savings",
                                         subtitle="Monthly net (bars) and how it adds up (line), last 6 months")
                    with hdr:
                        badge(f"{'+' if saved_total >= 0 else '−'}{CUR}{abs(saved_total):,.0f} over 6 months",
                              EMERALD if saved_total >= 0 else RED)
                    echart({
                        "backgroundColor": "transparent",
                        "grid": {"left": 55, "right": 55, "top": 30, "bottom": 28},
                        "legend": {"top": 0, "textStyle": {"color": TEXT_DIM, "fontSize": 10},
                                   "itemWidth": 14, "itemHeight": 8},
                        "xAxis": {
                            "type": "category",
                            "data": [date(k[0], k[1], 1).strftime("%b") for k in month_keys],
                            "axisLine": {"lineStyle": {"color": BORDER}},
                            "axisLabel": {"color": TEXT_DIM, "fontSize": 10},
                        },
                        "yAxis": [
                            {"type": "value", "axisLine": {"show": False},
                             "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                             "splitLine": {"lineStyle": {"color": BORDER}}},
                            {"type": "value", "axisLine": {"show": False},
                             "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                             "splitLine": {"show": False}},
                        ],
                        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                        "series": [
                            {
                                "name": "Monthly net", "type": "bar",
                                "data": [
                                    {"value": v, "itemStyle": {"color": EMERALD if v >= 0 else RED, "borderRadius": [3, 3, 0, 0]}}
                                    for v in net_series
                                ],
                                "markLine": {
                                    "silent": True, "symbol": "none",
                                    "lineStyle": {"color": TEXT_DIM, "type": "dashed"},
                                    "label": {"show": False},
                                    "data": [{"yAxis": 0}],
                                },
                            },
                            {
                                "name": "Total saved", "type": "line", "yAxisIndex": 1,
                                "data": cumulative, "smooth": True, "symbolSize": 5,
                                "lineStyle": {"color": INDIGO, "width": 3},
                                "itemStyle": {"color": INDIGO},
                                "areaStyle": {"color": "rgba(99,102,241,0.08)"},
                            },
                        ],
                    }).classes("w-full h-52")

            # --- habit streaks ---
            from backend.streaks import compute_streaks
            streaks = compute_streaks(today)
            if any(s["streak"] > 0 for s in streaks):
                with card_box().classes("w-full"):
                    section_header("Streaks", subtitle="Days in a row hitting your goals")
                    with ui.element("div").classes("b-streaks"):
                        for s in streaks:
                            if s["streak"] <= 0:
                                continue
                            with ui.element("div").classes("b-streak"):
                                ui.icon("local_fire_department").classes("text-xl").style(f"color:{AMBER}")
                                ui.label(str(s["streak"])).classes("n")
                                with ui.column().classes("gap-0"):
                                    ui.label(f"day{'s' if s['streak'] != 1 else ''}").classes("l")
                                    ui.label(s["label"]).classes("l")

    # --- Overview: spending & nutrition over a chosen window (centerpiece) ---
    with card_box().classes("w-full"):
        section_header("Overview",
                       subtitle="Spending & nutrition over your chosen window")
        period_state = {"value": "monthly"}
        pill_toggle({"daily": "Day", "weekly": "Week", "monthly": "Month", "6month": "6 months",
                     "yearly": "Year", "custom": "Custom"}, "monthly",
                    lambda v: (period_state.update(value=v), refresh()))
        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            date_input = date_field(value=today.isoformat())
            with ui.row().classes("items-center gap-3 flex-wrap") as custom_row:
                from_input = date_field("From", value=(today - timedelta(days=30)).isoformat())
                to_input = date_field("To", value=today.isoformat())
            custom_row.set_visibility(False)

        inner_card = f"bg-[{SURFACE_2}] border border-[{BORDER}] rounded-2xl p-3 sm:p-4 gap-3 w-full"
        trend_card = ui.column().classes(inner_card + " mt-1")
        with ui.grid().classes("w-full grid-cols-1 lg:grid-cols-2 gap-4"):
            expense_card = ui.column().classes(inner_card)
            nutrition_card = ui.column().classes(inner_card)

        def refresh():
            period = period_state["value"]
            ref_date = date.fromisoformat(date_input.value)
            is_custom = period == "custom"
            custom_row.set_visibility(is_custom)
            date_input.set_visibility(not is_custom)
            custom_range = None
            if is_custom and from_input.value and to_input.value:
                custom_range = (date.fromisoformat(from_input.value), date.fromisoformat(to_input.value))
            render_amount_trend(trend_card, Transaction, Transaction.date, "Spending trend",
                                "show_chart", AMBER, period, ref_date,
                                empty_hint="No spending recorded in this period.", custom_range=custom_range)
            render_expenses(expense_card, period, ref_date, custom_range=custom_range)
            render_nutrition(nutrition_card, period, ref_date, goals, custom_range=custom_range)

        date_input.on_value_change(lambda e: refresh())
        from_input.on_value_change(lambda e: refresh())
        to_input.on_value_change(lambda e: refresh())
        refresh()


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
