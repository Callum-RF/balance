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
    list_row,
    page_header,
    section_header,
    sheet_dialog,
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

TYPE_ICONS = {
    "current": ("account_balance", INDIGO), "savings": ("savings", EMERALD), "cash": ("payments", AMBER),
    "investment": ("trending_up", VIOLET), "credit": ("credit_card", RED), "loan": ("request_quote", RED),
}


def accounts_page(embedded=False, adder=None):
    from backend.networth import (
        ASSET_TYPES,
        LIABILITY_TYPES,
        TYPE_LABELS,
        snapshot_if_due,
    )

    adder = {} if adder is None else adder
    if not embedded:
        page_header("Accounts & Net Worth", "Balances across accounts, tracked over time.",
                    action=("Add", "add", lambda: adder["open"]()))
    undo_container = ui.column().classes("w-full")

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
                if not a:
                    return
                snapshot = a.model_dump(exclude={"id"})
                session.delete(a)
                session.commit()

            def undo():
                with Session(engine) as session:
                    session.add(Account(**snapshot))
                    session.commit()
                ui.notify("Restored.", type="positive")
                content.refresh()

            content.refresh()
            undo_banner(undo_container, f"Deleted {snapshot['name']}.", undo)

        def open_account(aid, nm, typ, bal):
            """Update the balance (the usual job), or rename / retype / delete."""
            with ui.dialog() as dialog, ui.card().classes(
                    f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
                section_header(nm, subtitle=TYPE_LABELS.get(typ, typ))
                ui.label("Balance now").classes("text-xs").style(f"color:{TEXT_DIM}")
                e_bal = ui.number(value=bal, format="%.2f").props(
                    f'dense outlined prefix="{CUR}" input-class="text-2xl font-bold" autofocus').classes("w-full")
                with ui.expansion("Rename or change type", icon="tune").classes("w-full"):
                    e_name = ui.input(label="Name", value=nm).props("dense").classes("w-full")
                    e_type = ui.select(TYPE_LABELS, value=typ, label="Type").props("dense").classes("w-full")

                def save():
                    with Session(engine) as session:
                        a = session.get(Account, aid)
                        if a:
                            a.name = e_name.value or a.name
                            a.type = e_type.value
                            session.add(a)
                            session.commit()
                    dialog.close()
                    _save_balance(aid, e_bal.value)

                def remove():
                    dialog.close()
                    _del(aid)

                with ui.row().classes("w-full items-center gap-2 mt-2"):
                    ui.button("Delete", icon="delete_outline", on_click=remove).props("flat no-caps color=negative")
                    ui.space()
                    ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                    ui.button("Save", on_click=save).props("color=primary unelevated no-caps")
            dialog.open()

        with sheet_dialog("Add an account", adder=adder):
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
                    adder["close"]()
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

        for title, types in (("Assets", ASSET_TYPES), ("Liabilities", LIABILITY_TYPES)):
            group_accs = [t for t in accounts if t[2] in types]
            if not group_accs:
                continue
            with ui.element("div").classes("b-day"):
                ui.label(title)
                ui.label(f"{CUR}{sum(t[3] for t in group_accs):,.2f}")
            with ui.column().classes(LIST_GROUP):
                for aid, nm, typ, bal in group_accs:
                    icon, color = TYPE_ICONS.get(typ, ("account_balance_wallet", INDIGO))
                    list_row(icon, color, nm, TYPE_LABELS.get(typ, typ), f"{CUR}{bal:,.2f}",
                             lambda _, a=(aid, nm, typ, bal): open_account(*a), tooltip="Update balance")

    content()
