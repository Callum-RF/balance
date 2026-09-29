"""The prices page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    PriceObservation,
)

from ..common import CUR, format_date_header
from ..components import (
    card_box,
    date_field,
    empty_state,
    list_row,
    page_header,
    pill_toggle,
    section_header,
    sheet_dialog,
    summary_strip,
    undo_banner,
)
from ..theme import (
    AMBER,
    BORDER,
    CHART_PALETTE,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    RED,
    SURFACE,
    TEXT_DIM,
    echart,
)

COMPARE_ALL = "__compare_all__"


def _change(first, last):
    return ((last - first) / first * 100) if first else 0


# ---------------------------------------------------------------------------
# Prices (grocery price / inflation tracking)
# ---------------------------------------------------------------------------
def prices_page():
    adder = {}
    page_header("Prices", "Track what staple grocery items cost over time.",
                action=("Log a price", "add", lambda: adder["open"]()))
    state = {"item": None}
    undo_container = ui.column().classes("w-full")

    @ui.refreshable
    def content():
        with Session(engine) as session:
            all_obs = session.exec(select(PriceObservation).order_by(PriceObservation.date)).all()
        by_item: dict = {}
        for o in all_obs:
            by_item.setdefault(o.item_name, []).append(o)
        item_names = sorted(by_item)
        trends = {n: _change(v[0].price, v[-1].price) for n, v in by_item.items() if len(v) > 1}
        biggest = max(trends.items(), key=lambda kv: kv[1]) if trends else None
        summary_strip([
            ("Items tracked", str(len(item_names)), INDIGO),
            ("Prices logged", str(len(all_obs)), EMERALD),
            biggest and biggest[1] > 0 and (f"Biggest rise · {biggest[0]}", f"{biggest[1]:+.1f}%", RED),
        ])

        with sheet_dialog("Log a price", adder=adder):
            with ui.column().classes("gap-1 max-w-xl w-full"):
                item_input = ui.input(label="Item (be consistent, e.g. 'Milk 2L')",
                                      autocomplete=item_names).props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
                    price_input = ui.number(label=f"Price ({CUR})", format="%.2f").props("dense").classes("w-full")
                    store_input = ui.input(label="Store (optional)").props("dense").classes("w-full")
                    date_input = date_field("Date", value=date.today().isoformat())

                def submit():
                    name = (item_input.value or "").strip()
                    if not name or not price_input.value:
                        ui.notify("Add an item name and a price.", type="warning")
                        return
                    with Session(engine) as session:
                        session.add(PriceObservation(item_name=name, price=price_input.value,
                                                     store=store_input.value or None,
                                                     date=date.fromisoformat(date_input.value)))
                        session.commit()
                    state["item"] = name
                    adder["close"]()
                    ui.notify(f"Logged {name} at {CUR}{price_input.value:,.2f}.", type="positive")
                    content.refresh()

                ui.button("Log price", on_click=submit).props("color=primary unelevated no-caps")

        if not item_names:
            with card_box().classes("w-full"):
                empty_state("No prices logged yet -- log the same item a few times over weeks to see its trend.",
                            "trending_up")
            return

        if state["item"] not in by_item and state["item"] != COMPARE_ALL:
            state["item"] = item_names[0]
        options = {name: name for name in item_names}
        if len(item_names) > 1:
            options = {COMPARE_ALL: "Compare all", **options}
        pill_toggle(options, state["item"], lambda k: (state.update(item=k), history.refresh()))

        @ui.refreshable
        def history():
            if state["item"] == COMPARE_ALL:
                render_comparison(by_item)
            else:
                render_item(state["item"], by_item.get(state["item"], []))

        history()

    def render_comparison(by_item):
        all_dates = sorted({o.date.isoformat() for obs in by_item.values() for o in obs})
        series = []
        for idx, (name, obs) in enumerate(sorted(by_item.items())):
            if len(obs) < 2 or not obs[0].price:
                continue
            base = obs[0].price
            by_date = {o.date.isoformat(): round(o.price / base * 100, 1) for o in obs}
            color = CHART_PALETTE[idx % len(CHART_PALETTE)]
            series.append({
                "name": name, "data": [by_date.get(d) for d in all_dates], "type": "line", "smooth": True,
                "connectNulls": True, "showSymbol": False,
                "lineStyle": {"color": color, "width": 2}, "itemStyle": {"color": color},
            })
        with card_box().classes("w-full"):
            section_header("All items", subtitle="Each rebased to 100 at its first logged price -- "
                                                 "above 100 means it has got dearer")
            if len(series) < 2:
                empty_state("Log at least two prices for two or more items to compare them.", "query_stats")
                return
            echart({
                "backgroundColor": "transparent",
                "grid": {"left": 45, "right": 20, "top": 40, "bottom": 40},
                "legend": {"textStyle": {"color": TEXT_DIM, "fontSize": 11}, "top": 0, "type": "scroll"},
                "xAxis": {"type": "category", "data": all_dates, "boundaryGap": False,
                          "axisLine": {"lineStyle": {"color": BORDER}},
                          "axisLabel": {"color": TEXT_DIM, "fontSize": 10}},
                "yAxis": {"type": "value", "axisLine": {"show": False},
                          "axisLabel": {"color": TEXT_DIM, "formatter": "{value}"},
                          "splitLine": {"lineStyle": {"color": BORDER}}},
                "tooltip": {"trigger": "axis"},
                "series": series,
            }).classes("w-full h-72")

    def render_item(name, obs):
        with card_box().classes("w-full"):
            logged = f"{len(obs)} price{'s' if len(obs) != 1 else ''} logged"
            change = _change(obs[0].price, obs[-1].price) if len(obs) > 1 else 0
            section_header(name, subtitle=logged + (f" · {change:+.1f}% since the first" if len(obs) > 1 else ""))
            if len(obs) < 2:
                ui.label("Log at least two prices for this item to see a trend.").classes(
                    "text-sm").style(f"color:{TEXT_DIM}")
            else:
                echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 50, "right": 20, "top": 20, "bottom": 40},
                    "xAxis": {"type": "category", "data": [o.date.isoformat() for o in obs], "boundaryGap": False,
                              "axisLine": {"lineStyle": {"color": BORDER}},
                              "axisLabel": {"color": TEXT_DIM, "fontSize": 10}},
                    "yAxis": {"type": "value", "axisLine": {"show": False},
                              "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                              "splitLine": {"lineStyle": {"color": BORDER}}},
                    "tooltip": {"trigger": "axis"},
                    "series": [{
                        "data": [o.price for o in obs], "type": "line", "smooth": True,
                        "lineStyle": {"color": INDIGO, "width": 3}, "itemStyle": {"color": INDIGO},
                        "areaStyle": {"color": "rgba(99,102,241,0.15)"},
                    }],
                }).classes("w-full h-64")

                monthly: dict = {}
                for o in obs:
                    monthly.setdefault((o.date.year, o.date.month), []).append(o.price)
                if len(monthly) > 1:
                    summary_strip([
                        (date(y, m, 1).strftime("%b %Y"), f"{CUR}{sum(v) / len(v):,.2f}", INDIGO)
                        for (y, m), v in sorted(monthly.items())[-4:]
                    ])

        # Every logged price, newest first; each row shows the change from the
        # one before it and opens the entry.
        previous = {o.id: (obs[i - 1].price if i else None) for i, o in enumerate(obs)}
        with ui.element("div").classes("b-day"):
            ui.label("Every price logged")
            ui.label(str(len(obs)))
        with ui.column().classes(LIST_GROUP):
            for o in reversed(obs):
                prev = previous.get(o.id)
                if prev:
                    ch = _change(prev, o.price)
                    tail = "no change" if abs(ch) < 0.05 else f"{ch:+.1f}% on last time"
                    color = RED if ch > 0.05 else EMERALD if ch < -0.05 else None
                else:
                    tail, color = "first logged", None
                icon = "trending_up" if color == RED else "trending_down" if color == EMERALD else "sell"
                list_row(icon, color or AMBER, o.store or "Store not noted",
                         f"{format_date_header(o.date)} · {tail}", f"{CUR}{o.price:,.2f}",
                         lambda _, ob=o: open_edit_dialog(ob), tooltip="Edit")

    def open_edit_dialog(obs):
        with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
            section_header(obs.item_name, subtitle="Logged price")
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
                content.refresh()

            def remove():
                dialog.close()
                delete_price(obs.id)

            with ui.row().classes("w-full items-center gap-2 mt-2"):
                ui.button("Delete", icon="delete_outline", on_click=remove).props("flat no-caps color=negative")
                ui.space()
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", on_click=save).props("color=primary unelevated no-caps")
        dialog.open()

    def delete_price(observation_id):
        with Session(engine) as session:
            obj = session.get(PriceObservation, observation_id)
            if not obj:
                return
            snapshot = obj.model_dump(exclude={"id"})
            session.delete(obj)
            session.commit()

        def undo_delete():
            with Session(engine) as session:
                session.add(PriceObservation(**snapshot))
                session.commit()
            ui.notify("Restored.", type="positive")
            content.refresh()

        content.refresh()
        undo_banner(undo_container, f"Deleted a {snapshot['item_name']} price.", undo_delete)

    content()
