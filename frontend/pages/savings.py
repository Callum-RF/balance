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
    summary_strip,
)
from ..theme import (
    AMBER,
    EMERALD,
    INDIGO,
    SURFACE_2,
    TEXT_DIM,
)


def savings_page():
    page_header("Savings Goals", "Targets, pace, and what it takes to hit them.", icon="savings")
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
            """Turn a required monthly saving into honest, non-preachy guidance
            tied to the person's actual flexible spending."""
            per_week = per_month / 4.345
            if disc <= 0:
                ui.label(f"That's ~{CUR}{per_week:,.0f}/week. Log a few weeks of spending and Balance "
                         "will show where it could come from.").classes("text-xs").style(f"color:{TEXT_DIM}")
            elif per_month <= disc:
                share = per_month / disc * 100
                ui.label(f"That's ~{CUR}{per_week:,.0f}/week — about {share:.0f}% of your ~{CUR}{disc:,.0f}/mo "
                         "of flexible spend (dining, coffee, subs). Redirect that and you're on track.").classes(
                    "text-xs").style(f"color:{EMERALD}")
            else:
                realistic = remaining / max(disc, 1)
                ui.label(f"Heads up: this needs {CUR}{per_month:,.0f}/mo, but you have only ~{CUR}{disc:,.0f}/mo "
                         f"of flexible spend. Even redirecting all of it that's ~{realistic:.0f} months — or "
                         "you'd have to trim essentials.").classes("text-xs").style(f"color:{AMBER}")

        total_saved = sum(g.saved_amount or 0 for g in goals)
        total_target = sum(g.target_amount or 0 for g in goals)

        summary_strip([
            ("Total saved", f"{CUR}{total_saved:,.0f}", EMERALD),
            ("Target", f"{CUR}{total_target:,.0f} · {len(goals)} goal{'s' if len(goals) != 1 else ''}", INDIGO),
            ("Overall progress", f"{min(total_saved / total_target * 100, 100):.0f}%", AMBER) if total_target else None,
        ])

        def _contribute(gid, amount):
            with Session(engine) as session:
                g = session.get(SavingsGoal, gid)
                if g:
                    g.saved_amount = (g.saved_amount or 0) + amount
                    session.add(g); session.commit()
            content.refresh()

        def _del(gid):
            with Session(engine) as session:
                g = session.get(SavingsGoal, gid)
                if g:
                    session.delete(g)
                session.commit()
            ui.notify("Goal deleted.", type="info")
            content.refresh()

        with ui.expansion("New goal", icon="add").classes("w-full"):
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
            with card_box().classes("w-full"):
                with section_header(g.name, icon="savings", icon_color=EMERALD,
                                    subtitle=f"{CUR}{saved:,.2f} of {CUR}{target:,.2f}"):
                    if reached:
                        badge("Reached", EMERALD)
                    ui.button(icon="delete", on_click=lambda _, gid=g.id: _del(gid)).props("flat round dense color=red")
                with ui.element("div").classes("w-full rounded-full h-2 mt-1").style(f"background:{SURFACE_2}"):
                    ui.element("div").classes("rounded-full h-2").style(
                        f"background:{EMERALD if reached else INDIGO}; width:{pct}%")
                ui.label(f"{pct:.0f}%").classes("text-xs").style(f"color:{TEXT_DIM}")
                if g.target_date and not reached:
                    days_left = (g.target_date - today).days
                    remaining = target - saved
                    if days_left > 0:
                        per_month = remaining / max(days_left / 30.0, 0.1)
                        ui.label(f"Save {CUR}{per_month:,.2f}/month to reach it by "
                                 f"{g.target_date.strftime('%d %b %Y')} ({days_left} days left).").classes(
                            "text-xs").style(f"color:{TEXT_DIM}")
                        _coach(per_month, remaining, discretionary_monthly)
                    else:
                        ui.label(f"Target date passed -- {CUR}{remaining:,.2f} still to go.").classes(
                            "text-xs").style(f"color:{AMBER}")
                elif not reached and discretionary_monthly > 0:
                    remaining = target - saved
                    months = remaining / discretionary_monthly
                    ui.label(f"No target date. At ~{CUR}{discretionary_monthly:,.0f}/mo of flexible spend, "
                             f"redirecting it all would get you there in ~{months:.0f} months.").classes(
                        "text-xs").style(f"color:{TEXT_DIM}")
                if not reached:
                    with ui.row().classes("w-full items-end gap-2 mt-1"):
                        amt = ui.number(label="Add contribution", format="%.2f").props(f'prefix="{CUR}" dense').classes("w-40")

                        def contribute(_=None, gid=g.id, amt=amt):
                            if amt.value:
                                _contribute(gid, amt.value)
                        ui.button("Add", icon="add", on_click=contribute).props("unelevated no-caps color=primary")

    content()
