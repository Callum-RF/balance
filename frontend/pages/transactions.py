"""The transactions page."""
import os
import uuid
from collections import Counter
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import RECEIPTS_DIR, engine
from backend.models import (
    Category,
    Transaction,
)
from backend.services.categorize import build_history_map, guess_category_id

from ..common import (
    CUR,
    TAG_OPTIONS,
    _category_label,
    _read_upload_bytes,
    category_style,
    download_csv,
    format_date_header,
    group_by_date,
    module_enabled,
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
    segmented,
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
    RED,
    SURFACE,
    TEXT_DIM,
)
from .dashboard import render_amount_trend, render_expenses


# ---------------------------------------------------------------------------
# Add / list transactions
# ---------------------------------------------------------------------------
def render_add_transaction_form(on_saved=None, compact=False):
    """Builds the add-transaction form in whatever container is currently
    active. Reused by both the standalone /add-transaction page and the
    Add tab on the merged /transactions page."""
    with Session(engine) as session:
        categories = session.exec(select(Category)).all()
        all_transactions = session.exec(select(Transaction)).all()
    history_map = build_history_map(all_transactions)
    category_options = {c.id: _category_label(c, categories) for c in categories}
    name_to_id = {c.name: c.id for c in categories}
    id_to_short = {c.id: c.name for c in categories}
    # most-used categories for quick-pick chips (empty until there's history)
    _cat_counts = Counter(t.category_id for t in all_transactions if t.category_id)
    top_category_ids = [cid for cid, _ in _cat_counts.most_common(5)]

    with form_frame("Add Transaction", "add_shopping_cart", AMBER, compact):
        frame = ui.context.slot.parent

        with ui.expansion("Attach receipt photo (optional)", icon="camera_alt").classes("w-full mb-1") as receipt_exp:
            ui.label(
                "Just keeps a copy for your own reference -- nothing is read automatically. "
                "Type the merchant/amount/date yourself while looking at it."
            ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")
            receipt_photo_path = {"value": None}
            receipt_preview_container = ui.column().classes("w-full")
            receipt_status = ui.label().classes("text-xs")

            async def handle_receipt_upload(e):
                try:
                    image_bytes = await _read_upload_bytes(e)
                    filename = f"{uuid.uuid4().hex}.jpg"
                    dest_path = os.path.join(RECEIPTS_DIR, filename)
                    with open(dest_path, "wb") as f:
                        f.write(image_bytes)
                    receipt_photo_path["value"] = filename
                    receipt_status.set_text("Photo attached.")
                    receipt_status.style(f"color:{EMERALD}")
                    receipt_preview_container.clear()
                    with receipt_preview_container:
                        ui.image(f"/receipt-images/{filename}").classes("w-full max-w-xs rounded-lg mt-1")
                except Exception as exc:
                    receipt_status.set_text(f"Couldn't save that photo: {exc}")
                    receipt_status.style(f"color:{RED}")
                try:
                    upload_widget.reset()
                except Exception:
                    pass

            def clear_receipt_photo():
                receipt_photo_path["value"] = None
                receipt_status.set_text("")
                receipt_preview_container.clear()
                try:
                    upload_widget.reset()
                except Exception:
                    pass

            upload_widget = ui.upload(on_upload=handle_receipt_upload, auto_upload=True, max_files=1).props(
                'accept="image/*" capture="environment"'
            ).classes("max-w-full")
            ui.button("Remove photo", icon="close", on_click=clear_receipt_photo).props("flat dense no-caps").classes("mt-1")

        with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1") as date_grid:
            date_input = date_field("Date", value=date.today().isoformat())
            merchant_input = ui.input(label="Merchant").props("dense").classes("w-full")

        payment_input = segmented(
            "Payment method",
            {"Card": "Card", "Cash": "Cash", "Bank Transfer": "Transfer", "Other": "Other"},
            "Card",
        )
        tag_select = ui.select(TAG_OPTIONS, value="", label="Tag (context)").props("dense options-dense").classes("w-full mt-2")

        split_toggle = ui.switch("Split into multiple categorized items", value=False).props("dense color=primary").classes("mt-2")
        split_help = ui.label(
            "e.g. one supermarket trip that covered both groceries and a book -- each item "
            "gets its own category and becomes its own transaction, sharing this date/merchant."
        ).classes("text-xs -mt-1 mb-1").style(f"color:{TEXT_DIM}")

        # --- single-amount mode (default) -- amount is the headline field ---
        with ui.column().classes("w-full gap-1") as single_amount_section:
            # Caption above (not a floating label): the big text-2xl value would
            # otherwise overlap a floating field label.
            ui.label("Amount").classes("text-xs").style(f"color:{TEXT_DIM}")
            amount_input = ui.number(value=0, format="%.2f").props(
                f'prefix="{CUR}" input-class="text-2xl font-bold"'
            ).classes("w-full")
            category_select = ui.select(category_options, label="Category", with_input=True).props("dense options-dense").classes("w-full")

            if top_category_ids:
                with ui.row().classes("w-full gap-1 flex-wrap items-center mt-1"):
                    ui.label("Quick pick:").classes("text-xs").style(f"color:{TEXT_DIM}")
                    for _cid in top_category_ids:
                        ui.button(
                            id_to_short.get(_cid, "?"),
                            on_click=lambda _, cid=_cid: category_select.set_value(cid),
                        ).props("flat dense no-caps size=sm").classes("text-xs")

            def _suggest_category_from_merchant():
                if category_select.value:  # don't override a category already chosen
                    return
                guess = guess_category_id(merchant_input.value, name_to_id, history_map)
                if guess is not None:
                    category_select.value = guess
            merchant_input.on("blur", lambda e: _suggest_category_from_merchant())

        # --- split-into-items mode ---
        with ui.column().classes("w-full gap-2") as items_section:
            items_container = ui.column().classes("w-full gap-2")
            item_rows = []

            def update_items_total():
                total = sum((r["amount"].value or 0) for r in item_rows)
                items_total_label.set_text(f"Items total: {CUR}{total:,.2f}")

            def remove_item_row(entry):
                entry["row"].delete()
                item_rows.remove(entry)
                update_items_total()

            def add_item_row(amount=0.0, description=""):
                with items_container:
                    row_element = ui.row().classes("w-full items-end gap-2")
                with row_element:
                    desc_input = ui.input(label="Item", value=description).props("dense").classes("flex-grow")
                    amt_input = ui.number(label=f"{CUR}", value=amount, format="%.2f").props("dense").classes("w-24")
                    amt_input.on_value_change(lambda e: update_items_total())
                    cat_select = ui.select(category_options, label="Category", with_input=True).props("dense options-dense").classes("flex-grow")
                    entry = {"row": row_element, "description": desc_input, "amount": amt_input, "category": cat_select}
                    ui.button(icon="close", on_click=lambda: remove_item_row(entry)).props("flat round dense color=red")
                item_rows.append(entry)
                update_items_total()

            items_total_label = ui.label(f"Items total: {CUR}0.00").classes("text-sm font-semibold mt-1")
            ui.button("+ Add item", icon="add", on_click=lambda: add_item_row()).props("flat dense no-caps")

        def update_mode_visibility():
            single_amount_section.set_visibility(not split_toggle.value)
            items_section.set_visibility(split_toggle.value)
            split_help.set_visibility(split_toggle.value)  # only relevant in split mode

        split_toggle.on_value_change(lambda e: update_mode_visibility())
        update_mode_visibility()

        notes_input = ui.textarea(label="Notes").props("dense").classes("w-full mt-1")
        result_label = ui.label().style(f"color:{EMERALD}")

        def submit():
            with Session(engine) as session:
                if split_toggle.value:
                    rows_to_save = [r for r in item_rows if (r["amount"].value or 0) > 0]
                    if not rows_to_save:
                        result_label.set_text("Add at least one item with an amount first.")
                        result_label.style(f"color:{RED}")
                        return
                    for r in rows_to_save:
                        session.add(Transaction(
                            date=date.fromisoformat(date_input.value),
                            amount=r["amount"].value or 0,
                            merchant=merchant_input.value,
                            category_id=r["category"].value,
                            payment_method=payment_input.value,
                            tag=tag_select.value or None,
                            notes=r["description"].value or notes_input.value,
                            receipt_image_path=receipt_photo_path["value"],
                        ))
                    session.commit()
                    result_label.set_text(f"Saved {len(rows_to_save)} transactions!")
                    for entry in list(item_rows):
                        entry["row"].delete()
                    item_rows.clear()
                    update_items_total()
                    split_toggle.set_value(False)
                else:
                    t = Transaction(
                        date=date.fromisoformat(date_input.value),
                        amount=amount_input.value or 0,
                        merchant=merchant_input.value,
                        category_id=category_select.value,
                        payment_method=payment_input.value,
                        tag=tag_select.value or None,
                        notes=notes_input.value,
                        receipt_image_path=receipt_photo_path["value"],
                    )
                    session.add(t)
                    session.commit()
                    result_label.set_text("Saved!")
                    result_label.style(f"color:{EMERALD}")
                    amount_input.value = 0

            merchant_input.value = ""
            notes_input.value = ""
            receipt_photo_path["value"] = None
            receipt_preview_container.clear()
            receipt_status.set_text("")
            if on_saved:
                on_saved()

        if compact:
            # In the quick-add sheet the question is "how much, where, what for":
            # those lead, and everything that usually keeps its default (today,
            # card, no tag, no receipt) folds away under More details.
            merchant_input.move(target_container=frame, target_index=0)
            single_amount_section.move(target_container=frame, target_index=1)
            items_section.move(target_container=frame, target_index=2)
            with frame:
                details = ui.expansion("More details", icon="tune",
                                       caption="Date, payment, tag, split, receipt, notes").classes("w-full")
            for element in (date_grid, payment_input.parent_slot.parent, tag_select, split_toggle,
                            split_help, receipt_exp, notes_input):
                element.move(target_container=details)
            result_label.move(target_container=frame)

        ui.button("Save transaction", on_click=submit).props("color=primary unelevated")


def add_transaction_page():
    render_add_transaction_form()


def transactions_page():
    page_header("Transactions", "Every expense, searchable and categorised.")

    @ui.refreshable
    def figures():
        m_start = date.today().replace(day=1)
        with Session(engine) as s:
            all_tx = s.exec(select(Transaction)).all()
        month_tx = [t for t in all_tx if t.date >= m_start]
        summary_strip([
            ("Spent this month", f"{CUR}{sum(t.amount for t in month_tx):,.0f}", AMBER),
            ("This month", f"{len(month_tx)} txns", INDIGO),
            ("All-time total", f"{CUR}{sum(t.amount for t in all_tx):,.0f}", EMERALD),
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
        with Session(engine) as session:
            all_categories = session.exec(select(Category)).all()
        category_names = {c.id: c.name for c in all_categories}
        filter_category_options = {None: "All categories"}
        filter_category_options.update({c.id: _category_label(c, all_categories) for c in all_categories})

        # --- toolbar: search, Filters, and chips for whatever is active ---
        with ui.element("div").classes("b-toolbar"):
            search_input = ui.input(placeholder="Search merchant or notes").props(
                "dense outlined clearable debounce=300").classes("b-field")
            with search_input.add_slot("prepend"):
                ui.icon("search").classes("text-lg").style(f"color:{TEXT_DIM}")
            with ui.button("Filters", icon="tune").props("flat no-caps").classes("b-tool-btn") as filters_btn:
                with ui.menu().props('anchor="bottom right" self="top right"'):
                    with ui.column().classes("b-filters"):
                        category_filter = ui.select(filter_category_options, value=None,
                                                    label="Category").classes("w-full")
                        with ui.row().classes("w-full gap-2 no-wrap"):
                            from_input = date_field("From")
                            to_input = date_field("To")
                        with ui.row().classes("w-full justify-between items-center"):
                            ui.button("Clear all", icon="close", on_click=lambda: clear_filters()).props(
                                "flat dense no-caps")
                            ui.button("Export CSV", icon="download",
                                      on_click=lambda: export_transactions()).props(
                                "outline dense no-caps color=primary")
                        if module_enabled("import"):
                            ui.separator()
                            ui.button("Import a bank statement", icon="upload_file",
                                      on_click=lambda: ui.navigate.to("/import")).props(
                                "flat dense no-caps color=primary").classes("self-start")
        with ui.element("div").classes("b-chips"):
            chips = ui.element("div").classes("b-chips")
            result_summary = ui.label().classes("b-count")

        undo_container = ui.column().classes("w-full")
        list_container = ui.column().classes("w-full gap-0")

    def query_filtered():
        """Returns (transactions, categories_by_id) applying the active filters."""
        with Session(engine) as session:
            query = select(Transaction)
            if category_filter.value is not None:
                query = query.where(Transaction.category_id == category_filter.value)
            if from_input.value:
                query = query.where(Transaction.date >= date.fromisoformat(from_input.value))
            if to_input.value:
                query = query.where(Transaction.date <= date.fromisoformat(to_input.value))
            query = query.order_by(Transaction.date.desc()).limit(500)
            transactions = session.exec(query).all()
            categories = {c.id: c.name for c in session.exec(select(Category)).all()}
        term = (search_input.value or "").strip().lower()
        if term:
            transactions = [
                t for t in transactions
                if term in (t.merchant or "").lower() or term in (t.notes or "").lower()
            ]
        return transactions, categories

    def render_chips():
        """One chip per active filter; tapping a chip removes that filter."""
        chips.clear()
        active = []
        if category_filter.value is not None:
            active.append((category_names.get(category_filter.value, "Category"),
                           lambda: setattr(category_filter, "value", None)))
        if from_input.value:
            active.append((f"From {from_input.value}", lambda: setattr(from_input, "value", "")))
        if to_input.value:
            active.append((f"To {to_input.value}", lambda: setattr(to_input, "value", "")))
        with chips:
            for label, clear in active:
                with ui.element("div").classes("b-chip").on("click", clear):
                    ui.label(label)
                    ui.icon("close")
        filters_btn.classes(add="on") if active else filters_btn.classes(remove="on")

    # Render only a capped number of rows at once -- drawing every one of
    # up to 500 transactions builds thousands of DOM nodes and is slow on
    # mobile. "Show more" reveals the rest in chunks.
    _DISPLAY = {"limit": 60}

    def render_list():
        list_container.clear()
        render_chips()
        transactions, categories = query_filtered()
        filters_active = bool(
            (search_input.value or "").strip() or category_filter.value is not None
            or from_input.value or to_input.value
        )
        if transactions:
            total = sum(t.amount for t in transactions)
            result_summary.set_text(f"{len(transactions)} transaction{'s' * (len(transactions) != 1)}"
                                    f" · {CUR}{total:,.2f}")
        else:
            result_summary.set_text("")
        shown = transactions[:_DISPLAY["limit"]]
        with list_container:
            if not transactions:
                if filters_active:
                    empty_state("No transactions match these filters.", "search_off")
                else:
                    empty_state("No transactions yet -- tap + to add your first one.", "receipt_long")
            for group_date, day_transactions in group_by_date(shown):
                day_total = sum(t.amount for t in day_transactions)
                with ui.element("div").classes("b-day"):
                    ui.label(format_date_header(group_date))
                    ui.label(f"{CUR}{day_total:,.2f}")
                with ui.column().classes(LIST_GROUP):
                    for t in day_transactions:
                        name = categories.get(t.category_id)
                        icon, color = category_style(name)
                        sub = name or "Uncategorized"
                        if t.tag:
                            sub += f" · {t.tag}"
                        if t.receipt_image_path:
                            sub += " · receipt"
                        list_row(icon, color, t.merchant or "Unnamed", sub, f"{CUR}{t.amount:,.2f}",
                                 lambda _, tid=t.id: open_edit_transaction(tid))
            remaining = len(transactions) - len(shown)
            if remaining > 0:
                def _more():
                    _DISPLAY["limit"] += 100
                    render_list()
                ui.button(f"Show more ({remaining} remaining)", icon="expand_more", on_click=_more).props(
                    "flat no-caps color=primary").classes("self-center mt-2")

    def refresh():
        _DISPLAY["limit"] = 60   # reset to the top whenever filters change
        render_list()

    def clear_filters():
        search_input.value = ""
        category_filter.value = None
        from_input.value = ""
        to_input.value = ""
        refresh()

    def export_transactions():
        transactions, categories = query_filtered()
        if not transactions:
            ui.notify("Nothing to export with the current filters.", type="warning")
            return
        rows = [
            [
                t.date.isoformat(), t.merchant or "", f"{t.amount:.2f}",
                categories.get(t.category_id, "Uncategorized"),
                t.payment_method or "", t.tag or "", t.notes or "",
            ]
            for t in transactions
        ]
        download_csv(
            ["Date", "Merchant", "Amount", "Category", "Payment method", "Tag", "Notes"],
            rows, f"transactions-{date.today().isoformat()}.csv",
        )

    search_input.on_value_change(lambda e: refresh())
    category_filter.on_value_change(lambda e: refresh())
    from_input.on_value_change(lambda e: refresh())
    to_input.on_value_change(lambda e: refresh())

    def view_receipt_photo(path):
        with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] p-2"):
            ui.image(f"/receipt-images/{path}").classes("max-w-full")
            ui.button("Close", on_click=dialog.close).props("flat dense no-caps").classes("mt-2")
        dialog.open()

    def open_edit_transaction(tid):
        """The whole entry: edit it, see its receipt, or delete it."""
        with Session(engine) as session:
            t = session.get(Transaction, tid)
            if not t:
                return
            cats = session.exec(select(Category)).all()
            cat_opts = {c.id: _category_label(c, cats) for c in cats}
            current = dict(date=t.date.isoformat(), merchant=t.merchant or "", amount=t.amount,
                           category_id=t.category_id, payment=t.payment_method or "Card",
                           tag=t.tag or "", notes=t.notes or "", receipt=t.receipt_image_path)

        with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
            section_header("Transaction", icon="edit", icon_color=AMBER)
            e_date = date_field("Date", value=current["date"])
            e_merchant = ui.input(label="Merchant", value=current["merchant"]).classes("w-full")
            e_amount = ui.number(label="Amount", value=current["amount"], format="%.2f").props(
                f'prefix="{CUR}" input-class="text-xl font-bold"'
            ).classes("w-full")
            e_category = ui.select(cat_opts, value=current["category_id"], label="Category").classes("w-full")
            e_payment = segmented("Payment method",
                                  {"Card": "Card", "Cash": "Cash", "Bank Transfer": "Transfer", "Other": "Other"},
                                  current["payment"] if current["payment"] in ("Card", "Cash", "Bank Transfer", "Other") else "Card")
            e_tag = ui.select(TAG_OPTIONS, value=current["tag"], label="Tag (context)").classes("w-full")
            e_notes = ui.textarea(label="Notes", value=current["notes"]).classes("w-full")
            if current["receipt"]:
                ui.button("View receipt photo", icon="receipt",
                          on_click=lambda: view_receipt_photo(current["receipt"])).props(
                    "flat dense no-caps color=primary").classes("self-start")

            def save_edit():
                with Session(engine) as session:
                    obj = session.get(Transaction, tid)
                    if obj:
                        obj.date = date.fromisoformat(e_date.value)
                        obj.merchant = e_merchant.value or None
                        obj.amount = e_amount.value or 0
                        obj.category_id = e_category.value
                        obj.payment_method = e_payment.value
                        obj.tag = e_tag.value or None
                        obj.notes = e_notes.value or None
                        session.add(obj)
                        session.commit()
                dialog.close()
                ui.notify("Transaction updated.", type="positive")
                refresh_all()

            def delete_it():
                dialog.close()
                delete_transaction(tid)

            with ui.row().classes("w-full items-center gap-2 mt-2"):
                ui.button("Delete", icon="delete_outline", on_click=delete_it).props(
                    "flat no-caps color=negative")
                ui.space()
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", on_click=save_edit).props("color=primary unelevated no-caps")
        dialog.open()

    def delete_transaction(tid):
        # Snapshot the row's values before deleting so the toast can
        # offer a real undo. The receipt file is deliberately left on
        # disk until undo expires -- deleting it eagerly would make the
        # restore lossy.
        with Session(engine) as session:
            obj = session.get(Transaction, tid)
            if not obj:
                return
            snapshot = {
                "date": obj.date, "amount": obj.amount, "merchant": obj.merchant,
                "category_id": obj.category_id, "payment_method": obj.payment_method,
                "notes": obj.notes, "tag": obj.tag,
                "receipt_image_path": obj.receipt_image_path,
                "is_subscription_payment": obj.is_subscription_payment,
            }
            session.delete(obj)
            session.commit()

        def undo_delete():
            with Session(engine) as session:
                session.add(Transaction(**snapshot))
                session.commit()
            ui.notify("Restored.", type="positive")
            refresh_all()

        refresh_all()
        undo_banner(undo_container, f"Deleted {snapshot['merchant'] or 'transaction'}.", undo_delete)

    def refresh_all():
        figures.refresh()
        refresh()

    refresh()
    # Adding from the + sheet redraws the figures and the list in place.
    set_page_refresh(refresh_all)

    with summary_view:
        period = period_pills(lambda: refresh_summary())
        trend_container = ui.column().classes(CARD)
        summary_container = ui.column().classes(CARD)

        def refresh_summary():
            render_amount_trend(trend_container, Transaction, Transaction.date, "Spending trend",
                                "show_chart", AMBER, period(), date.today(),
                                empty_hint="No spending recorded in this period.")
            render_expenses(summary_container, period(), date.today())

        refresh_summary()
