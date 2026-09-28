"""The income page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    INCOME_SOURCES,
    Income,
)

from ..common import (
    CUR,
    INCOME_ICONS,
    TAG_OPTIONS,
    download_csv,
    format_date_header,
    group_by_date,
)
from ..components import (
    card_box,
    date_field,
    empty_state,
    form_frame,
    page_header,
    section_header,
    summary_strip,
    undo_banner,
)
from ..theme import (
    AMBER,
    BORDER,
    CARD,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    SURFACE,
    TEXT,
    TEXT_DIM,
)
from .dashboard import render_amount_trend, render_income_summary


def render_add_income_form(on_saved=None, compact=False):
    """Builds the add-income form. Reused by both the standalone
    /add-income page and the Add tab on the merged /income page."""
    with form_frame("Add Income", "payments", EMERALD, compact):
        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
            date_input = date_field("Date", value=date.today().isoformat())
            amount_input = ui.number(label=f"Amount ({CUR})", value=0, format="%.2f").props("dense").classes("w-full")
            source_select = ui.select(INCOME_SOURCES, value="Salary", label="Source").props("dense options-dense").classes("w-full")
            payer_input = ui.input(label="From (employer, client, etc.)").props("dense").classes("w-full")
            tag_select = ui.select(TAG_OPTIONS, value="", label="Tag (context)").props("dense options-dense").classes("w-full")
        notes_input = ui.textarea(label="Notes").props("dense").classes("w-full mt-1")
        result_label = ui.label().style(f"color:{EMERALD}")

        def submit():
            with Session(engine) as session:
                entry = Income(
                    date=date.fromisoformat(date_input.value),
                    amount=amount_input.value or 0,
                    source=source_select.value,
                    payer=payer_input.value or None,
                    tag=tag_select.value or None,
                    notes=notes_input.value,
                )
                session.add(entry)
                session.commit()
            result_label.set_text("Saved!")
            amount_input.value = 0
            payer_input.value = ""
            notes_input.value = ""
            if on_saved:
                on_saved()

        ui.button("Save income", on_click=submit).props("color=primary unelevated")


def add_income_page():
    render_add_income_form()


def income_page():
    page_header("Income", "What's coming in, by source and month.", icon="payments")

    _m_start = date.today().replace(day=1)
    with Session(engine) as _s:
        _all_inc = _s.exec(select(Income)).all()
    _month_inc = [i for i in _all_inc if i.date >= _m_start]
    _sources = len({i.source for i in _all_inc if i.source})
    summary_strip([
        ("This month", f"{CUR}{sum(i.amount for i in _month_inc):,.0f}", EMERALD),
        ("All-time", f"{CUR}{sum(i.amount for i in _all_inc):,.0f}", INDIGO),
        ("Sources", str(_sources), AMBER) if _sources else None,
    ])

    with ui.tabs().classes("w-full") as tabs:
        log_tab = ui.tab("Log", icon="list")
        summary_tab = ui.tab("Summary", icon="bar_chart")
        add_tab = ui.tab("Add", icon="add")

    with ui.tab_panels(tabs, value=log_tab).props('swipeable animated transition-prev="fade" transition-next="fade" transition-duration="260"').classes("w-full bg-transparent min-h-[70vh]"):
        with ui.tab_panel(log_tab).classes("p-0 min-h-[70vh]"):
            with ui.row().classes("w-full justify-end pt-4"):
                ui.button("Export CSV", icon="download", on_click=lambda: export_income()).props(
                    "outline dense no-caps color=primary"
                )
            undo_container = ui.column().classes("w-full")
            list_container = ui.column().classes("w-full gap-2")

            def export_income():
                with Session(engine) as session:
                    entries = session.exec(select(Income).order_by(Income.date.desc())).all()
                if not entries:
                    ui.notify("No income to export yet.", type="warning")
                    return
                rows = [
                    [i.date.isoformat(), i.source, i.payer or "", f"{i.amount:.2f}", i.tag or "", i.notes or ""]
                    for i in entries
                ]
                download_csv(
                    ["Date", "Source", "Payer", "Amount", "Tag", "Notes"],
                    rows, f"income-{date.today().isoformat()}.csv",
                )

            _DISPLAY = {"limit": 60}

            def render_list():
                list_container.clear()
                with Session(engine) as session:
                    income_entries = session.exec(select(Income).order_by(Income.date.desc()).limit(200)).all()
                shown = income_entries[:_DISPLAY["limit"]]
                with list_container:
                    if not income_entries:
                        empty_state("No income logged yet -- swipe right or tap \"Add\" to log your first one.", "payments")
                    for group_date, day_entries in group_by_date(shown):
                        day_total = sum(i.amount for i in day_entries)
                        with ui.row().classes("w-full items-baseline justify-between mt-3 mb-1 px-1"):
                            ui.label(format_date_header(group_date)).classes("text-xs font-semibold uppercase tracking-wide").style(f"color:{TEXT_DIM}")
                            ui.label(f"{CUR}{day_total:,.2f}").classes("text-xs font-semibold").style(f"color:{TEXT_DIM}")
                        with ui.column().classes(LIST_GROUP):
                            for idx, i in enumerate(day_entries):
                                if idx:
                                    ui.element("div").classes("h-px w-full").style(f"background:{BORDER}")
                                icon = INCOME_ICONS.get(i.source, "attach_money")
                                with ui.row().classes("w-full items-center justify-between gap-3 px-3 py-2.5"):
                                    with ui.row().classes("items-center gap-3 min-w-0"):
                                        ui.icon(icon).classes("text-xl shrink-0").style(f"color:{EMERALD}")
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(i.payer or i.source).classes("font-medium truncate")
                                            sub = i.source
                                            if i.tag:
                                                sub += f" · {i.tag}"
                                            ui.label(sub).classes("text-xs truncate").style(f"color:{TEXT_DIM}")
                                    with ui.row().classes("items-center gap-1 shrink-0"):
                                        ui.label(f"{CUR}{i.amount:,.2f}").classes("font-semibold").style(f"color:{EMERALD}")
                                        ui.button(icon="edit", on_click=lambda _, iid=i.id: open_edit_income(iid)).props("flat round dense size=sm").tooltip("Edit")
                                        ui.button(icon="delete", on_click=lambda _, iid=i.id: delete_income(iid)).props("flat round dense color=red size=sm")
                    remaining = len(income_entries) - len(shown)
                    if remaining > 0:
                        def _more():
                            _DISPLAY["limit"] += 100
                            render_list()
                        ui.button(f"Show more ({remaining} remaining)", icon="expand_more", on_click=_more).props(
                            "flat no-caps color=primary").classes("self-center mt-2")

            def refresh():
                _DISPLAY["limit"] = 60
                render_list()

            def open_edit_income(iid):
                with Session(engine) as session:
                    obj = session.get(Income, iid)
                    if not obj:
                        return
                    cur = dict(date=obj.date.isoformat(), amount=obj.amount, source=obj.source,
                               payer=obj.payer or "", tag=obj.tag or "", notes=obj.notes or "")

                with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
                    section_header("Edit income", icon="edit", icon_color=EMERALD)
                    e_date = date_field("Date", value=cur["date"])
                    e_amount = ui.number(label="Amount", value=cur["amount"], format="%.2f").props(
                        f'prefix="{CUR}" input-class="text-xl font-bold"'
                    ).classes("w-full")
                    e_source = ui.select(INCOME_SOURCES, value=cur["source"], label="Source").classes("w-full")
                    e_payer = ui.input(label="Payer", value=cur["payer"]).classes("w-full")
                    e_tag = ui.select(TAG_OPTIONS, value=cur["tag"], label="Tag (context)").classes("w-full")
                    e_notes = ui.textarea(label="Notes", value=cur["notes"]).classes("w-full")

                    def save_edit():
                        with Session(engine) as session:
                            obj = session.get(Income, iid)
                            if obj:
                                obj.date = date.fromisoformat(e_date.value)
                                obj.amount = e_amount.value or 0
                                obj.source = e_source.value
                                obj.payer = e_payer.value or None
                                obj.tag = e_tag.value or None
                                obj.notes = e_notes.value or None
                                session.add(obj)
                                session.commit()
                        dialog.close()
                        ui.notify("Income updated.", type="positive")
                        refresh()

                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                        ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                        ui.button("Save", on_click=save_edit).props("color=primary unelevated no-caps")
                dialog.open()

            def delete_income(iid):
                with Session(engine) as session:
                    obj = session.get(Income, iid)
                    if not obj:
                        return
                    snapshot = dict(date=obj.date, amount=obj.amount, source=obj.source,
                                    payer=obj.payer, tag=obj.tag, notes=obj.notes)
                    session.delete(obj)
                    session.commit()

                def undo_delete():
                    with Session(engine) as session:
                        session.add(Income(**snapshot))
                        session.commit()
                    ui.notify("Restored.", type="positive")
                    refresh()

                refresh()
                undo_banner(undo_container, f"Deleted {snapshot['payer'] or snapshot['source']}.", undo_delete)

            refresh()

        with ui.tab_panel(summary_tab).classes("p-0 min-h-[70vh]"):
            with ui.column().classes("w-full gap-3 pt-4"):
                with card_box().classes("w-full"):
                    period_select = ui.select(
                        {"weekly": "Week", "monthly": "Month", "6month": "6 Months", "yearly": "Year", "2year": "2 Years", "all_time": "All time"},
                        value="monthly", label="Period",
                    ).props("dense options-dense").classes("w-40")
                trend_container = ui.column().classes(CARD)
                summary_container = ui.column().classes(CARD)

                def refresh_summary():
                    render_amount_trend(trend_container, Income, Income.date, "Income trend",
                                        "show_chart", EMERALD, period_select.value, date.today(),
                                        empty_hint="No income logged in this period.")
                    render_income_summary(summary_container, period_select.value, date.today())

                period_select.on_value_change(lambda e: refresh_summary())
                refresh_summary()

        with ui.tab_panel(add_tab).classes("p-0 min-h-[70vh]"):
            def on_saved():
                refresh()
                quick_income_card.refresh()
                tabs.set_value(log_tab)

            with ui.column().classes("w-full items-center pt-4 gap-4"):
                @ui.refreshable
                def quick_income_card():
                    """Recurring income (salary, regular clients) as one-tap
                    chips -- re-logs the entry with today's date, closing the
                    'retype your salary every month' loop."""
                    with Session(engine) as session:
                        recent = session.exec(
                            select(Income).order_by(Income.date.desc(), Income.id.desc()).limit(60)
                        ).all()
                    seen, favourites = set(), []
                    for entry in recent:
                        key = (entry.source, (entry.payer or "").strip().lower())
                        if key in seen:
                            continue
                        seen.add(key)
                        favourites.append(entry)
                        if len(favourites) >= 6:
                            break
                    if not favourites:
                        return
                    with card_box().classes("w-full max-w-xl"):
                        section_header("Quick add", icon="bolt", icon_color=EMERALD,
                                       subtitle="Tap to log a repeat of a recent income for today")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            for entry in favourites:
                                icon = INCOME_ICONS.get(entry.source, "attach_money")
                                with ui.button(on_click=lambda _, iid=entry.id: quick_log_income(iid)).props(
                                    "outline dense no-caps"
                                ).classes("normal-case").style(f"border-color:{BORDER}; color:{TEXT};"):
                                    with ui.row().classes("items-center gap-2 no-wrap"):
                                        ui.icon(icon).classes("text-base").style(f"color:{EMERALD}")
                                        with ui.column().classes("gap-0 items-start"):
                                            ui.label(entry.payer or entry.source).classes("text-xs font-medium leading-tight")
                                            ui.label(f"{CUR}{entry.amount:,.2f}").classes("text-[10px] leading-tight").style(f"color:{TEXT_DIM}")

                def quick_log_income(iid):
                    with Session(engine) as session:
                        src = session.get(Income, iid)
                        if not src:
                            return
                        session.add(Income(date=date.today(), amount=src.amount, source=src.source,
                                           payer=src.payer, tag=src.tag, notes=src.notes))
                        session.commit()
                    ui.notify(f"Logged {CUR}{src.amount:,.2f} from {src.payer or src.source}.", type="positive")
                    refresh()
                    quick_income_card.refresh()

                quick_income_card()
                render_add_income_form(on_saved=on_saved)
