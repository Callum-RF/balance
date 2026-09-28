"""The prices page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    PriceObservation,
)

from ..common import CUR, format_date_header, group_by_date
from ..components import (
    card_box,
    date_field,
    empty_state,
    page_header,
    section_header,
)
from ..theme import (
    BORDER,
    CHART_PALETTE,
    EMERALD,
    INDIGO,
    RED,
    SURFACE,
    TEXT_DIM,
    VIOLET,
    echart,
)


# ---------------------------------------------------------------------------
# Prices (grocery price / inflation tracking)
# ---------------------------------------------------------------------------
def prices_page():
    page_header("Prices", "Track what staple grocery items cost over time.", icon="trending_up")

    with card_box().classes("w-full max-w-xl"):
        section_header("Log a price", icon="sell", icon_color=EMERALD)
        item_input = ui.input(label="Item name (be consistent, e.g. 'Milk 2L')").props("dense").classes("w-full")
        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
            price_input = ui.number(label=f"Price ({CUR})", format="%.2f").props("dense").classes("w-full")
            store_input = ui.input(label="Store (optional)").props("dense").classes("w-full")
            date_input = date_field("Date", value=date.today().isoformat())
        result_label = ui.label().style(f"color:{EMERALD}")

        def submit():
            with Session(engine) as session:
                obs = PriceObservation(
                    item_name=item_input.value or "",
                    price=price_input.value or 0,
                    store=store_input.value or None,
                    date=date.fromisoformat(date_input.value),
                )
                session.add(obs)
                session.commit()
            result_label.set_text("Logged!")

        ui.button("Log price", on_click=submit).props("color=primary unelevated")

    with Session(engine) as session:
        all_obs = session.exec(select(PriceObservation)).all()
    item_names = sorted({o.item_name for o in all_obs})

    COMPARE_ALL = "__compare_all__"

    if not item_names:
        with card_box().classes("w-full"):
            empty_state("No prices logged yet -- log the same item a few times over weeks to see its trend.", "trending_up")

    if item_names:
        with card_box().classes("w-full"):
            section_header("Price history", icon="query_stats", icon_color=VIOLET)
            select_options = {name: name for name in item_names}
            if len(item_names) > 1:
                # indexed comparison overlays every item on one chart, each
                # rebased to 100 at its first reading so items at very
                # different price points are comparable on relative change.
                select_options = {COMPARE_ALL: "★ Compare all (indexed)", **select_options}
            item_select = ui.select(
                select_options, value=item_names[0], label="Item"
            ).props("dense options-dense").classes("w-64")
            history_container = ui.column().classes("w-full gap-1")

            def render_comparison():
                with Session(engine) as session:
                    all_obs_c = session.exec(select(PriceObservation).order_by(PriceObservation.date)).all()
                by_item = {}
                for o in all_obs_c:
                    by_item.setdefault(o.item_name, []).append(o)

                all_dates = sorted({o.date.isoformat() for o in all_obs_c})
                series = []
                for idx, (name, obs) in enumerate(sorted(by_item.items())):
                    if len(obs) < 2 or not obs[0].price:
                        continue
                    base = obs[0].price
                    by_date = {o.date.isoformat(): round(o.price / base * 100, 1) for o in obs}
                    # align to the shared x-axis; None lets ECharts connect across gaps
                    data = [by_date.get(d) for d in all_dates]
                    series.append({
                        "name": name, "data": data, "type": "line", "smooth": True,
                        "connectNulls": True, "showSymbol": False,
                        "lineStyle": {"color": CHART_PALETTE[idx % len(CHART_PALETTE)], "width": 2},
                        "itemStyle": {"color": CHART_PALETTE[idx % len(CHART_PALETTE)]},
                    })
                with history_container:
                    if len(series) < 2:
                        ui.label(
                            "Log at least two prices for two or more items to compare them."
                        ).classes("text-sm").style(f"color:{TEXT_DIM}")
                        return
                    ui.label(
                        "Each item rebased to 100 at its first logged price -- lines rising above "
                        "100 have gotten more expensive, in percentage terms."
                    ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")
                    echart({
                        "backgroundColor": "transparent",
                        "grid": {"left": 45, "right": 20, "top": 40, "bottom": 40},
                        "legend": {"textStyle": {"color": TEXT_DIM, "fontSize": 11}, "top": 0, "type": "scroll"},
                        "xAxis": {
                            "type": "category", "data": all_dates, "boundaryGap": False,
                            "axisLine": {"lineStyle": {"color": BORDER}},
                            "axisLabel": {"color": TEXT_DIM, "fontSize": 10},
                        },
                        "yAxis": {
                            "type": "value", "axisLine": {"show": False},
                            "axisLabel": {"color": TEXT_DIM, "formatter": "{value}"},
                            "splitLine": {"lineStyle": {"color": BORDER}},
                        },
                        "tooltip": {"trigger": "axis"},
                        "series": series,
                    }).classes("w-full h-72")

            def render_history():
                history_container.clear()
                if item_select.value == COMPARE_ALL:
                    render_comparison()
                    return
                with Session(engine) as session:
                    obs = session.exec(
                        select(PriceObservation).where(PriceObservation.item_name == item_select.value).order_by(PriceObservation.date)
                    ).all()
                with history_container:
                    if len(obs) < 2:
                        ui.label("Log at least two prices for this item to see a trend.").classes("text-sm").style(f"color:{TEXT_DIM}")
                    else:
                        change = ((obs[-1].price - obs[0].price) / obs[0].price) * 100 if obs[0].price else 0
                        color = RED if change > 0 else EMERALD
                        ui.label(f"{change:+.1f}% since first logged").style(f"color:{color}").classes("text-sm mb-2")

                        dates = [o.date.isoformat() for o in obs]
                        prices = [o.price for o in obs]
                        echart({
                            "backgroundColor": "transparent",
                            "grid": {"left": 50, "right": 20, "top": 20, "bottom": 40},
                            "xAxis": {
                                "type": "category", "data": dates, "boundaryGap": False,
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
                            "series": [{
                                "data": prices, "type": "line", "smooth": True,
                                "lineStyle": {"color": INDIGO, "width": 3},
                                "itemStyle": {"color": INDIGO},
                                "areaStyle": {"color": "rgba(99,102,241,0.15)"},
                            }],
                        }).classes("w-full h-64")

                        # monthly averages, nicely formatted (e.g. "Jul 2026" not "2026-07")
                        monthly = {}
                        for o in obs:
                            key = (o.date.year, o.date.month)
                            monthly.setdefault(key, []).append(o.price)
                        monthly_avgs = sorted(monthly.items())

                        if len(monthly_avgs) > 1:
                            ui.label("Monthly average").classes("text-xs font-semibold uppercase tracking-wide mt-3").style(f"color:{TEXT_DIM}")
                            with ui.row().classes("w-full gap-4 flex-wrap mt-1"):
                                for (year, month), vals in monthly_avgs:
                                    label = date(year, month, 1).strftime("%b %Y")
                                    avg = sum(vals) / len(vals)
                                    with ui.column().classes("gap-0"):
                                        ui.label(label).classes("text-xs").style(f"color:{TEXT_DIM}")
                                        ui.label(f"{CUR}{avg:,.2f}").classes("text-sm font-semibold")

                    # full history, newest first, grouped by date, with edit/delete
                    ui.label(f"All logged prices ({len(obs)})").classes("text-xs font-semibold uppercase tracking-wide mt-4").style(f"color:{TEXT_DIM}")
                    for group_date, day_obs in group_by_date(list(reversed(obs))):
                        ui.label(format_date_header(group_date)).classes("text-xs mt-2").style(f"color:{TEXT_DIM}")
                        for o in day_obs:
                            with card_box().classes("w-full py-2 flex-row items-center justify-between gap-2"):
                                with ui.column().classes("gap-0"):
                                    ui.label(f"{CUR}{o.price:,.2f}").classes("font-semibold")
                                    if o.store:
                                        ui.label(o.store).classes("text-xs").style(f"color:{TEXT_DIM}")
                                with ui.row().classes("gap-1"):
                                    ui.button(icon="edit", on_click=lambda _, ob=o: open_edit_dialog(ob)).props("flat round dense")
                                    ui.button(icon="delete", on_click=lambda _, oid=o.id: delete_price(oid)).props("flat round dense color=red")

            def open_edit_dialog(obs):
                with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2"):
                    ui.label("Edit price").classes("text-lg font-semibold")
                    edit_price = ui.number(label=f"Price ({CUR})", value=obs.price, format="%.2f").classes("w-full")
                    edit_store = ui.input(label="Store", value=obs.store or "").props("dense").classes("w-full")
                    edit_date = date_field("Date", value=obs.date.isoformat())

                    def save():
                        with Session(engine) as session:
                            db_obs = session.get(PriceObservation, obs.id)
                            if db_obs:
                                db_obs.price = edit_price.value or 0
                                db_obs.store = edit_store.value or None
                                db_obs.date = date.fromisoformat(edit_date.value)
                                session.add(db_obs)
                                session.commit()
                        dialog.close()
                        render_history()

                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                        ui.button("Cancel", on_click=dialog.close).props("flat")
                        ui.button("Save", on_click=save).props("color=primary unelevated")
                dialog.open()

            def delete_price(observation_id):
                with Session(engine) as session:
                    obs = session.get(PriceObservation, observation_id)
                    if obs:
                        session.delete(obs)
                        session.commit()
                render_history()

            item_select.on_value_change(lambda e: render_history())
            render_history()
