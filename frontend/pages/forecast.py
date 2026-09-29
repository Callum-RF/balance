"""The forecast page: where weight and spending head if the last 30 days continue."""
from datetime import date

from nicegui import ui
from sqlmodel import Session

from backend.database import engine
from backend.routers.forecast import compute_forecast

from ..common import CUR
from ..components import (
    card_box,
    card_box_accent,
    page_header,
    pill_toggle,
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
    TEXT_DIM,
    VIOLET,
    echart,
)

HORIZONS = {1: "1 month", 6: "6 months", 12: "1 year"}


def _month_labels(months):
    """'Now', then the real month names -- clearer than M1, M2..."""
    today = date.today()
    labels = []
    for m in range(months + 1):
        y, mo = divmod(today.month - 1 + m, 12)
        d = date(today.year + y, mo + 1, 1)
        labels.append("Now" if m == 0 else d.strftime("%b %y" if months > 6 else "%b"))
    return labels


def _line_chart(labels, series, y_format, scale=False):
    return echart({
        "backgroundColor": "transparent",
        "grid": {"left": 56, "right": 16, "top": 34 if len(series) > 1 else 16, "bottom": 28},
        "legend": {"show": len(series) > 1, "top": 0, "right": 0, "itemWidth": 14, "itemHeight": 8,
                   "textStyle": {"color": TEXT_DIM, "fontSize": 11}},
        "xAxis": {"type": "category", "data": labels, "boundaryGap": False,
                  "axisLine": {"lineStyle": {"color": BORDER}},
                  "axisLabel": {"color": TEXT_DIM, "fontSize": 10, "hideOverlap": True}},
        "yAxis": {"type": "value", "scale": scale, "axisLine": {"show": False},
                  "axisLabel": {"color": TEXT_DIM, "formatter": y_format},
                  "splitLine": {"lineStyle": {"color": BORDER}}},
        "tooltip": {"trigger": "axis"},
        "series": series,
    })


