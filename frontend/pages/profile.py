"""The profile page."""
import json
from datetime import date, datetime

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    AppSettings,
    BudgetTarget,
    Category,
    FoodLog,
    Income,
    NutrientGoals,
    PantryItem,
    PriceObservation,
    Subscription,
    Transaction,
    UserProfile,
    WaterLog,
    WeightLog,
)
from backend.routers.forecast import ACTIVITY_MULTIPLIERS, estimate_bmr
from backend.routers.profile import WEIGHT_TREND_WINDOWS, calculate_age, compute_weight_trend
from backend.timeutil import utcnow

from ..common import ACTIVITY_LEVEL_OPTIONS, CUR, _category_label
from ..components import (
    card_box,
    date_field,
    goal_row,
    page_header,
    section_header,
    summary_strip,
)
from ..theme import (
    AMBER,
    BORDER,
    EMERALD,
    INDIGO,
    RED,
    SKY,
    SURFACE_2,
    TEXT,
    TEXT_DIM,
    VIOLET,
    echart,
)


# ---------------------------------------------------------------------------
# Profile & Goals
# ---------------------------------------------------------------------------
def profile_page():
    page_header("Profile & Goals", "Your details, targets and weight — what the reference calcs use.", icon="badge")

    with Session(engine) as session:
        profile = session.exec(select(UserProfile)).first() or UserProfile()
        goals = session.exec(select(NutrientGoals)).first() or NutrientGoals()
        overall_budget = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711

    # Shared caption-above field wrapper -- a small caption in TEXT_DIM sitting
    # above a light outlined input, used across every card on the page so the
    # form fields share one rhythm instead of each card inventing its own.
    def capfield(label, builder):
        with ui.column().classes("gap-1 w-full"):
            ui.label(label).classes("text-xs font-medium").style(f"color:{TEXT_DIM}")
            return builder()

    age = calculate_age(profile.date_of_birth)
    with Session(engine) as _s:
        latest_w = _s.exec(select(WeightLog).order_by(WeightLog.date.desc())).first()

    summary_strip([
        ("Age", str(age) if age else "—", INDIGO),
        ("Height", f"{profile.height_cm:.0f} cm" if profile.height_cm else "—", SKY),
        ("Latest weight", f"{latest_w.weight_kg:.1f} kg" if latest_w else "—", EMERALD),
        ("Calorie target", f"{goals.calories:,.0f}" if goals.calories else "—", AMBER),
    ], width_class="max-w-2xl")

    with card_box().classes("w-full max-w-2xl").style(f"border-left:3px solid {INDIGO}"):
        section_header("About you", icon="person", icon_color=INDIGO)

        # Caption-above layout so the grid columns line up (date_field is already
        # caption-above; the others were floating-label at a different height).
        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3 items-start"):
            dob_input = date_field("Date of birth", value=profile.date_of_birth.isoformat() if profile.date_of_birth else None)
            height_input = capfield("Height (cm)", lambda: ui.number(value=profile.height_cm).props("dense outlined").classes("w-full"))
            sex_select = capfield("Sex", lambda: ui.select(["male", "female", "other"], value=profile.sex).props("dense outlined options-dense").classes("w-full"))
            activity_select = capfield("Activity level", lambda: ui.select(ACTIVITY_LEVEL_OPTIONS, value=profile.activity_level).props("dense outlined options-dense").classes("w-full"))
        profile_result = ui.label().classes("text-sm").style(f"color:{EMERALD}")

        def save_profile():
            with Session(engine) as session:
                p = session.exec(select(UserProfile)).first() or UserProfile()
                p.date_of_birth = date.fromisoformat(dob_input.value) if dob_input.value else None
                p.height_cm = height_input.value
                p.sex = sex_select.value
                p.activity_level = activity_select.value
                session.add(p)
                session.commit()
            profile_result.set_text("Saved!")

        with ui.row().classes("w-full justify-end mt-1"):
            ui.button("Save profile", on_click=save_profile).props("color=primary unelevated no-caps")

    ui.separator().classes("w-full max-w-2xl my-4").style(f"background:{BORDER}")
    with ui.column().classes("w-full max-w-2xl gap-3"):
        section_header("Weight", icon="monitor_weight", icon_color=EMERALD)

        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3 items-start max-w-md"):
            weight_date_input = date_field("Date", value=date.today().isoformat())
            weight_input = capfield("Weight (kg)", lambda: ui.number().props("dense outlined").classes("w-full"))
        weight_result = ui.label().classes("text-sm").style(f"color:{EMERALD}")

        weight_chart_container = ui.column().classes("w-full gap-2 mt-3")
        weight_list_container = ui.column().classes("w-full gap-1 mt-3")

        def log_weight():
            with Session(engine) as session:
                entry_date = date.fromisoformat(weight_date_input.value) if weight_date_input.value else date.today()
                session.add(WeightLog(date=entry_date, weight_kg=weight_input.value or 0))
                session.commit()
            weight_result.set_text("Logged!")
            weight_input.value = None
            render_weight_chart()
            render_weight_list()

        with ui.row().classes("w-full justify-end mt-1"):
            ui.button("Log weight", on_click=log_weight).props("color=primary unelevated no-caps")

        window_options = {"1d": "1 day", "3d": "3 day", "1w": "1 week", "1m": "1 month",
                           "3m": "3 month", "6m": "6 month", "1y": "1 year"}
        window_select = ui.select(window_options, value="1w", label="Trend smoothing").props("dense outlined options-dense").classes("w-40 mt-3")
        ui.label(
            "Body weight bounces daily from water and food -- this averages readings over the "
            "selected window so the real trend is easier to see than the raw scale number alone."
        ).classes("text-xs").style(f"color:{TEXT_DIM}")

        def render_weight_chart():
            weight_chart_container.clear()
            with Session(engine) as session:
                trend = compute_weight_trend(session, WEIGHT_TREND_WINDOWS.get(window_select.value, 7))

            with weight_chart_container:
                if not trend["available"] or trend["num_entries"] < 2:
                    # Compact placeholder rather than a tall empty chart void: a
                    # centred hint in a dashed frame that fills only what it needs.
                    with ui.column().classes(
                            "w-full items-center justify-center gap-1 py-6 rounded-xl").style(
                            f"border:1px dashed {BORDER}"):
                        ui.icon("show_chart").classes("text-3xl").style(f"color:{TEXT_DIM}")
                        ui.label("Log at least two weigh-ins to see your trend.").classes(
                            "text-sm").style(f"color:{TEXT_DIM}")
                    return

                change = trend["change_since_first_kg"]
                color = EMERALD if change <= 0 else AMBER
                with ui.row().classes("gap-8 mb-2"):
                    with ui.column().classes("gap-0"):
                        ui.label("Latest").classes("text-xs").style(f"color:{TEXT_DIM}")
                        ui.label(f"{trend['latest_weight_kg']:.1f}kg").classes("text-xl font-bold")
                    with ui.column().classes("gap-0"):
                        ui.label("Trend average").classes("text-xs").style(f"color:{TEXT_DIM}")
                        ui.label(f"{trend['latest_rolling_avg_kg']:.1f}kg").classes("text-xl font-bold")
                    with ui.column().classes("gap-0"):
                        ui.label("Since first log").classes("text-xs").style(f"color:{TEXT_DIM}")
                        ui.label(f"{change:+.1f}kg").classes("text-xl font-bold").style(f"color:{color}")

                dates = [p["date"].isoformat() for p in trend["points"]]
                raw = [p["raw_weight_kg"] for p in trend["points"]]
                smoothed = [p["rolling_avg_kg"] for p in trend["points"]]
                echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 50, "right": 20, "top": 20, "bottom": 40},
                    "xAxis": {
                        "type": "category", "data": dates, "boundaryGap": False,
                        "axisLine": {"lineStyle": {"color": BORDER}},
                        "axisLabel": {"color": TEXT_DIM, "fontSize": 9, "rotate": 45},
                    },
                    "yAxis": {
                        "type": "value", "scale": True,
                        "axisLine": {"show": False},
                        "axisLabel": {"color": TEXT_DIM, "formatter": "{value}kg"},
                        "splitLine": {"lineStyle": {"color": BORDER}},
                    },
                    "tooltip": {"trigger": "axis"},
                    "series": [
                        {
                            "name": "Raw", "data": raw, "type": "line", "smooth": False,
                            "lineStyle": {"color": TEXT_DIM, "width": 1, "type": "dotted"},
                            "itemStyle": {"color": TEXT_DIM},
                            "symbolSize": 4,
                        },
                        {
                            "name": "Trend", "data": smoothed, "type": "line", "smooth": True,
                            "lineStyle": {"color": INDIGO, "width": 3},
                            "itemStyle": {"color": INDIGO},
                            "areaStyle": {"color": "rgba(99,102,241,0.10)"},
                            "symbolSize": 0,
                        },
                    ],
                }).classes("w-full h-64")

        window_select.on_value_change(lambda e: render_weight_chart())
        render_weight_chart()

        def render_weight_list():
            weight_list_container.clear()
            with Session(engine) as session:
                recent = session.exec(select(WeightLog).order_by(WeightLog.date.desc()).limit(10)).all()
            with weight_list_container:
                if not recent:
                    return
                with ui.expansion(f"Recent entries ({len(recent)})").classes("w-full"):
                    for entry in recent:
                        with ui.row().classes("w-full items-center justify-between py-1"):
                            ui.label(f"{entry.date} — {entry.weight_kg:.1f}kg").classes("text-sm")
                            ui.button(icon="delete", on_click=lambda _, eid=entry.id: delete_weight_entry(eid)).props("flat round dense color=red")

        def delete_weight_entry(entry_id):
            with Session(engine) as session:
                entry = session.get(WeightLog, entry_id)
                if entry:
                    session.delete(entry)
                    session.commit()
            render_weight_chart()
            render_weight_list()

        render_weight_list()

    ui.separator().classes("w-full max-w-2xl my-4").style(f"background:{BORDER}")
    with card_box().classes("w-full max-w-2xl").style(f"border-left:3px solid {INDIGO}"):
        section_header("Daily nutrient goals", icon="flag", icon_color=INDIGO,
                       subtitle="Tap the ⓘ next to any field for what it does and why it matters.")
        # Just-in-time estimate: fill the fields from the profile + latest weight
        # rather than entering them by hand. Pick a direction, tap Estimate, review, Save.
        with ui.row().classes("w-full items-center gap-x-2 gap-y-1 flex-wrap mb-3"):
            ui.label("Estimate for").classes("text-xs shrink-0").style(f"color:{TEXT_DIM}")
            est_dir = ui.toggle({"maintain": "Maintain", "lose": "Lose fat", "gain": "Build muscle"},
                                value="maintain").props(
                "no-caps unelevated dense toggle-color=primary").classes(
                "seg-toggle text-xs overflow-hidden").style(
                f"border:1px solid {BORDER}; border-radius:999px; background:{SURFACE_2};")
            est_btn = ui.button("Estimate", icon="auto_awesome").props("flat dense no-caps color=primary")
        with ui.column().classes("w-full gap-0 mt-1"):
            cal_g = goal_row("Calories", goals.calories, "calories", "kcal", INDIGO)
            protein_g = goal_row("Protein", goals.protein_g, "protein_g", "g", EMERALD)
            carbs_g = goal_row("Carbs", goals.carbs_g, "carbs_g", "g", AMBER)
            fat_g = goal_row("Fat", goals.fat_g, "fat_g", "g", VIOLET)
            fiber_g = goal_row("Fiber", goals.fiber_g, "fiber_g", "g", SKY)
            water_g = goal_row("Water", goals.water_ml, "water_ml", "ml", SKY, last=True)

        with ui.expansion("Daily limits", icon="do_not_disturb_on").props("dense").classes("w-full mt-3"):
            ui.label("Ceilings, not targets — a day is flagged when it goes over.").classes(
                "text-xs mb-1").style(f"color:{TEXT_DIM}")
            with ui.column().classes("w-full gap-0"):
                sugar_lim = goal_row("Added sugar", goals.sugar_limit_g, "sugar_limit_g", "g", RED)
                satfat_lim = goal_row("Saturated fat", goals.saturated_fat_limit_g, "saturated_fat_limit_g", "g", RED)
                transfat_lim = goal_row("Trans fat", goals.trans_fat_limit_g, "trans_fat_limit_g", "g", RED)
                sodium_lim = goal_row("Sodium", goals.sodium_limit_mg, "sodium_limit_mg", "mg", RED)
                alcohol_lim = goal_row("Alcohol", goals.alcohol_limit_g, "alcohol_limit_g", "g", RED)
                caffeine_lim = goal_row("Caffeine", goals.caffeine_limit_mg, "caffeine_limit_mg", "mg", RED, last=True)
        goals_result = ui.label().style(f"color:{EMERALD}").classes("mt-2")

        def _estimate_targets():
            direction = est_dir.value
            with Session(engine) as session:
                prof = session.exec(select(UserProfile)).first()
                lw = session.exec(select(WeightLog).order_by(WeightLog.date.desc())).first()
            age = calculate_age(prof.date_of_birth) if prof and prof.date_of_birth else None
            height = prof.height_cm if prof else None
            weight = lw.weight_kg if lw else None
            sex = prof.sex if prof else None
            activity = prof.activity_level if prof and prof.activity_level else "moderate"
            missing = []
            if not weight: missing.append("a weight entry")
            if not height: missing.append("height")
            if age is None: missing.append("date of birth")
            if missing:
                goals_result.set_text("Add " + ", ".join(missing) + " above so I can estimate.")
                goals_result.style(f"color:{AMBER}")
                return
            tdee = estimate_bmr(weight, height, age, sex) * ACTIVITY_MULTIPLIERS.get(activity, 1.55)
            if direction == "lose":
                cals, ppk = tdee - 500, 2.0
            elif direction == "gain":
                cals, ppk = tdee + 350, 2.0
            else:
                cals, ppk = tdee, 1.8
            cals = max(round(cals / 10) * 10, 1200)
            protein = round(weight * ppk)
            fat = round(cals * 0.25 / 9)
            cal_g.value = cals
            protein_g.value = protein
            fat_g.value = fat
            carbs_g.value = max(round((cals - protein * 4 - fat * 9) / 4), 0)
            fiber_g.value = round(cals / 1000 * 14)
            water_g.value = int(round(weight * 35 / 50) * 50)
            goals_result.set_text(f"Estimated for '{direction}' at {activity} activity — review and Save.")
            goals_result.style(f"color:{EMERALD}")

        est_btn.on("click", lambda: _estimate_targets())

        def save_goals():
            with Session(engine) as session:
                g = session.exec(select(NutrientGoals)).first() or NutrientGoals()
                g.calories = cal_g.value
                g.protein_g = protein_g.value
                g.carbs_g = carbs_g.value
                g.fat_g = fat_g.value
                g.fiber_g = fiber_g.value
                g.water_ml = water_g.value
                g.sugar_limit_g = sugar_lim.value
                g.saturated_fat_limit_g = satfat_lim.value
                g.trans_fat_limit_g = transfat_lim.value
                g.sodium_limit_mg = sodium_lim.value
                g.alcohol_limit_g = alcohol_lim.value
                g.caffeine_limit_mg = caffeine_lim.value
                session.add(g)
                session.commit()
            goals_result.set_text("Saved!")

        with ui.row().classes("w-full justify-end mt-1"):
            ui.button("Save goals", on_click=save_goals).props("color=primary unelevated no-caps")

    ui.separator().classes("w-full max-w-2xl my-4").style(f"background:{BORDER}")
    with ui.column().classes("w-full max-w-2xl gap-3"):
        section_header("Monthly budget target", icon="account_balance_wallet", icon_color=AMBER)
        budget_input = capfield(
            f"Overall monthly budget ({CUR})",
            lambda: ui.number(value=overall_budget.monthly_amount if overall_budget else None).props("dense outlined").classes("w-full max-w-xs"))
        budget_result = ui.label().classes("text-sm").style(f"color:{EMERALD}")

        def save_budget():
            with Session(engine) as session:
                target = session.exec(select(BudgetTarget).where(BudgetTarget.category_id == None)).first()  # noqa: E711
                if not target:
                    target = BudgetTarget(category_id=None, monthly_amount=budget_input.value or 0)
                else:
                    target.monthly_amount = budget_input.value or 0
                session.add(target)
                session.commit()
            budget_result.set_text("Saved!")

        with ui.row().classes("w-full justify-end mt-1"):
            ui.button("Save budget", on_click=save_budget).props("color=primary unelevated no-caps")

        with ui.expansion("Per-category budgets", icon="tune").props("dense").classes("w-full mt-1"):
            ui.label(
                "Optional -- caps a specific category instead of your whole spend, shown as its "
                "own progress bar on the dashboard alongside the overall budget above."
            ).classes("text-xs mb-1").style(f"color:{TEXT_DIM}")
            budget_section = ui.column().classes("w-full gap-2")

        def render_budget_section():
            budget_section.clear()
            with Session(engine) as session:
                targets = session.exec(select(BudgetTarget).where(BudgetTarget.category_id != None)).all()  # noqa: E711
                all_cats = session.exec(select(Category)).all()
            cats_by_id = {c.id: c for c in all_cats}
            budgeted_ids = {t.category_id for t in targets}
            available = [c for c in all_cats if c.id not in budgeted_ids]

            with budget_section:
                if not targets:
                    ui.label("No category budgets set yet.").classes("text-xs").style(f"color:{TEXT_DIM}")
                else:
                    for target in sorted(targets, key=lambda t: _category_label(cats_by_id[t.category_id], all_cats)):
                        category = cats_by_id[target.category_id]
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            ui.label(_category_label(category, all_cats)).classes("text-sm flex-1 min-w-0 truncate")
                            amount_input = ui.number(value=target.monthly_amount, format="%.2f").props("dense").classes("w-28 shrink-0")

                            def save_one(target_id=target.id, amount_input=amount_input):
                                with Session(engine) as session:
                                    t = session.get(BudgetTarget, target_id)
                                    t.monthly_amount = amount_input.value or 0
                                    session.add(t)
                                    session.commit()

                            def delete_one(target_id=target.id):
                                with Session(engine) as session:
                                    t = session.get(BudgetTarget, target_id)
                                    session.delete(t)
                                    session.commit()
                                render_budget_section()

                            ui.button(icon="save", on_click=save_one).props("flat dense round color=primary")
                            ui.button(icon="delete", on_click=delete_one).props("flat dense round color=red")

                if available:
                    with ui.row().classes("w-full items-end gap-2 mt-1 no-wrap"):
                        new_category_select = ui.select(
                            {c.id: _category_label(c, all_cats) for c in available}, label="Category"
                        ).props("dense options-dense").classes("flex-1 min-w-0")
                        new_amount_input = ui.number(label=f"{CUR} / month", format="%.2f").props("dense").classes("w-28 shrink-0")

                        def add_one():
                            if not new_category_select.value:
                                return
                            with Session(engine) as session:
                                session.add(BudgetTarget(
                                    category_id=new_category_select.value,
                                    monthly_amount=new_amount_input.value or 0,
                                ))
                                session.commit()
                            render_budget_section()

                        ui.button("Add", icon="add", on_click=add_one).props("flat dense no-caps")
                else:
                    ui.label("All categories have a budget set.").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")

        render_budget_section()

    ui.separator().classes("w-full max-w-2xl my-4").style(f"background:{BORDER}")
    with ui.column().classes("w-full max-w-2xl gap-3"):
        section_header("Backup", icon="cloud_download", icon_color=SKY,
                       subtitle="Everything in one JSON file -- transactions, income, food, water, weight, pantry, subscriptions, prices, budgets, goals, profile.")

        def export_backup():
            tables = {
                "transactions": Transaction, "income": Income, "food_log": FoodLog,
                "water_log": WaterLog, "weight_log": WeightLog, "pantry": PantryItem,
                "subscriptions": Subscription, "prices": PriceObservation,
                "budgets": BudgetTarget, "categories": Category,
                "profile": UserProfile, "goals": NutrientGoals, "settings": AppSettings,
            }
            payload = {"exported_at": utcnow().isoformat(), "app": "balance", "version": 1}
            with Session(engine) as session:
                for name, model in tables.items():
                    rows = session.exec(select(model)).all()
                    payload[name] = [
                        {k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
                         for k, v in r.model_dump().items()}
                        for r in rows
                    ]
            content = json.dumps(payload, indent=1)
            ui.download.content(content.encode("utf-8"), f"balance-backup-{date.today().isoformat()}.json", "application/json")
            ui.notify("Backup downloaded.", type="positive")

        ui.button("Download full backup", icon="download", on_click=export_backup).props("outline no-caps color=primary")
        ui.label(
            "Receipt photos live in data/receipts/ and aren't included -- copy that folder alongside this file for a complete backup."
        ).classes("text-xs").style(f"color:{TEXT_DIM}")

        ui.separator().classes("my-2").style(f"background:{BORDER}")
        ui.label("Automatic off-machine backups").classes("text-sm font-semibold").style(f"color:{TEXT}")
        with Session(engine) as _s:
            _mirror_now = _s.exec(select(AppSettings)).first()
        mirror_input = ui.input(
            label="Backup folder (optional)",
            value=(_mirror_now.backup_mirror_path if _mirror_now else "") or "",
            placeholder="e.g. D:\\Backups\\Balance, or a cloud-synced folder",
        ).props("dense clearable").classes("w-full")

        def save_mirror():
            path = (mirror_input.value or "").strip() or None
            with Session(engine) as session:
                row = session.exec(select(AppSettings)).first()
                row.backup_mirror_path = path
                session.add(row)
                session.commit()
            ui.notify("Off-machine backups enabled." if path else "Off-machine backups disabled.",
                      type="positive")

        ui.button("Save backup folder", icon="save", on_click=save_mirror).props("flat dense no-caps")
        ui.label(
            "The app already snapshots your database daily to data/backups/. Set a folder on a second drive or a "
            "cloud-synced location here and each snapshot is copied there too, so a single disk failure can't lose everything."
        ).classes("text-xs").style(f"color:{TEXT_DIM}")
