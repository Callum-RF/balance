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
    set_page_refresh,
)
from ..components import (
    date_field,
    empty_state,
    form_frame,
    list_row,
    page_header,
    period_pills,
    pill_toggle,
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
    TEXT_DIM,
)
from .dashboard import render_amount_trend, render_income_summary


def render_add_income_form(on_saved=None, compact=False):
    """Builds the add-income form. Reused by both the standalone
    /add-income page and the Add tab on the merged /income page."""
    with form_frame("Add Income", "payments", EMERALD, compact):
        if compact:
            # In the quick-add sheet: how much and from whom lead; the date
            # (usually today), tag and notes fold under More details.
            ui.label("Amount").classes("text-xs").style(f"color:{TEXT_DIM}")
            amount_input = ui.number(value=0, format="%.2f").props(
                f'dense outlined prefix="{CUR}" input-class="text-2xl font-bold"').classes("w-full")
            with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
                payer_input = ui.input(label="From (employer, client, etc.)").props("dense").classes("w-full")
                source_select = ui.select(INCOME_SOURCES, value="Salary", label="Source").props(
                    "dense options-dense").classes("w-full")
            with ui.expansion("More details", icon="tune", caption="Date, tag, notes").classes("w-full"):
                date_input = date_field("Date", value=date.today().isoformat())
                tag_select = ui.select(TAG_OPTIONS, value="", label="Tag (context)").props(
                    "dense options-dense").classes("w-full")
                notes_input = ui.textarea(label="Notes").props("dense").classes("w-full mt-1")
        else:
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


def recent_incomes(limit: int = 6):
    """Your recent distinct incomes (source + payer), for one-tap re-logging:
    salary and regular clients shouldn't need retyping every month."""
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
        if len(favourites) >= limit:
            break
    return favourites


def relog_income(iid):
    """Log a copy of an income entry for today. Returns a short description."""
    with Session(engine) as session:
        src = session.get(Income, iid)
        if not src:
            return None
        session.add(Income(date=date.today(), amount=src.amount, source=src.source,
                           payer=src.payer, tag=src.tag, notes=src.notes))
        session.commit()
        return f"{CUR}{src.amount:,.2f} from {src.payer or src.source}"


