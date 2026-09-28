"""The accounts page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    Account,
    NetWorthSnapshot,
)

from ..common import CUR
from ..components import (
    card_box,
    empty_state,
    page_header,
    section_header,
    summary_strip,
)
from ..theme import (
    BORDER,
    EMERALD,
    INDIGO,
    RED,
    SKY,
    TEXT,
    TEXT_DIM,
    echart,
)


def accounts_page():
    from backend.networth import ASSET_TYPES, LIABILITY_TYPES, TYPE_LABELS, snapshot_if_due

    page_header("Accounts & Net Worth", "Balances across accounts, tracked over time.", icon="account_balance")

    @ui.refreshable
    def content():
        today = date.today()
        with Session(engine) as session:
            if session.exec(select(Account)).first() is not None:
                snapshot_if_due(session, today)   # commits -> expires ORM objects
            # Materialise to plain tuples: the commit above expires the ORM
            # instances, so they must not be touched after the session closes.
            accounts = [(a.id, a.name, a.type, a.balance or 0)
                        for a in session.exec(select(Account)).all()]
            snaps = [(sn.date, sn.net_worth)
                     for sn in session.exec(select(NetWorthSnapshot).order_by(NetWorthSnapshot.date)).all()]

        assets = sum(bal for (_i, _n, typ, bal) in accounts if typ in ASSET_TYPES)
        liabilities = sum(bal for (_i, _n, typ, bal) in accounts if typ in LIABILITY_TYPES)
        net = assets - liabilities

        summary_strip([
            ("Net worth", f"{CUR}{net:,.0f}", EMERALD if net >= 0 else RED),
            ("Assets", f"{CUR}{assets:,.0f}", INDIGO),
            ("Liabilities", f"{CUR}{liabilities:,.0f}", RED) if liabilities else None,
            ("Accounts", str(len(accounts)), SKY) if accounts else None,
        ])

        def _save_balance(aid, val):
            with Session(engine) as session:
                a = session.get(Account, aid)
                if a:
                    a.balance = val or 0
                    session.add(a)
                    session.commit()
                    snapshot_if_due(session, today)
            ui.notify("Balance updated.", type="positive")
            content.refresh()

        def _del(aid):
            with Session(engine) as session:
                a = session.get(Account, aid)
                if a:
                    session.delete(a)
                session.commit()
            content.refresh()

        with ui.expansion("Add account", icon="add").classes("w-full"):
            with ui.column().classes("gap-1 max-w-xl w-full"):
                a_name = ui.input(label="Account name (e.g. Monzo Current)").props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-2"):
                    a_type = ui.select(TYPE_LABELS, value="current", label="Type").props("dense options-dense").classes("w-full")
                    a_bal = ui.number(label="Current balance", format="%.2f").props(f'prefix="{CUR}"').classes("w-full")
                ui.label("Credit card / loan balances count as liabilities (subtracted from net worth).").classes(
                    "text-xs").style(f"color:{TEXT_DIM}")

                def add_account():
                    if not a_name.value:
                        ui.notify("Name the account.", type="warning"); return
                    with Session(engine) as session:
                        session.add(Account(name=a_name.value, type=a_type.value, balance=a_bal.value or 0))
                        session.commit()
                        snapshot_if_due(session, today)
                    ui.notify("Account added.", type="positive")
                    content.refresh()
                ui.button("Add account", on_click=add_account).props("color=primary unelevated")

        if len(snaps) >= 2:
            with card_box().classes("w-full"):
                section_header("Net worth trend", icon="show_chart", icon_color=EMERALD,
                               subtitle="Snapshotted once a day as you update balances")
                echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 60, "right": 15, "top": 15, "bottom": 28},
                    "xAxis": {"type": "category", "data": [dt.strftime("%d %b") for (dt, nw) in snaps],
                              "axisLine": {"lineStyle": {"color": BORDER}},
                              "axisLabel": {"color": TEXT_DIM, "fontSize": 10}},
                    "yAxis": {"type": "value", "axisLine": {"show": False},
                              "axisLabel": {"color": TEXT_DIM, "formatter": f"{CUR}{{value}}"},
                              "splitLine": {"lineStyle": {"color": BORDER}}},
                    "tooltip": {"trigger": "axis"},
                    "series": [{"type": "line", "smooth": True,
                                "data": [round(nw, 2) for (dt, nw) in snaps],
                                "itemStyle": {"color": EMERALD}, "lineStyle": {"color": EMERALD},
                                "areaStyle": {"color": EMERALD + "22"}}],
                }).classes("w-full h-56")

        if not accounts:
            with card_box().classes("w-full"):
                empty_state("No accounts yet -- add your current, savings, cash or credit accounts to track net worth.",
                            "account_balance")

        for group, title, types in (("assets", "Assets", ASSET_TYPES), ("liab", "Liabilities", LIABILITY_TYPES)):
            group_accs = [t for t in accounts if t[2] in types]
            if not group_accs:
                continue
            with card_box().classes("w-full"):
                section_header(title, icon="account_balance_wallet",
                               icon_color=INDIGO if group == "assets" else RED, count=len(group_accs))
                for aid, nm, typ, bal in group_accs:
                    with ui.row().classes("w-full items-center gap-2 py-1"):
                        with ui.column().classes("gap-0 min-w-0 flex-grow"):
                            ui.label(nm).classes("text-sm").style(f"color:{TEXT}")
                            ui.label(TYPE_LABELS.get(typ, typ)).classes("text-xs").style(f"color:{TEXT_DIM}")
                        bal_in = ui.number(value=bal, format="%.2f").props(f'prefix="{CUR}" dense').classes("w-32")

                        def save_bal(_=None, aid=aid, bal_in=bal_in):
                            _save_balance(aid, bal_in.value)
                        ui.button(icon="save", on_click=save_bal).props("flat round dense color=primary").tooltip("Save balance")
                        ui.button(icon="delete", on_click=lambda _, aid=aid: _del(aid)).props("flat round dense color=red")

    content()
