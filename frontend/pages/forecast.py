"""The forecast page."""

from nicegui import ui
from sqlmodel import Session

from backend.database import engine
from backend.routers.forecast import compute_forecast

from ..common import CUR
from ..components import (
    card_box,
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
    TEXT_DIM,
    VIOLET,
    echart,
)


# ---------------------------------------------------------------------------
# Caloric ROI Forecast
# ---------------------------------------------------------------------------
def forecast_page():
    page_header("Forecast",
                "Where your weight and spending are headed if your last 30 days continue.",
                icon="insights")

    months_select = ui.select({1: "1 month", 6: "6 months", 12: "12 months"}, value=6, label="Time horizon").props("dense options-dense").classes("w-48")
    forecast_container = ui.column().classes("w-full gap-4")

    def render():
        forecast_container.clear()
        with Session(engine) as session:
            result = compute_forecast(session, months_select.value)

        with forecast_container:
            if not result["available"]:
                with card_box().classes("w-full"):
                    section_header("Missing info needed for a forecast", icon="info", icon_color=AMBER, accent=AMBER)
                    missing = ", ".join(result["missing_fields"])
                    ui.label(f"Add the following on the Profile & Goals page: {missing}.").classes("text-sm").style(f"color:{TEXT_DIM}")
                    ui.link("Go to Profile & Goals", "/profile").classes("no-underline text-sm mt-2").style(f"color:{INDIGO}")
                return

            with ui.expansion("How this is calculated", icon="info").props("dense").classes("w-full"):
                ui.label(
                    "Maintenance calories are estimated with the Mifflin-St Jeor formula, scaled by your "
                    "activity level -- a population-average estimate, not a measurement of your actual "
                    "metabolism (real TDEE commonly varies ±10-20% between people with identical stats). "
                    "\"Recent habits\" means your trailing 30-day daily average calories and spending. Weight "
                    "change is projected using the standard ~7,700 kcal ≈ 1kg rule of thumb. This is a "
                    "projection of current trends, not a guarantee, medical advice, or financial advice."
                ).classes("text-xs").style(f"color:{TEXT_DIM}")

            calib = result.get("calibrated")
            activity_short = result["activity_level"].replace("_", " ")
            if result.get("tdee_source") == "calibrated":
                maint_sub, maint_color = "calibrated from your own data", VIOLET
            else:
                maint_sub, maint_color = f"BMR {result['bmr']:,.0f} × {activity_short} activity (formula)", INDIGO
            delta = result["daily_calorie_delta"]
            delta_label = f"{delta:+,.0f} kcal/day" if delta else "0 kcal/day"
            summary_strip([
                ("Maintenance", f"{result['tdee']:,.0f} kcal", maint_color, maint_sub),
                ("You eat", f"{result['avg_daily_calories']:,.0f} kcal", EMERALD if delta <= 0 else AMBER,
                 f"{delta_label} vs. maintenance"),
                ("You spend", f"{CUR}{result['avg_daily_spend']:,.2f}/day", SKY, "trailing 30-day average"),
            ])

            if calib:
                with card_box().classes("w-full"):
                    section_header("Calibrated to your metabolism", icon="science", icon_color=VIOLET,
                                   subtitle="Measured from your own logs, not a population-average formula.")
                    ui.label(
                        f"Over {calib['span_days']} days your weight changed {calib['weight_change_kg']:+.2f} kg while "
                        f"averaging {calib['avg_intake']:,.0f} kcal/day (across {calib['logged_days']} logged days). "
                        f"By energy balance that implies a real maintenance of ~{calib['tdee']:,.0f} kcal/day, versus the "
                        f"formula's {result['tdee_formula']:,.0f}. The projection below uses this calibrated figure."
                    ).classes("text-xs").style(f"color:{TEXT_DIM}")
            else:
                with card_box().classes("w-full py-3").style(f"background:{SURFACE_2}"):
                    ui.label(
                        "Tip: log your weight and food for a couple of weeks and this switches to a maintenance "
                        "figure calibrated from your actual data instead of the formula."
                    ).classes("text-xs").style(f"color:{TEXT_DIM}")

            # --- weight projection ---
            with card_box().classes("w-full"):
                change = result["projected_weight_change_kg"]
                direction = "loss" if change < 0 else ("gain" if change > 0 else "change")
                color = EMERALD if change <= 0 else AMBER
                section_header(f"Projected weight {direction}", icon="monitor_weight", icon_color=color)
                ui.label(
                    f"{result['current_weight_kg']:.1f}kg → {result['projected_end_weight_kg']:.1f}kg "
                    f"over {result['months']} month(s) ({change:+.1f}kg)"
                ).style(f"color:{color}").classes("text-sm mb-2")

                months_list = [w["month"] for w in result["weight_series"]]
                weights = [w["projected_weight_kg"] for w in result["weight_series"]]
                echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 50, "right": 20, "top": 20, "bottom": 30},
                    "xAxis": {
                        "type": "category", "data": [f"M{m}" for m in months_list],
                        "axisLine": {"lineStyle": {"color": BORDER}},
                        "axisLabel": {"color": TEXT_DIM, "fontSize": 10},
                    },
                    "yAxis": {
                        "type": "value", "scale": True,   # weight moves in kg, not from zero
                        "axisLine": {"show": False},
                        "axisLabel": {"color": TEXT_DIM, "formatter": "{value}kg"},
                        "splitLine": {"lineStyle": {"color": BORDER}},
                    },
                    "tooltip": {"trigger": "axis"},
                    "series": [{
                        "data": weights, "type": "line", "smooth": True,
                        "lineStyle": {"color": color, "width": 3},
                        "itemStyle": {"color": color},
                        "areaStyle": {"color": "rgba(52,211,153,0.12)" if change <= 0 else "rgba(245,158,11,0.12)"},
                    }],
                }).classes("w-full h-56")

            # --- spending projection ---
            with card_box().classes("w-full"):
                section_header("Projected spending", icon="savings", icon_color=SKY)
                spend_line = f"{CUR}{result['projected_total_spend']:,.2f} over {result['months']} month(s) at your recent pace"
                ui.label(spend_line).classes("text-sm mb-2").style(f"color:{TEXT_DIM}")

                if result["projected_budget_pace"] is not None:
                    over_under = result["projected_over_under_budget"]
                    budget_color = RED if over_under > 0 else EMERALD
                    verb = "over" if over_under > 0 else "under"
                    ui.label(
                        f"{CUR}{abs(over_under):,.2f} {verb} your budget pace of {CUR}{result['projected_budget_pace']:,.2f} "
                        f"({CUR}{result['monthly_budget_target']:,.2f}/month target)"
                    ).style(f"color:{budget_color}").classes("text-sm mb-2")
                else:
                    ui.label("Set a monthly budget target on Profile & Goals to compare against.").classes("text-xs").style(f"color:{TEXT_DIM}")

                spend_months = [s["month"] for s in result["spend_series"]]
                cumulative = [s["cumulative_spend"] for s in result["spend_series"]]
                series = [{
                    "name": "Projected spend", "data": cumulative, "type": "line", "smooth": True,
                    "lineStyle": {"color": INDIGO, "width": 3},
                    "itemStyle": {"color": INDIGO},
                    "areaStyle": {"color": "rgba(99,102,241,0.12)"},
                }]
                if result["projected_budget_pace"] is not None:
                    budget_line = [round(result["monthly_budget_target"] * m, 2) for m in spend_months]
                    series.append({
                        "name": "Budget pace", "data": budget_line, "type": "line",
                        "lineStyle": {"color": TEXT_DIM, "width": 2, "type": "dashed"},
                        "itemStyle": {"color": TEXT_DIM},
                    })
                echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 60, "right": 20, "top": 20, "bottom": 30},
                    "xAxis": {
                        "type": "category", "data": [f"M{m}" for m in spend_months],
                        "axisLine": {"lineStyle": {"color": BORDER}},
                        "axisLabel": {"color": TEXT_DIM, "fontSize": 10},
                    },
                    "yAxis": {
                        "type": "value",
                        "axisLine": {"show": False},
                        "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                        "splitLine": {"lineStyle": {"color": BORDER}},
                    },
                    "tooltip": {"trigger": "axis"},
                    "series": series,
                }).classes("w-full h-56")

    months_select.on_value_change(lambda e: render())
    render()
