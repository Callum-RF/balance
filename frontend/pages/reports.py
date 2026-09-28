"""The reports page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session

from backend.database import engine

from ..common import CUR
from ..components import (
    card_box,
    page_header,
    section_header,
    summary_strip,
    thin_meter,
)
from ..theme import (
    AMBER,
    EMERALD,
    INDIGO,
    RED,
    TEXT,
    TEXT_DIM,
    VIOLET,
)


def reports_page():
    from backend.report import monthly_report, report_html

    page_header("Monthly Report", "A shareable summary of your month.", icon="summarize")
    today = date.today()
    opts, y, m = {}, today.year, today.month
    for _ in range(12):
        opts[f"{y}-{m:02d}"] = date(y, m, 1).strftime("%B %Y")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    month_select = ui.select(opts, value=f"{today.year}-{today.month:02d}", label="Month").props(
        "dense options-dense").classes("w-56")
    container = ui.column().classes("w-full gap-4")

    def render():
        container.clear()
        yr, mo = map(int, month_select.value.split("-"))
        with Session(engine) as session:
            data = monthly_report(session, yr, mo)
        with container:
            summary_strip([
                ("Income", f"{CUR}{data['total_income']:,.2f}", EMERALD),
                ("Spent", f"{CUR}{data['total_spent']:,.2f}", RED, f"{data['transaction_count']} transactions"),
                ("Net", f"{'+' if data['net'] >= 0 else '−'}{CUR}{abs(data['net']):,.2f}",
                 EMERALD if data['net'] >= 0 else RED),
            ])
            if data["overall_budget"] is not None:
                ou = data["over_under_budget"]
                with ui.element("div").classes("b-budget"):
                    thin_meter(data["total_spent"], data["overall_budget"], RED if ou > 0 else EMERALD)
                    with ui.element("div").classes("b-budget-cap"):
                        ui.label(f"{CUR}{data['total_spent']:,.2f} of {CUR}{data['overall_budget']:,.2f} budget")
                        ui.label(f"{CUR}{abs(ou):,.2f} {'over' if ou > 0 else 'under'}").style(
                            f"color:{RED if ou > 0 else EMERALD}")

            with card_box().classes("w-full"):
                section_header("Spending by category", icon="pie_chart", icon_color=VIOLET)
                if not data["by_category"]:
                    ui.label("No spending recorded this month.").classes("text-xs").style(f"color:{TEXT_DIM}")
                for name, amt in data["by_category"].items():
                    with ui.row().classes("w-full justify-between py-0.5"):
                        ui.label(name).classes("text-sm").style(f"color:{TEXT}")
                        ui.label(f"{CUR}{amt:,.2f}").classes("text-sm").style(f"color:{TEXT_DIM}")

            if data["top_merchants"]:
                with card_box().classes("w-full"):
                    section_header("Top merchants", icon="storefront", icon_color=AMBER)
                    for name, amt in data["top_merchants"]:
                        with ui.row().classes("w-full justify-between py-0.5"):
                            ui.label(name).classes("text-sm").style(f"color:{TEXT}")
                            ui.label(f"{CUR}{amt:,.2f}").classes("text-sm").style(f"color:{TEXT_DIM}")

            n = data["nutrition"]
            with card_box().classes("w-full"):
                section_header("Nutrition", icon="restaurant", icon_color=INDIGO)
                ui.label(
                    f"{n['days_logged']} day(s) logged. Daily average {n['avg_calories']:,.0f} kcal · "
                    f"P {n['avg_protein']:,.0f}g · C {n['avg_carbs']:,.0f}g · F {n['avg_fat']:,.0f}g."
                ).classes("text-sm").style(f"color:{TEXT_DIM}")

            def download():
                html = report_html(data, str(CUR))
                ui.download.content(html.encode("utf-8"), f"balance-report-{yr}-{mo:02d}.html", "text/html")
            ui.button("Download report (HTML)", icon="download", on_click=download).props("outline no-caps color=primary")

    month_select.on_value_change(render)
    render()