def income_page():
    page_header("Income", "What's coming in, by source and month.")

    @ui.refreshable
    def figures():
        m_start = date.today().replace(day=1)
        with Session(engine) as s:
            all_inc = s.exec(select(Income)).all()
        month_inc = [i for i in all_inc if i.date >= m_start]
        sources = len({i.source for i in all_inc if i.source})
        summary_strip([
            ("This month", f"{CUR}{sum(i.amount for i in month_inc):,.0f}", EMERALD),
            ("All-time", f"{CUR}{sum(i.amount for i in all_inc):,.0f}", INDIGO),
            ("Sources", str(sources), AMBER) if sources else None,
        ])

    figures()

    def switch_view(key):
        # Only matters on narrower screens: from 1200px the summary sits
        # beside the log and the pills are hidden (see .b-split).
        log_view.classes(remove="b-off") if key == "log" else log_view.classes(add="b-off")
        summary_view.classes(remove="b-off") if key == "summary" else summary_view.classes(add="b-off")

    with ui.element("div").classes("b-split-pills"):
        pill_toggle({"log": "Log", "summary": "Summary"}, "log", switch_view)

    with ui.element("div").classes("b-split"):
        log_view = ui.column().classes("w-full gap-2 mt-2")
        summary_view = ui.column().classes("w-full gap-3 mt-2 b-off")

    with log_view:
        with ui.element("div").classes("b-toolbar"):
            search_input = ui.input(placeholder="Search payer or notes").props(
                "dense outlined clearable debounce=300").classes("b-field")
            with search_input.add_slot("prepend"):
                ui.icon("search").classes("text-lg").style(f"color:{TEXT_DIM}")
            with ui.button("Filters", icon="tune").props("flat no-caps").classes("b-tool-btn") as filters_btn:
                with ui.menu().props('anchor="bottom right" self="top right"'):
                    with ui.column().classes("b-filters"):
                        source_filter = ui.select({None: "All sources", **{x: x for x in INCOME_SOURCES}},
                                                  value=None, label="Source").classes("w-full")
                        with ui.row().classes("w-full justify-between items-center"):
                            ui.button("Clear", icon="close",
                                      on_click=lambda: setattr(source_filter, "value", None)).props(
                                "flat dense no-caps")
                            ui.button("Export CSV", icon="download", on_click=lambda: export_income()).props(
                                "outline dense no-caps color=primary")
        with ui.element("div").classes("b-chips"):
            chips = ui.element("div").classes("b-chips")
            result_summary = ui.label().classes("b-count")
        undo_container = ui.column().classes("w-full")
        list_container = ui.column().classes("w-full gap-0")

    def query_filtered():
        with Session(engine) as session:
            query = select(Income)
            if source_filter.value:
                query = query.where(Income.source == source_filter.value)
            entries = session.exec(query.order_by(Income.date.desc(), Income.id.desc()).limit(500)).all()
        term = (search_input.value or "").strip().lower()
        if term:
            entries = [i for i in entries
                       if term in (i.payer or "").lower() or term in (i.notes or "").lower()
                       or term in (i.source or "").lower()]
        return entries

    def export_income():
        entries = query_filtered()
        if not entries:
            ui.notify("No income to export.", type="warning")
            return
        rows = [[i.date.isoformat(), i.source, i.payer or "", f"{i.amount:.2f}", i.tag or "", i.notes or ""]
                for i in entries]
        download_csv(["Date", "Source", "Payer", "Amount", "Tag", "Notes"],
                     rows, f"income-{date.today().isoformat()}.csv")

    _DISPLAY = {"limit": 60}

    def render_list():
        list_container.clear()
        chips.clear()
        if source_filter.value:
            with chips:
                with ui.element("div").classes("b-chip").on(
                        "click", lambda: setattr(source_filter, "value", None)):
                    ui.label(source_filter.value)
                    ui.icon("close")
            filters_btn.classes(add="on")
        else:
            filters_btn.classes(remove="on")
        entries = query_filtered()
        result_summary.set_text(
            f"{len(entries)} entr{'ies' if len(entries) != 1 else 'y'} · {CUR}{sum(i.amount for i in entries):,.2f}"
            if entries else "")
        shown = entries[:_DISPLAY["limit"]]
        with list_container:
            if not entries:
                if (search_input.value or "").strip() or source_filter.value:
                    empty_state("No income matches these filters.", "search_off")
                else:
                    empty_state("No income logged yet — tap + and choose Income.", "payments")
            for group_date, day_entries in group_by_date(shown):
                with ui.element("div").classes("b-day"):
                    ui.label(format_date_header(group_date))
                    ui.label(f"{CUR}{sum(i.amount for i in day_entries):,.2f}")
                with ui.column().classes(LIST_GROUP):
                    for i in day_entries:
                        sub = i.source + (f" · {i.tag}" if i.tag else "")
                        list_row(INCOME_ICONS.get(i.source, "attach_money"), EMERALD, i.payer or i.source,
                                 sub, f"+{CUR}{i.amount:,.2f}", lambda _, iid=i.id: open_edit_income(iid))
            remaining = len(entries) - len(shown)
            if remaining > 0:
                def _more():
                    _DISPLAY["limit"] += 100
                    render_list()
                ui.button(f"Show more ({remaining} remaining)", icon="expand_more", on_click=_more).props(
                    "flat no-caps color=primary").classes("self-center mt-2")

    def refresh():
        _DISPLAY["limit"] = 60
        render_list()

    def refresh_all():
        figures.refresh()
        refresh()

    search_input.on_value_change(lambda e: refresh())
    source_filter.on_value_change(lambda e: refresh())

    def open_edit_income(iid):
        """The whole entry: edit it, log it again today, or delete it."""
        with Session(engine) as session:
            obj = session.get(Income, iid)
            if not obj:
                return
            cur = dict(date=obj.date.isoformat(), amount=obj.amount, source=obj.source,
                       payer=obj.payer or "", tag=obj.tag or "", notes=obj.notes or "")

        with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
            section_header("Income")
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
                refresh_all()

            def again():
                dialog.close()
                what = relog_income(iid)
                if what:
                    ui.notify(f"Logged {what} for today.", type="positive")
                refresh_all()

            def delete_it():
                dialog.close()
                delete_income(iid)

            ui.button("Log this again today", icon="replay", on_click=again).props(
                "flat dense no-caps color=primary").classes("self-start")
            with ui.row().classes("w-full items-center gap-2 mt-2"):
                ui.button("Delete", icon="delete_outline", on_click=delete_it).props("flat no-caps color=negative")
                ui.space()
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
            refresh_all()

        refresh_all()
        undo_banner(undo_container, f"Deleted {snapshot['payer'] or snapshot['source']}.", undo_delete)

    refresh()
    set_page_refresh(refresh_all)

    with summary_view:
        period = period_pills(lambda: refresh_summary())
        trend_container = ui.column().classes(CARD)
        summary_container = ui.column().classes(CARD)

        def refresh_summary():
            render_amount_trend(trend_container, Income, Income.date, "Income trend",
                                "show_chart", EMERALD, period(), date.today(),
                                empty_hint="No income logged in this period.")
            render_income_summary(summary_container, period(), date.today())

        refresh_summary()
