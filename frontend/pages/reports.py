"""The reports page: one month, summarised -- and downloadable to share."""
from datetime import date

from nicegui import ui
from sqlmodel import Session

from backend.database import engine

from ..common import CUR, category_style
from ..components import (
    bar_row,
    card_box,
    empty_state,
    page_header,
    section_header,
    summary_strip,
    thin_meter,
)
from ..theme import (
    AMBER,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    RED,
    SKY,
    VIOLET,
)


def reports_page():
    from backend.report import monthly_report, report_html

    page_header("Monthly Report", "A shareable summary of your month.")
    today = date.today()
    state = {"y": today.year, "m": today.month}

    def shift(delta):
        y, m = state["y"], state["m"] + delta
        y, m = (y - 1, 12) if m == 0 else (y + 1, 1) if m == 13 else (y, m)
        if (y, m) <= (today.year, today.month):   # never into the future
            state.update(y=y, m=m)
            render()

    header = ui.row().classes("w-full items-center justify-between gap-2")
    container = ui.column().classes("w-full gap-4 b-cards2")

    def render():
        yr, mo = state["y"], state["m"]
        with Session(engine) as session:
            data = monthly_report(session, yr, mo)
        is_now = (yr, mo) == (today.year, today.month)

        def download():
            html = report_html(data, str(CUR))
            ui.download.content(html.encode("utf-8"), f"balance-report-{yr}-{mo:02d}.html", "text/html")

        header.clear()
        with header:
            with ui.element("div").classes("b-monthnav"):
                ui.button(icon="chevron_left", on_click=lambda: shift(-1)).props(
                    "flat round dense").classes("b-icon-btn").tooltip("Previous month")
                ui.label(date(yr, mo, 1).strftime("%B %Y")).classes("b-month")
                nxt = ui.button(icon="chevron_right", on_click=lambda: shift(1)).props(
                    "flat round dense").classes("b-icon-btn")
                if is_now:
                    nxt.props("disable")
                else:
                    nxt.tooltip("Next month")
            ui.button("Download", icon="download", on_click=download).props(
                "flat dense no-caps color=primary").tooltip("Save this month as a web page to share")

        container.clear()
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

            total = data["total_spent"] or 1
            with card_box().classes("w-full b-half gap-2"):
                section_header("Where it went", subtitle="Spending by category, share of the month")
                if not data["by_category"]:
                    empty_state("No spending recorded this month.", "receipt_long")
                else:
                    with ui.column().classes(LIST_GROUP):
                        for name, amt in sorted(data["by_category"].items(), key=lambda kv: -kv[1]):
                            icon, color = category_style(name)
                            bar_row(icon, color, name, f"{CUR}{amt:,.2f}", amt / total, f"{amt / total:.0%}")

            with card_box().classes("w-full b-half gap-2"):
                section_header("Top merchants", subtitle="Where the most went")
                if not data["top_merchants"]:
                    empty_state("No spending recorded this month.", "storefront")
                else:
                    top = data["top_merchants"][0][1] or 1
                    with ui.column().classes(LIST_GROUP):
                        for i, (name, amt) in enumerate(data["top_merchants"], 1):
                            bar_row("storefront", AMBER, f"{i}. {name}", f"{CUR}{amt:,.2f}", amt / top)

            n = data["nutrition"]
            with card_box().classes("w-full"):
                section_header("Nutrition", subtitle=f"Daily averages across the {n['days_logged']} "
                                                      f"day{'s' if n['days_logged'] != 1 else ''} you logged food")
                if not n["days_logged"]:
                    empty_state("No food logged this month.", "restaurant")
                else:
                    summary_strip([
                        ("Calories", f"{n['avg_calories']:,.0f}", INDIGO),
                        ("Protein", f"{n['avg_protein']:,.0f}g", EMERALD),
                        ("Carbs", f"{n['avg_carbs']:,.0f}g", AMBER),
                        ("Fat", f"{n['avg_fat']:,.0f}g", VIOLET),
                        ("Days logged", str(n["days_logged"]), SKY),
                    ])

    render()
