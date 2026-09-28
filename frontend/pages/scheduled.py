"""The scheduled page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    INCOME_SOURCES,
    Category,
    Income,
    ScheduledTransaction,
    Transaction,
)

from ..common import CUR, _category_label, format_date_header
from ..components import (
    card_box,
    card_box_accent,
    date_field,
    empty_state,
    list_row,
    page_header,
    section_header,
    segmented,
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
    SURFACE,
    TEXT,
    TEXT_DIM,
)


# ---------------------------------------------------------------------------
# Single entry point: header/drawer render once, ui.sub_pages swaps the
# content panel client-side (history.pushState) instead of a full browser
# reload on every nav click.
# ---------------------------------------------------------------------------
def scheduled_page():
    from backend.cashflow import cashflow_summary
    from backend.recurring import post_now, skip_next

    page_header("Scheduled", "Recurring transactions and upcoming cashflow.")
    undo_container = ui.column().classes("w-full")

    @ui.refreshable
    def content():
        today = date.today()
        with Session(engine) as session:
            items = session.exec(select(ScheduledTransaction)).all()
            categories = session.exec(select(Category)).all()
            month_start = today.replace(day=1)
            spent_mtd = sum(t.amount for t in session.exec(
                select(Transaction).where(Transaction.date >= month_start, Transaction.date <= today)).all())
            earned_mtd = sum(i.amount for i in session.exec(
                select(Income).where(Income.date >= month_start, Income.date <= today)).all())
        net_so_far = earned_mtd - spent_mtd
        category_options = {c.id: _category_label(c, categories) for c in categories}
        cats_by_id = {c.id: c for c in categories}
        active_items = [i for i in items if i.active]

        def monthly_norm(i):
            if i.cadence == "weekly":
                return i.amount * 52 / 12
            if i.cadence == "yearly":
                return i.amount / 12
            return i.amount
        monthly_out = sum(monthly_norm(i) for i in active_items if i.kind == "expense")
        monthly_in = sum(monthly_norm(i) for i in active_items if i.kind == "income")

        summary_strip([
            ("Scheduled items", str(len(active_items)), INDIGO),
            ("Recurring out / mo", f"{CUR}{monthly_out:,.0f}", RED),
            ("Recurring in / mo", f"{CUR}{monthly_in:,.0f}", EMERALD) if monthly_in else None,
        ])

        # --- forward cashflow: what's due in the next 30 days ---
        cf = cashflow_summary(days=30, today=today)
        with card_box().classes("w-full"):
            with section_header("Next 30 days",
                                subtitle="Bills and income from your subscriptions and scheduled items"):
                ui.label(f"{'+' if cf['net'] >= 0 else '-'}{CUR}{abs(cf['net']):,.2f}").classes(
                    "text-lg font-bold").style(f"color:{EMERALD if cf['net'] >= 0 else RED}")
            with ui.row().classes("w-full gap-4 flex-wrap"):
                ui.label(f"Out {CUR}{cf['out']:,.2f}").classes("text-xs").style(f"color:{RED}")
                ui.label(f"In {CUR}{cf['in']:,.2f}").classes("text-xs").style(f"color:{EMERALD}")
            if cf["out"] > 0:
                after = net_so_far + cf["in"] - cf["out"]
                ui.label(
                    f"Net so far this month is {CUR}{net_so_far:,.2f}; after the {CUR}{cf['out']:,.2f} of upcoming bills "
                    f"(and {CUR}{cf['in']:,.2f} income) that leaves {CUR}{after:,.2f}."
                ).classes("text-xs").style(f"color:{TEXT_DIM if after >= 0 else AMBER}")
            if not cf["events"]:
                ui.label("Nothing scheduled in the next 30 days.").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")
            for e in cf["events"][:30]:
                sign = "+" if e["direction"] == "in" else "-"
                color = EMERALD if e["direction"] == "in" else RED
                with ui.row().classes("w-full items-center justify-between gap-2 py-1 no-wrap"):
                    with ui.row().classes("flex-1 items-center gap-3 min-w-0 no-wrap"):
                        ui.label(f"{e['date'].day} {e['date']:%b}").classes(
                            "text-xs w-12 shrink-0 font-semibold").style(f"color:{TEXT_DIM}")
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(e["label"]).classes("text-sm min-w-0 truncate").style(f"color:{TEXT}")
                            ui.label(f"{e['date']:%A} · {e['source']}").classes("text-xs truncate").style(
                                f"color:{TEXT_DIM}")
                    ui.label(f"{sign}{CUR}{e['amount']:,.2f}").classes(
                        "text-sm font-semibold shrink-0 whitespace-nowrap").style(f"color:{color}")

        def _post_now(iid):
            post_now(iid)
            ui.notify("Posted.", type="positive")
            content.refresh()

        def _skip(iid):
            skip_next(iid)
            ui.notify("Skipped to next date.", type="info")
            content.refresh()

        def _toggle_active(iid, val):
            with Session(engine) as session:
                row = session.get(ScheduledTransaction, iid)
                if row:
                    row.active = val
                    session.add(row); session.commit()
            content.refresh()

        def _delete(iid):
            with Session(engine) as session:
                row = session.get(ScheduledTransaction, iid)
                if not row:
                    return
                snapshot = row.model_dump(exclude={"id"})
                session.delete(row); session.commit()

            def undo():
                with Session(engine) as session:
                    session.add(ScheduledTransaction(**snapshot))
                    session.commit()
                ui.notify("Restored.", type="positive")
                content.refresh()

            content.refresh()
            undo_banner(undo_container, f"Deleted {snapshot['description'] or 'scheduled item'}.", undo)

        def open_item(iid):
            """One scheduled item: post it now, skip a date, pause, or delete."""
            with Session(engine) as session:
                row = session.get(ScheduledTransaction, iid)
                if not row:
                    return
                cur = row.model_dump()
            lbl = cur["description"] or ("Income" if cur["kind"] == "income" else "Expense")
            with ui.dialog() as dialog, ui.card().classes(
                    f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
                section_header(lbl, subtitle=(
                    f"{'+' if cur['kind'] == 'income' else '-'}{CUR}{cur['amount']:,.2f} · {cur['cadence']} · "
                    + ("posts automatically" if cur["auto_post"] else "waits for you to confirm")))
                if cur["next_date"]:
                    ui.label(f"Next: {cur['next_date']:%A %d %B}").classes("text-sm")

                def act(fn):
                    dialog.close()
                    fn()

                with ui.column().classes("w-full gap-1 mt-1"):
                    if cur["active"]:
                        ui.button("Post it now", icon="check", on_click=lambda: act(lambda: _post_now(iid))).props(
                            "unelevated no-caps color=primary").classes("self-start")
                        ui.button("Skip the next one", icon="skip_next",
                                  on_click=lambda: act(lambda: _skip(iid))).props(
                            "flat no-caps color=primary").classes("self-start")
                with ui.row().classes("w-full items-center gap-2 mt-2"):
                    ui.button("Delete", icon="delete_outline",
                              on_click=lambda: act(lambda: _delete(iid))).props("flat no-caps color=negative")
                    ui.button("Resume" if not cur["active"] else "Pause",
                              icon="play_arrow" if not cur["active"] else "pause",
                              on_click=lambda: act(lambda: _toggle_active(iid, not cur["active"]))).props(
                        "flat no-caps")
                    ui.space()
                    ui.button("Close", on_click=dialog.close).props("flat no-caps")
            dialog.open()

        due = sorted([i for i in active_items if not i.auto_post and i.next_date and i.next_date <= today],
                     key=lambda i: i.next_date)
        if due:
            with card_box_accent().classes("w-full gap-1"):
                section_header("Due now", subtitle="Confirm to record them, or skip to the next date")
                with ui.column().classes("w-full gap-0"):
                    for i in due:
                        lbl = i.description or ("Income" if i.kind == "income" else "Expense")
                        sign = "+" if i.kind == "income" else "-"
                        with ui.element("div").classes("b-nudge").style("cursor:default"):
                            ui.element("span").classes("dot").style(f"background:{AMBER}")
                            with ui.column().classes("b-nudge-text gap-0"):
                                ui.label(f"{lbl} · {sign}{CUR}{i.amount:,.2f}").classes("font-semibold")
                                ui.label(f"Due {format_date_header(i.next_date).lower()} · {i.cadence}").classes(
                                    "text-xs").style(f"color:{TEXT_DIM}")
                            ui.button("Skip", on_click=lambda _, iid=i.id: _skip(iid)).props(
                                "flat dense no-caps").style(f"color:{TEXT_DIM}")
                            ui.button("Post", icon="check", on_click=lambda _, iid=i.id: _post_now(iid)).props(
                                "unelevated dense no-caps color=primary")

        with ui.expansion("Add scheduled item", icon="add").classes("w-full"):
            with ui.column().classes("gap-1 max-w-xl w-full"):
                kind_toggle = segmented("Type", {"expense": "Expense", "income": "Income"}, "expense")
                ui.label("Amount").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")
                amount_input = ui.number(placeholder="0.00", format="%.2f").props(
                    f'prefix="{CUR}" input-class="text-2xl font-bold"').classes("w-full")
                desc_input = ui.input(label="Description (merchant / payer)").props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1 mt-2"):
                    cadence_select = segmented("Repeats", {"weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly"}, "monthly")
                    next_date_input = date_field("Next date", value=today.isoformat())
                category_select = ui.select(category_options, label="Category", with_input=True).props("dense options-dense").classes("w-full")
                source_select = ui.select(INCOME_SOURCES, value="Other", label="Income source").props("dense options-dense").classes("w-full")
                source_select.set_visibility(False)

                def _sync_kind(e):
                    is_income = e.value == "income"
                    category_select.set_visibility(not is_income)
                    source_select.set_visibility(is_income)
                kind_toggle.on_value_change(_sync_kind)

                auto_switch = ui.switch("Post automatically on the due date", value=True).props("dense color=primary").classes("mt-2")
                ui.label("Off = it waits here for you to confirm each time (good for variable amounts).").classes(
                    "text-xs -mt-1").style(f"color:{TEXT_DIM}")

                def add_item():
                    if not amount_input.value:
                        ui.notify("Enter an amount.", type="warning"); return
                    if not next_date_input.value:
                        ui.notify("Pick a next date.", type="warning"); return
                    is_income = kind_toggle.value == "income"
                    with Session(engine) as session:
                        session.add(ScheduledTransaction(
                            kind=kind_toggle.value,
                            amount=amount_input.value or 0,
                            description=desc_input.value or None,
                            category_id=None if is_income else category_select.value,
                            source=source_select.value if is_income else None,
                            cadence=cadence_select.value,
                            next_date=date.fromisoformat(next_date_input.value),
                            auto_post=auto_switch.value,
                        ))
                        session.commit()
                    ui.notify("Scheduled.", type="positive")
                    content.refresh()

                ui.button("Add scheduled item", on_click=add_item).props("color=primary unelevated")

        if not items:
            with card_box().classes("w-full"):
                empty_state("Nothing scheduled yet -- add a recurring bill, subscription charge, or your salary above.", "event_repeat")

        for title, group in (("Active", [i for i in items if i.active]),
                             ("Paused", [i for i in items if not i.active])):
            if not group:
                continue
            with ui.element("div").classes("b-day"):
                ui.label(title)
                ui.label(str(len(group)))
            with ui.column().classes(LIST_GROUP):
                for i in sorted(group, key=lambda x: x.next_date or date.max):
                    is_income = i.kind == "income"
                    lbl = i.description or ("Income" if is_income else "Expense")
                    bits = [i.cadence.capitalize()]
                    if is_income and i.source:
                        bits.append(i.source)
                    elif not is_income and i.category_id in cats_by_id:
                        bits.append(cats_by_id[i.category_id].name)
                    if i.active and i.next_date:
                        bits.append(f"next {i.next_date.day} {i.next_date:%b}")
                    bits.append("auto" if i.auto_post else "you confirm")
                    list_row("south_west" if is_income else "north_east",
                             (EMERALD if is_income else RED) if i.active else TEXT_DIM, lbl, " · ".join(bits),
                             f"{'+' if is_income else '-'}{CUR}{i.amount:,.2f}",
                             lambda _, iid=i.id: open_item(iid))

    content()
