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
    badge,
    card_box,
    date_field,
    empty_state,
    page_header,
    section_header,
    segmented,
    summary_strip,
)
from ..theme import (
    AMBER,
    EMERALD,
    INDIGO,
    RED,
    SKY,
    SURFACE_2,
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

    page_header("Scheduled", "Recurring transactions and upcoming cashflow.", icon="event_repeat")

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
            with section_header("Upcoming (next 30 days)", icon="date_range", icon_color=SKY,
                                subtitle="Known bills and income from your subscriptions and scheduled items."):
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
                with ui.row().classes("w-full items-center justify-between gap-2 py-0.5 no-wrap"):
                    with ui.row().classes("flex-1 items-center gap-2 min-w-0 no-wrap"):
                        ui.label(e["date"].strftime("%a %d %b")).classes("text-xs w-20 shrink-0").style(f"color:{TEXT_DIM}")
                        ui.label(e["label"]).classes("text-sm min-w-0 truncate").style(f"color:{TEXT}")
                        with ui.element("div").classes("shrink-0"):
                            badge(e["source"], TEXT_DIM)
                    ui.label(f"{sign}{CUR}{e['amount']:,.2f}").classes("text-sm shrink-0 whitespace-nowrap").style(f"color:{color}")

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
                if row:
                    session.delete(row); session.commit()
            ui.notify("Deleted.", type="info")
            content.refresh()

        due = sorted([i for i in active_items if not i.auto_post and i.next_date and i.next_date <= today],
                     key=lambda i: i.next_date)
        if due:
            with card_box().classes("w-full"):
                section_header("Due now", icon="notification_important", icon_color=AMBER, accent=AMBER,
                               subtitle="Confirm to record them, or skip to move to the next date.")
                for i in due:
                    lbl = i.description or ("Income" if i.kind == "income" else "Expense")
                    sign = "+" if i.kind == "income" else "-"
                    with card_box().classes("w-full py-3 flex-row items-center justify-between gap-3").style(f"background:{SURFACE_2}"):
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(f"{lbl} · {sign}{CUR}{i.amount:,.2f}").classes("font-semibold")
                            ui.label(f"Due {format_date_header(i.next_date).lower()} · {i.cadence}").classes("text-xs").style(f"color:{TEXT_DIM}")
                        with ui.row().classes("items-center gap-2 shrink-0"):
                            ui.button("Post now", icon="check", on_click=lambda _, iid=i.id: _post_now(iid)).props("flat dense no-caps color=primary")
                            ui.button("Skip", icon="skip_next", on_click=lambda _, iid=i.id: _skip(iid)).props("flat dense no-caps").style(f"color:{TEXT_DIM}")

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

        for i in sorted(items, key=lambda x: (not x.active, x.next_date or date.max)):
            is_income = i.kind == "income"
            color = EMERALD if is_income else RED
            icon = "trending_up" if is_income else "trending_down"
            lbl = i.description or ("Income" if is_income else "Expense")
            with card_box().classes("w-full py-3 flex-row items-center justify-between gap-2 no-wrap"):
                with ui.row().classes("flex-1 items-center gap-3 min-w-0 no-wrap"):
                    ui.icon(icon).classes("text-2xl shrink-0").style(f"color:{color if i.active else TEXT_DIM}")
                    with ui.column().classes("gap-0 min-w-0"):
                        with ui.row().classes("items-center gap-2 min-w-0 no-wrap w-full"):
                            ui.label(lbl).classes("font-semibold truncate" + ("" if i.active else " line-through")).style(
                                f"color:{TEXT if i.active else TEXT_DIM}")
                            badge("Auto" if i.auto_post else "Confirm", INDIGO if i.auto_post else AMBER)
                            if not i.active:
                                badge("Paused", TEXT_DIM)
                        sub = f"{'+' if is_income else '-'}{CUR}{i.amount:,.2f} · {i.cadence}"
                        if is_income and i.source:
                            sub += f" · {i.source}"
                        elif not is_income and i.category_id in cats_by_id:
                            sub += f" · {_category_label(cats_by_id[i.category_id], categories)}"
                        ui.label(sub).classes("text-xs truncate w-full").style(f"color:{TEXT_DIM}")
                        if i.next_date:
                            ui.label(f"Next: {format_date_header(i.next_date).lower()}").classes("text-xs truncate w-full").style(f"color:{TEXT_DIM}")
                with ui.row().classes("items-center gap-2 shrink-0 no-wrap"):
                    ui.switch(value=i.active, on_change=lambda e, iid=i.id: _toggle_active(iid, e.value)).props(
                        "color=primary dense").tooltip("Active / Paused")
                    ui.button(icon="delete", on_click=lambda _, iid=i.id: _delete(iid)).props("flat round dense color=red")

    content()
