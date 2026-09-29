"""The savings page."""
from datetime import date, timedelta

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    Category,
    SavingsGoal,
    Transaction,
)

from ..common import CUR, DISCRETIONARY_CATEGORIES
from ..components import (
    badge,
    card_box,
    date_field,
    empty_state,
    page_header,
    section_header,
    sheet_dialog,
    summary_strip,
    thin_meter,
    undo_banner,
)
from ..theme import (
    AMBER,
    BORDER,
    EMERALD,
    INDIGO,
    SKY,
    SURFACE,
    TEXT_DIM,
    VIOLET,
)
from .dashboard import render_monthly_net


def savings_page():
    adder = {}
    page_header("Savings Goals", "Targets, pace, and what it takes to hit them.",
                action=("New goal", "add", lambda: adder["open"]()))
    undo_container = ui.column().classes("w-full")
    @ui.refreshable
    def content():
        today = date.today()
        with Session(engine) as session:
            goals = session.exec(select(SavingsGoal)).all()
            _since = today - timedelta(days=90)
            _recent = session.exec(select(Transaction).where(Transaction.date >= _since)).all()
            _cat_name = {c.id: c.name for c in session.exec(select(Category)).all()}
        # Average monthly "flexible" spend over the last ~90 days -- the pool a
        # goal can be funded from without touching essentials.
        discretionary_monthly = sum(
            t.amount for t in _recent if _cat_name.get(t.category_id) in DISCRETIONARY_CATEGORIES
        ) / 3.0

        def _coach(per_month, remaining, disc):
            """One honest line on whether the pace is realistic, measured against
            the person's actual flexible spending (eating out, entertainment, subs)."""
            per_week = per_month / 4.345
            if disc <= 0:
                text, color = (f"About {CUR}{per_week:,.0f} a week. Log a few weeks of spending and Balance "
                               "will show where it could come from.", TEXT_DIM)
            elif per_month <= disc:
                text, color = (f"About {CUR}{per_week:,.0f} a week -- {per_month / disc * 100:.0f}% of your "
                               f"~{CUR}{disc:,.0f}/month flexible spending. Doable.", EMERALD)
            else:
                text, color = (f"That's more than your ~{CUR}{disc:,.0f}/month of flexible spending -- even all of "
                               f"it would take ~{remaining / max(disc, 1):.0f} months.", AMBER)
            ui.label(text).classes("b-hint").style(f"margin:0; color:{color}")

        total_saved = sum(g.saved_amount or 0 for g in goals)
        total_target = sum(g.target_amount or 0 for g in goals)

        summary_strip([
            ("Total saved", f"{CUR}{total_saved:,.0f}", EMERALD),
            ("Target", f"{CUR}{total_target:,.0f} · {len(goals)} goal{'s' if len(goals) != 1 else ''}", INDIGO),
            ("Overall progress", f"{min(total_saved / total_target * 100, 100):.0f}%", AMBER) if total_target else None,
        ])
        render_monthly_net()

        def _contribute(gid, amount):
            with Session(engine) as session:
                g = session.get(SavingsGoal, gid)
                if g:
                    g.saved_amount = (g.saved_amount or 0) + amount
                    session.add(g); session.commit()
                    name = g.name
            ui.notify(f"Added {CUR}{amount:,.2f} to {name}.", type="positive")
            content.refresh()

        def _del(gid):
            with Session(engine) as session:
                g = session.get(SavingsGoal, gid)
                if not g:
                    return
                snapshot = g.model_dump(exclude={"id"})
                session.delete(g)
                session.commit()

            def undo():
                with Session(engine) as session:
                    session.add(SavingsGoal(**snapshot))
                    session.commit()
                ui.notify("Restored.", type="positive")
                content.refresh()

            content.refresh()
            undo_banner(undo_container, f"Deleted {snapshot['name']}.", undo)

        def open_goal(gid):
            with Session(engine) as session:
                g = session.get(SavingsGoal, gid)
                if not g:
                    return
                cur = g.model_dump()
            with ui.dialog() as dialog, ui.card().classes(
                    f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
                section_header(cur["name"], subtitle="Edit goal")
                e_name = ui.input(label="Goal", value=cur["name"]).props("dense").classes("w-full")
                e_target = ui.number(label="Target", value=cur["target_amount"], format="%.2f").props(
                    f'dense prefix="{CUR}"').classes("w-full")
                e_saved = ui.number(label="Saved so far", value=cur["saved_amount"], format="%.2f").props(
                    f'dense prefix="{CUR}"').classes("w-full")
                e_date = date_field("Target date (optional)",
                                    value=cur["target_date"].isoformat() if cur["target_date"] else "")

                def save():
                    with Session(engine) as session:
                        g = session.get(SavingsGoal, gid)
                        if g:
                            g.name = e_name.value or g.name
                            g.target_amount = e_target.value or g.target_amount
                            g.saved_amount = e_saved.value or 0
                            g.target_date = date.fromisoformat(e_date.value) if e_date.value else None
                            session.add(g)
                            session.commit()
                    dialog.close()
                    content.refresh()

                def remove():
                    dialog.close()
                    _del(gid)

                with ui.row().classes("w-full items-center gap-2 mt-2"):
                    ui.button("Delete", icon="delete_outline", on_click=remove).props("flat no-caps color=negative")
                    ui.space()
                    ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                    ui.button("Save", on_click=save).props("color=primary unelevated no-caps")
            dialog.open()

        with sheet_dialog("New savings goal", adder=adder):
            with ui.column().classes("gap-1 max-w-xl w-full"):
                g_name = ui.input(label="Goal (e.g. Emergency fund)").props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-2"):
                    g_target = ui.number(label="Target amount", format="%.2f").props(f'prefix="{CUR}"').classes("w-full")
                    g_date = date_field("Target date (optional)")
                g_start = ui.number(label="Already saved (optional)", value=0, format="%.2f").props(f'prefix="{CUR}"').classes("w-full")

                def add_goal():
                    if not g_name.value or not g_target.value:
                        ui.notify("Give it a name and a target amount.", type="warning"); return
                    with Session(engine) as session:
                        session.add(SavingsGoal(
                            name=g_name.value, target_amount=g_target.value, saved_amount=g_start.value or 0,
                            target_date=date.fromisoformat(g_date.value) if g_date.value else None))
                        session.commit()
                    adder["close"]()
                    ui.notify("Goal created.", type="positive")
                    content.refresh()
                ui.button("Create goal", on_click=add_goal).props("color=primary unelevated")

        if not goals:
            with card_box().classes("w-full"):
                empty_state("No savings goals yet -- add one above to start a sinking fund.", "savings")

        for g in goals:
            saved = g.saved_amount or 0
            target = g.target_amount or 0
            pct = min(saved / target * 100, 100) if target else 0
            reached = bool(target) and saved >= target
            with card_box().classes("w-full gap-3"):
                with section_header(g.name, subtitle=f"{CUR}{saved:,.2f} of {CUR}{target:,.2f}"):
                    if reached:
                        badge("Reached", EMERALD)
                    else:
                        ui.label(f"{pct:.0f}%").classes("text-lg font-bold")
                    ui.button(icon="edit", on_click=lambda _, gid=g.id: open_goal(gid)).props(
                        "flat round dense").classes("b-icon-btn").tooltip("Edit or delete")
                thin_meter(saved, target, EMERALD if reached else INDIGO, height="h-2")
                remaining = max(target - saved, 0)
                days_left = (g.target_date - today).days if g.target_date else None
                per_month = remaining / max(days_left / 30.0, 0.1) if days_left and days_left > 0 else None
                if not reached:
                    summary_strip([
                        ("To go", f"{CUR}{remaining:,.0f}", AMBER),
                        ("By", g.target_date.strftime("%d %b %Y"), SKY,
                         f"{days_left} days left" if days_left and days_left > 0 else "date has passed")
                        if g.target_date else None,
                        ("Needed a month", f"{CUR}{per_month:,.0f}", VIOLET) if per_month else None,
                    ])
                    if per_month:
                        _coach(per_month, remaining, discretionary_monthly)
                    elif not g.target_date and discretionary_monthly > 0:
                        ui.label(f"No date set. Putting all ~{CUR}{discretionary_monthly:,.0f}/month of flexible "
                                 f"spending towards it would get there in ~{remaining / discretionary_monthly:.0f} "
                                 "months.").classes("b-hint").style("margin:0")
                if not reached:
                    with ui.row().classes("w-full items-center gap-2 mt-1"):
                        with ui.element("div").classes("b-pills"):
                            for step in (10, 25, 50):
                                with ui.element("div").classes("b-pill").on(
                                        "click", lambda gid=g.id, st=step: _contribute(gid, st)):
                                    ui.label(f"+{CUR}{step}")
                        amt = ui.number(placeholder="Other", format="%.2f").props(
                            f'prefix="{CUR}" dense outlined').classes("w-28")

                        def contribute(_=None, gid=g.id, amt=amt):
                            if amt.value:
                                _contribute(gid, amt.value)
                        ui.button("Add", on_click=contribute).props("flat dense no-caps color=primary")

    content()