# ---------------------------------------------------------------------------
# Caloric ROI Forecast
# ---------------------------------------------------------------------------
def forecast_page():
    page_header("Forecast", "Where your weight and spending are headed if your last 30 days continue.")
    state = {"months": 6}
    pill_toggle(HORIZONS, 6, lambda k: (state.update(months=k), render()))
    container = ui.column().classes("w-full gap-4 b-cards2")

    def render():
        container.clear()
        with Session(engine) as session:
            result = compute_forecast(session, state["months"])

        with container:
            if not result["available"]:
                with card_box_accent().classes("w-full gap-1"):
                    section_header("A few details first", subtitle="The forecast needs these from Profile & Goals")
                    with ui.column().classes("w-full gap-0"):
                        for field in result["missing_fields"]:
                            with ui.element("div").classes("b-nudge").on("click", lambda: ui.navigate.to("/profile")):
                                ui.element("span").classes("dot").style(f"background:{AMBER}")
                                ui.label(f"Add {field}" if field.startswith("a ") else f"Add your {field}").classes("b-nudge-text")
                                with ui.element("div").classes("b-nudge-cta"):
                                    ui.label("Profile")
                                    ui.icon("chevron_right")
                return

            calib = result.get("calibrated")
            if result.get("tdee_source") == "calibrated":
                maint_sub, maint_color = "calibrated from your own logs", VIOLET
            else:
                activity = result["activity_level"].replace("_", " ")
                maint_sub, maint_color = f"formula · {activity} activity", INDIGO
            delta = result["daily_calorie_delta"]
            summary_strip([
                ("Maintenance", f"{result['tdee']:,.0f} kcal", maint_color, maint_sub),
                ("You eat", f"{result['avg_daily_calories']:,.0f} kcal", EMERALD if delta <= 0 else AMBER,
                 f"{delta:+,.0f} kcal/day vs. maintenance" if delta else "right at maintenance"),
                ("You spend", f"{CUR}{result['avg_daily_spend']:,.2f}/day", SKY, "30-day average"),
            ])

            labels = _month_labels(result["months"])
            horizon = HORIZONS[result["months"]]

            # --- weight ---
            change = result["projected_weight_change_kg"]
            color = EMERALD if change <= 0 else AMBER
            with card_box().classes("w-full b-half gap-2"):
                with section_header("Weight", subtitle=f"{result['current_weight_kg']:.1f} → "
                                                       f"{result['projected_end_weight_kg']:.1f} kg in {horizon}"):
                    ui.label(f"{change:+.1f} kg").classes("text-lg font-bold").style(f"color:{color}")
                _line_chart(labels, [{
                    "name": "Projected weight", "type": "line", "smooth": True,
                    "data": [w["projected_weight_kg"] for w in result["weight_series"]],
                    "lineStyle": {"color": color, "width": 3}, "itemStyle": {"color": color},
                    "areaStyle": {"color": "rgba(52,211,153,0.12)" if change <= 0 else "rgba(245,158,11,0.12)"},
                }], "{value}kg", scale=True).classes("w-full h-56")

            # --- spending ---
            with card_box().classes("w-full b-half gap-2"):
                with section_header("Spending", subtitle=f"At your recent pace, over {horizon}"):
                    ui.label(f"{CUR}{result['projected_total_spend']:,.0f}").classes("text-lg font-bold")
                series = [{
                    "name": "Projected spend", "type": "line", "smooth": True,
                    "data": [s["cumulative_spend"] for s in result["spend_series"]],
                    "lineStyle": {"color": INDIGO, "width": 3}, "itemStyle": {"color": INDIGO},
                    "areaStyle": {"color": "rgba(99,102,241,0.12)"},
                }]
                if result["projected_budget_pace"] is not None:
                    ou = result["projected_over_under_budget"]
                    ui.label(f"{CUR}{abs(ou):,.0f} {'over' if ou > 0 else 'under'} your "
                             f"{CUR}{result['monthly_budget_target']:,.0f}/month budget").classes(
                        "text-sm font-semibold").style(f"color:{RED if ou > 0 else EMERALD}")
                    series.append({
                        "name": "Budget", "type": "line",
                        "data": [round(result["monthly_budget_target"] * s["month"], 2) for s in result["spend_series"]],
                        "lineStyle": {"color": TEXT_DIM, "width": 2, "type": "dashed"}, "itemStyle": {"color": TEXT_DIM},
                    })
                else:
                    ui.label("Set a monthly budget in Profile & Goals to compare against.").classes(
                        "b-hint").style("margin:0")
                _line_chart(labels, series, f"{CUR}{{value}}").classes("w-full h-56")

            # --- how it's worked out ---
            with card_box().classes("w-full gap-1"):
                section_header("How this is worked out")
                if calib:
                    ui.label(
                        f"Calibrated to you: over {calib['span_days']} days your weight changed "
                        f"{calib['weight_change_kg']:+.2f} kg while you averaged {calib['avg_intake']:,.0f} kcal/day "
                        f"({calib['logged_days']} days logged). By energy balance that's a real maintenance of "
                        f"~{calib['tdee']:,.0f} kcal/day, against the formula's {result['tdee_formula']:,.0f} -- "
                        "the forecast uses yours."
                    ).classes("text-sm")
                else:
                    ui.label(
                        "Maintenance comes from the Mifflin-St Jeor formula scaled by your activity level. Log your "
                        "weight and food for a couple of weeks and it switches to a figure calibrated from your own "
                        "data."
                    ).classes("text-sm")
                ui.label(
                    "Weight change uses the ~7,700 kcal ≈ 1 kg rule of thumb, and spending your 30-day average. "
                    "It's a projection of current habits -- not a guarantee, or medical or financial advice."
                ).classes("b-hint").style("margin:4px 0 0")

    render()
