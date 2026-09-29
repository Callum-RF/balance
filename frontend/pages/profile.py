"""The profile page: weight, daily targets, budget and the details behind them."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    BudgetTarget,
    Category,
    NutrientGoals,
    UserProfile,
    WeightLog,
)
from backend.routers.forecast import ACTIVITY_MULTIPLIERS, estimate_bmr
from backend.routers.profile import (
    WEIGHT_TREND_WINDOWS,
    calculate_age,
    compute_weight_trend,
)

from ..common import ACTIVITY_LEVEL_OPTIONS, CUR, _category_label
from ..components import (
    card_box,
    date_field,
    empty_state,
    goal_row,
    list_row,
    page_header,
    pill_toggle,
    section_header,
    summary_strip,
    undo_banner,
)
from ..theme import (
    AMBER,
    BORDER,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    RED,
    SKY,
    SURFACE,
    TEXT_DIM,
    VIOLET,
    echart,
)

VIEWS = {"weight": "Weight", "targets": "Targets", "budget": "Budget", "about": "About you"}
SMOOTHING = {"3d": "3 days", "1w": "1 week", "1m": "1 month", "3m": "3 months"}


def _capfield(label, builder):
    """A small caption above a field -- the rhythm every form here shares."""
    with ui.column().classes("gap-1 w-full"):
        ui.label(label).classes("text-xs font-medium").style(f"color:{TEXT_DIM}")
        return builder()


# ---------------------------------------------------------------------------
# Profile & Goals
# ---------------------------------------------------------------------------
def profile_page():
    page_header("Profile & Goals", "Your weight, daily targets and budget -- and the details behind them.")

    @ui.refreshable
    def figures():
        with Session(engine) as s:
            profile = s.exec(select(UserProfile)).first() or UserProfile()
            goals = s.exec(select(NutrientGoals)).first() or NutrientGoals()
            latest = s.exec(select(WeightLog).order_by(WeightLog.date.desc(), WeightLog.id.desc())).first()
            budget = s.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711
        summary_strip([
            ("Weight", f"{latest.weight_kg:.1f} kg" if latest else "—", EMERALD),
            ("Calorie target", f"{goals.calories:,.0f}" if goals.calories else "—", AMBER),
            ("Monthly budget", f"{CUR}{budget.monthly_amount:,.0f}" if budget and budget.monthly_amount else "—", INDIGO),
            ("Age", str(calculate_age(profile.date_of_birth) or "—"), SKY),
        ])

    figures()
    views = {}

    def show(key):
        for k, v in views.items():
            v.classes(remove="b-off") if k == key else v.classes(add="b-off")

    pill_toggle(VIEWS, "weight", show)
    for key in VIEWS:
        views[key] = ui.column().classes("w-full gap-4 sm:gap-6" + ("" if key == "weight" else " b-off"))

    with views["weight"]:
        _weight_view(figures)
    with views["targets"]:
        _targets_view(figures)
    with views["budget"]:
        _budget_view(figures)
    with views["about"]:
        _about_view(figures)


# --- Weight ---------------------------------------------------------------------------
def _weight_view(figures):
    undo_container = ui.column().classes("w-full")
    state = {"window": "1w"}

    with card_box().classes("w-full"):
        section_header("Log a weigh-in")
        with ui.row().classes("w-full items-end gap-3 no-wrap"):
            weight_input = ui.number(placeholder="0.0", format="%.1f").props(
                'dense outlined suffix="kg" input-class="text-2xl font-bold"').classes("flex-1")
            ui.button("Log", icon="add", on_click=lambda: log_weight()).props(
                "unelevated no-caps color=primary").classes("h-12")
        with ui.expansion("Not today?", icon="event").props("dense").classes("w-full"):
            weight_date = date_field("Date", value=date.today().isoformat())

    trend_card = card_box().classes("w-full")
    recent_box = ui.column().classes("w-full gap-0")

    def log_weight():
        if not weight_input.value:
            ui.notify("Enter your weight first.", type="warning")
            return
        entry_date = date.fromisoformat(weight_date.value) if weight_date.value else date.today()
        with Session(engine) as session:
            session.add(WeightLog(date=entry_date, weight_kg=weight_input.value))
            session.commit()
        ui.notify(f"Logged {weight_input.value:.1f} kg.", type="positive")
        weight_input.value = None
        refresh()

    def refresh():
        render_trend()
        render_recent()
        figures.refresh()

    def render_trend():
        trend_card.clear()
        with Session(engine) as session:
            trend = compute_weight_trend(session, WEIGHT_TREND_WINDOWS.get(state["window"], 7))
        with trend_card:
            section_header("Trend", subtitle="Weight bounces daily with water and food -- the line "
                                              "averages it out so the real direction shows")
            if not trend["available"] or trend["num_entries"] < 2:
                empty_state("Log at least two weigh-ins to see your trend.", "show_chart")
                return
            change = trend["change_since_first_kg"]
            summary_strip([
                ("Latest", f"{trend['latest_weight_kg']:.1f} kg", INDIGO),
                ("Trend", f"{trend['latest_rolling_avg_kg']:.1f} kg", VIOLET),
                ("Since first", f"{change:+.1f} kg", EMERALD if change <= 0 else AMBER),
            ])
            pill_toggle(SMOOTHING, state["window"], lambda k: (state.update(window=k), render_trend()))
            pts = trend["points"]
            echart({
                "backgroundColor": "transparent",
                "grid": {"left": 48, "right": 16, "top": 16, "bottom": 28},
                "xAxis": {
                    "type": "category", "data": [f"{p['date'].day} {p['date']:%b}" for p in pts],
                    "boundaryGap": False, "axisLine": {"lineStyle": {"color": BORDER}},
                    "axisLabel": {"color": TEXT_DIM, "fontSize": 10, "hideOverlap": True},
                },
                "yAxis": {
                    "type": "value", "scale": True, "axisLine": {"show": False},
                    "axisLabel": {"color": TEXT_DIM, "formatter": "{value}kg"},
                    "splitLine": {"lineStyle": {"color": BORDER}},
                },
                "tooltip": {"trigger": "axis"},
                "series": [
                    {"name": "Weigh-in", "data": [p["raw_weight_kg"] for p in pts], "type": "line",
                     "lineStyle": {"color": TEXT_DIM, "width": 1, "type": "dotted"},
                     "itemStyle": {"color": TEXT_DIM}, "symbolSize": 4},
                    {"name": "Trend", "data": [p["rolling_avg_kg"] for p in pts], "type": "line", "smooth": True,
                     "lineStyle": {"color": INDIGO, "width": 3}, "itemStyle": {"color": INDIGO},
                     "areaStyle": {"color": "rgba(99,102,241,0.10)"}, "symbolSize": 0},
                ],
            }).classes("w-full h-60")

    def render_recent():
        recent_box.clear()
        with Session(engine) as session:
            recent = session.exec(select(WeightLog).order_by(WeightLog.date.desc(), WeightLog.id.desc())
                                  .limit(11)).all()
        if not recent:
            return
        with recent_box:
            with ui.element("div").classes("b-day"):
                ui.label("Recent weigh-ins")
            with ui.column().classes(LIST_GROUP):
                for i, e in enumerate(recent[:10]):
                    prev = recent[i + 1] if i + 1 < len(recent) else None
                    diff = e.weight_kg - prev.weight_kg if prev else None
                    sub = e.date.strftime("%A %d %B")
                    if diff is not None:
                        sub += " · no change" if abs(diff) < 0.05 else f" · {diff:+.1f} kg"
                    color = EMERALD if diff is not None and diff < -0.05 else (
                        AMBER if diff is not None and diff > 0.05 else INDIGO)
                    list_row("monitor_weight", color, f"{e.weight_kg:.1f} kg", sub, "",
                             lambda _, eid=e.id: open_entry(eid), tooltip="Edit")

    def open_entry(eid):
        with Session(engine) as session:
            e = session.get(WeightLog, eid)
            if not e:
                return
            cur = e.model_dump()
        with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
            section_header("Weigh-in", subtitle=cur["date"].strftime("%A %d %B %Y"))
            e_weight = ui.number(label="Weight", value=cur["weight_kg"], format="%.1f").props(
                'suffix="kg"').classes("w-full")
            e_date = date_field("Date", value=cur["date"].isoformat())

            def save():
                with Session(engine) as session:
                    obj = session.get(WeightLog, eid)
                    if obj:
                        obj.weight_kg = e_weight.value or obj.weight_kg
                        obj.date = date.fromisoformat(e_date.value) if e_date.value else obj.date
                        session.add(obj)
                        session.commit()
                dialog.close()
                refresh()

            def remove():
                dialog.close()
                with Session(engine) as session:
                    obj = session.get(WeightLog, eid)
                    if not obj:
                        return
                    snapshot = obj.model_dump(exclude={"id"})
                    session.delete(obj)
                    session.commit()

                def undo():
                    with Session(engine) as session:
                        session.add(WeightLog(**snapshot))
                        session.commit()
                    refresh()

                refresh()
                undo_banner(undo_container, f"Deleted the {snapshot['weight_kg']:.1f} kg weigh-in.", undo)

            with ui.row().classes("w-full items-center gap-2 mt-2"):
                ui.button("Delete", icon="delete_outline", on_click=remove).props("flat no-caps color=negative")
                ui.space()
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", on_click=save).props("color=primary unelevated no-caps")
        dialog.open()

    render_trend()
    render_recent()


# --- Targets --------------------------------------------------------------------------
def _targets_view(figures):
    with Session(engine) as session:
        goals = session.exec(select(NutrientGoals)).first() or NutrientGoals()
    est = {"dir": "maintain"}

    with card_box().classes("w-full"):
        section_header("Daily targets", subtitle="Tap the ⓘ next to any one for what it does and why it matters")
        with ui.column().classes("w-full gap-2 mb-1"):
            ui.label("Not sure? Estimate them from your details and latest weight, for:").classes(
                "text-xs").style(f"color:{TEXT_DIM}")
            with ui.row().classes("w-full items-center gap-2"):
                pill_toggle({"maintain": "Maintain", "lose": "Lose fat", "gain": "Build muscle"}, "maintain",
                            lambda k: est.update(dir=k))
                ui.button("Estimate", icon="auto_awesome", on_click=lambda: estimate()).props(
                    "flat dense no-caps color=primary")
        with ui.column().classes("w-full gap-0"):
            cal_g = goal_row("Calories", goals.calories, "calories", "kcal", INDIGO)
            protein_g = goal_row("Protein", goals.protein_g, "protein_g", "g", EMERALD)
            carbs_g = goal_row("Carbs", goals.carbs_g, "carbs_g", "g", AMBER)
            fat_g = goal_row("Fat", goals.fat_g, "fat_g", "g", VIOLET)
            fiber_g = goal_row("Fiber", goals.fiber_g, "fiber_g", "g", SKY)
            water_g = goal_row("Water", goals.water_ml, "water_ml", "ml", SKY, last=True)
        with ui.expansion("Daily limits", icon="do_not_disturb_on",
                          caption="Ceilings, not targets -- a day is flagged when it goes over").props(
                "dense").classes("w-full mt-2"):
            with ui.column().classes("w-full gap-0"):
                sugar_lim = goal_row("Added sugar", goals.sugar_limit_g, "sugar_limit_g", "g", RED)
                satfat_lim = goal_row("Saturated fat", goals.saturated_fat_limit_g, "saturated_fat_limit_g", "g", RED)
                transfat_lim = goal_row("Trans fat", goals.trans_fat_limit_g, "trans_fat_limit_g", "g", RED)
                sodium_lim = goal_row("Sodium", goals.sodium_limit_mg, "sodium_limit_mg", "mg", RED)
                alcohol_lim = goal_row("Alcohol", goals.alcohol_limit_g, "alcohol_limit_g", "g", RED)
                caffeine_lim = goal_row("Caffeine", goals.caffeine_limit_mg, "caffeine_limit_mg", "mg", RED, last=True)
        note = ui.label().classes("text-sm")
        with ui.row().classes("w-full justify-end"):
            ui.button("Save targets", on_click=lambda: save()).props("color=primary unelevated no-caps")

    def estimate():
        direction = est["dir"]
        with Session(engine) as session:
            prof = session.exec(select(UserProfile)).first()
            lw = session.exec(select(WeightLog).order_by(WeightLog.date.desc())).first()
        age = calculate_age(prof.date_of_birth) if prof and prof.date_of_birth else None
        height = prof.height_cm if prof else None
        weight = lw.weight_kg if lw else None
        sex = prof.sex if prof else None
        activity = prof.activity_level if prof and prof.activity_level else "moderate"
        missing = [what for what, have in (("a weigh-in", weight), ("your height", height),
                                           ("your date of birth", age is not None)) if not have]
        if missing:
            note.set_text("Add " + ", ".join(missing) + " first (Weight / About you) so I can estimate.")
            note.style(f"color:{AMBER}")
            return
        tdee = estimate_bmr(weight, height, age, sex) * ACTIVITY_MULTIPLIERS.get(activity, 1.55)
        cals, ppk = {"lose": (tdee - 500, 2.0), "gain": (tdee + 350, 2.0)}.get(direction, (tdee, 1.8))
        cals = max(round(cals / 10) * 10, 1200)
        protein = round(weight * ppk)
        fat = round(cals * 0.25 / 9)
        cal_g.value, protein_g.value, fat_g.value = cals, protein, fat
        carbs_g.value = max(round((cals - protein * 4 - fat * 9) / 4), 0)
        fiber_g.value = round(cals / 1000 * 14)
        water_g.value = int(round(weight * 35 / 50) * 50)
        label = {"maintain": "maintaining", "lose": "losing fat", "gain": "building muscle"}[direction]
        note.set_text(f"Estimated for {label} at your activity level -- review, then Save.")
        note.style(f"color:{EMERALD}")

    def save():
        with Session(engine) as session:
            g = session.exec(select(NutrientGoals)).first() or NutrientGoals()
            g.calories, g.protein_g, g.carbs_g = cal_g.value, protein_g.value, carbs_g.value
            g.fat_g, g.fiber_g, g.water_ml = fat_g.value, fiber_g.value, water_g.value
            g.sugar_limit_g, g.saturated_fat_limit_g = sugar_lim.value, satfat_lim.value
            g.trans_fat_limit_g, g.sodium_limit_mg = transfat_lim.value, sodium_lim.value
            g.alcohol_limit_g, g.caffeine_limit_mg = alcohol_lim.value, caffeine_lim.value
            session.add(g)
            session.commit()
        note.set_text("")
        ui.notify("Targets saved.", type="positive")
        figures.refresh()


# --- Budget ---------------------------------------------------------------------------
def _budget_view(figures):
    with Session(engine) as session:
        overall = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711

    with card_box().classes("w-full"):
        section_header("Monthly budget", subtitle="Your whole month's spending -- the bar on the dashboard")
        with ui.row().classes("w-full items-end gap-3 no-wrap"):
            budget_input = ui.number(value=overall.monthly_amount if overall else None, format="%.2f").props(
                f'dense outlined prefix="{CUR}" input-class="text-2xl font-bold"').classes("flex-1")

            def save_budget():
                with Session(engine) as session:
                    t = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711
                    t = t or BudgetTarget(category_id=None, monthly_amount=0)
                    t.monthly_amount = budget_input.value or 0
                    session.add(t)
                    session.commit()
                ui.notify("Budget saved.", type="positive")
                figures.refresh()

            ui.button("Save", on_click=save_budget).props("unelevated no-caps color=primary").classes("h-12")

    per_cat = ui.column().classes("w-full gap-0")

    def render_categories():
        per_cat.clear()
        with Session(engine) as session:
            targets = session.exec(select(BudgetTarget).where(BudgetTarget.category_id != None)).all()  # noqa: E711
            all_cats = session.exec(select(Category)).all()
        cats_by_id = {c.id: c for c in all_cats}
        budgeted = {t.category_id for t in targets}
        available = [c for c in all_cats if c.id not in budgeted]
        with per_cat:
            with ui.element("div").classes("b-day"):
                ui.label("Per-category budgets")
                ui.label("optional")
            if targets:
                with ui.column().classes(LIST_GROUP):
                    for t in sorted(targets, key=lambda t: _category_label(cats_by_id[t.category_id], all_cats)):
                        with ui.element("div").classes("b-row").style("cursor:default"):
                            with ui.element("div").classes("b-row-text"):
                                ui.label(_category_label(cats_by_id[t.category_id], all_cats)).classes("b-row-title")
                            amount = ui.number(value=t.monthly_amount, format="%.2f").props(
                                f'dense outlined prefix="{CUR}" input-class="text-right"').classes("w-32")
                            amount.on("blur", lambda e, tid=t.id, a=amount: save_one(tid, a.value))
                            ui.button(icon="close", on_click=lambda _, tid=t.id: delete_one(tid)).props(
                                "flat round dense").classes("b-icon-btn").tooltip("Remove")
            ui.label("Caps one category instead of your whole spend; each gets its own bar on the dashboard. "
                     "Changes save as you leave the field.").classes("b-hint")
            if available:
                with ui.row().classes("w-full items-end gap-2 mt-2 no-wrap"):
                    new_cat = ui.select({c.id: _category_label(c, all_cats) for c in available},
                                        label="Add a category").props("dense options-dense").classes("flex-1 min-w-0")
                    new_amt = ui.number(label=f"{CUR} / month", format="%.2f").props("dense").classes("w-28")
                    ui.button("Add", icon="add", on_click=lambda: add_one(new_cat.value, new_amt.value)).props(
                        "flat dense no-caps color=primary")

    def save_one(tid, value):
        with Session(engine) as session:
            t = session.get(BudgetTarget, tid)
            if t and t.monthly_amount != (value or 0):
                t.monthly_amount = value or 0
                session.add(t)
                session.commit()
                ui.notify("Saved.", type="positive")

    def delete_one(tid):
        with Session(engine) as session:
            t = session.get(BudgetTarget, tid)
            if t:
                session.delete(t)
                session.commit()
        render_categories()

    def add_one(cat_id, amount):
        if not cat_id:
            return
        with Session(engine) as session:
            session.add(BudgetTarget(category_id=cat_id, monthly_amount=amount or 0))
            session.commit()
        render_categories()

    render_categories()


# --- About you ------------------------------------------------------------------------
def _about_view(figures):
    with Session(engine) as session:
        profile = session.exec(select(UserProfile)).first() or UserProfile()

    with card_box().classes("w-full"):
        section_header("About you", subtitle="Used to estimate your maintenance calories and targets")
        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3 items-start"):
            dob_input = date_field("Date of birth",
                                   value=profile.date_of_birth.isoformat() if profile.date_of_birth else None)
            height_input = _capfield("Height (cm)", lambda: ui.number(value=profile.height_cm).props(
                "dense outlined").classes("w-full"))
            sex_select = _capfield("Sex", lambda: ui.select(["male", "female", "other"], value=profile.sex).props(
                "dense outlined options-dense").classes("w-full"))
            activity_select = _capfield("Activity level", lambda: ui.select(
                ACTIVITY_LEVEL_OPTIONS, value=profile.activity_level).props(
                "dense outlined options-dense").classes("w-full"))

        def save_profile():
            with Session(engine) as session:
                p = session.exec(select(UserProfile)).first() or UserProfile()
                p.date_of_birth = date.fromisoformat(dob_input.value) if dob_input.value else None
                p.height_cm = height_input.value
                p.sex = sex_select.value
                p.activity_level = activity_select.value
                session.add(p)
                session.commit()
            ui.notify("Saved.", type="positive")
            figures.refresh()

        with ui.row().classes("w-full justify-end"):
            ui.button("Save", on_click=save_profile).props("color=primary unelevated no-caps")
