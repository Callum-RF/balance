"""The import statement page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    Category,
    Income,
    Transaction,
)
from backend.services.categorize import build_history_map, guess_category_id
from backend.services.statement_import import (
    DATE_FORMATS,
    StatementImportError,
    extract_pdf_text,
    parse_amount,
    parse_csv,
    parse_date_with_format,
    parse_pdf_lines,
)

from ..common import CUR, _category_label, _read_upload_bytes
from ..components import (
    badge,
    card_box,
    card_box_accent,
    page_header,
    section_header,
    segmented,
    summary_strip,
)
from ..theme import (
    AMBER,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    RED,
    TEXT_DIM,
)

STEPS = ["Upload", "Match columns", "Review", "Done"]


def _steps(current):
    """Where you are in the import: done steps ticked, this one highlighted."""
    with ui.element("div").classes("b-steps"):
        for i, name in enumerate(STEPS):
            state = "done" if i < current else "now" if i == current else ""
            with ui.element("div").classes(f"b-step {state}"):
                with ui.element("span").classes("n"):
                    if i < current:
                        ui.icon("check")
                    else:
                        ui.label(str(i + 1))
                ui.label(name).classes("t")


# ---------------------------------------------------------------------------
# Import bank statement (CSV or PDF)
# ---------------------------------------------------------------------------
def import_statement_page():
    page_header("Import a statement",
                "Bring in a CSV or PDF from your bank -- nothing is saved until you've reviewed it.")

    step_container = ui.column().classes("w-full gap-4")
    state = {
        "source_type": None,   # 'csv' or 'pdf'
        "table": None,          # csv: {"headers": [...], "rows": [...]}; pdf: list of line candidates
        "candidates": [],       # unified list of dicts after mapping: {date, description, amount, include, is_duplicate}
        "created_ids": {"transactions": [], "income": []},
    }

    with Session(engine) as session:
        categories = session.exec(select(Category)).all()
    category_options = {c.id: _category_label(c, categories) for c in categories}
    default_category = next((c.id for c in categories if c.name == "Miscellaneous"), None)

    def render_upload_step():
        step_container.clear()
        with step_container:
            _steps(0)
            # A hidden uploader does the work; the drop zone drives it from the
            # browser directly (a tap has to stay a real tap for phones to open
            # the file picker), and hands it files dropped onto the zone.
            uploader = ui.upload(on_upload=lambda e: handle_upload(e), auto_upload=True, max_files=1).props(
                'accept=".csv,.pdf"').classes("b-off")
            pick = "() => getElement(%d).$refs.qRef.pickFiles()" % uploader.id
            drop = ("(e) => { e.currentTarget.classList.remove('over'); "
                    "getElement(%d).$refs.qRef.addFiles(e.dataTransfer.files); }" % uploader.id)
            zone = ui.element("div").classes("b-drop")
            zone.on("click", js_handler=pick)
            zone.on("dragover.prevent", js_handler="(e) => e.currentTarget.classList.add('over')")
            zone.on("dragleave", js_handler="(e) => e.currentTarget.classList.remove('over')")
            zone.on("drop.prevent", js_handler=drop)
            with zone:
                ui.icon("upload_file").classes("b-drop-icon")
                ui.label("Choose a statement").classes("b-drop-title")
                ui.label("CSV or PDF · or drag it here").classes("b-drop-sub")
            upload_status = ui.label().classes("text-sm")
            ui.label("Most banks let you download a statement as CSV from their website or app -- that gives "
                     "the cleanest import. PDFs work too: Balance picks out the lines that look like a date "
                     "next to an amount.").classes("b-hint").style("margin:0")

        async def handle_upload(e):
            upload_status.set_text("Reading the file…")
            upload_status.style(f"color:{TEXT_DIM}")
            try:
                file_bytes = await _read_upload_bytes(e)
                filename = (getattr(e, "file", None) or e)
                filename = getattr(filename, "name", "") or ""
            except Exception as exc:
                upload_status.set_text(f"Couldn't read that file: {exc}")
                upload_status.style(f"color:{RED}")
                return
            try:
                if filename.lower().endswith(".pdf"):
                    state["source_type"] = "pdf"
                    state["table"] = parse_pdf_lines(extract_pdf_text(file_bytes))
                    if not state["table"]:
                        raise StatementImportError(
                            "Couldn't find any lines that look like transactions "
                            "(a date next to an amount) in this PDF."
                        )
                else:
                    state["source_type"] = "csv"
                    state["table"] = parse_csv(file_bytes)
            except StatementImportError as exc:
                upload_status.set_text(str(exc))
                upload_status.style(f"color:{RED}")
                uploader.reset()
                return
            except Exception as exc:
                upload_status.set_text(f"Couldn't process that file: {exc}")
                upload_status.style(f"color:{RED}")
                uploader.reset()
                return
            state["filename"] = filename
            render_mapping_step()

    # -----------------------------------------------------------------
    def render_mapping_step():
        step_container.clear()
        with step_container:
            _steps(1)
            if state["source_type"] == "csv":
                render_csv_mapping()
            else:
                render_pdf_mapping()

    def render_csv_mapping():
        headers = state["table"]["headers"]
        header_options = {i: h for i, h in enumerate(headers)}

        with card_box().classes("w-full"):
            section_header("Which column is which?",
                           subtitle=f"{state.get('filename') or 'Your file'} · {len(state['table']['rows'])} rows")
            with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
                date_col = ui.select(header_options, label="Date column").props("dense options-dense").classes("w-full")
                date_format = ui.select(list(DATE_FORMATS.keys()), value="DD/MM/YYYY", label="Date format").props("dense options-dense").classes("w-full")
                desc_col = ui.select(header_options, label="Description column").props("dense options-dense").classes("w-full")

            split_toggle = ui.switch("Separate Debit and Credit columns", value=False).props("dense color=primary").classes("mt-1")

            with ui.column().classes("w-full gap-1") as single_amount_col:
                amount_col = ui.select(header_options, label="Amount column").props("dense options-dense").classes("w-full")
                sign_convention = segmented(
                    "", ["Negative = expense", "Negative = income"], "Negative = expense"
                )

            with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1") as split_amount_cols:
                debit_col = ui.select(header_options, label="Debit (money out) column").props("dense options-dense").classes("w-full")
                credit_col = ui.select(header_options, label="Credit (money in) column").props("dense options-dense").classes("w-full")
            split_amount_cols.set_visibility(False)

            def toggle_split(e):
                single_amount_col.set_visibility(not e.value)
                split_amount_cols.set_visibility(e.value)

            split_toggle.on_value_change(toggle_split)

            error_label = ui.label().classes("text-xs mt-1").style(f"color:{RED}")

            def build_candidates():
                if date_col.value is None or desc_col.value is None:
                    error_label.set_text("Pick a date column and a description column first.")
                    return
                if not split_toggle.value and amount_col.value is None:
                    error_label.set_text("Pick an amount column, or switch on separate Debit/Credit columns.")
                    return
                if split_toggle.value and (debit_col.value is None or credit_col.value is None):
                    error_label.set_text("Pick both a Debit and a Credit column.")
                    return

                candidates = []
                for row in state["table"]["rows"]:
                    d = parse_date_with_format(row[date_col.value], date_format.value)
                    if not d:
                        continue
                    description = row[desc_col.value].strip()

                    if split_toggle.value:
                        debit = parse_amount(row[debit_col.value]) or 0
                        credit = parse_amount(row[credit_col.value]) or 0
                        if debit:
                            candidates.append({"date": d, "description": description, "amount": abs(debit), "is_income": False})
                        elif credit:
                            candidates.append({"date": d, "description": description, "amount": abs(credit), "is_income": True})
                    else:
                        amt = parse_amount(row[amount_col.value])
                        if amt is None:
                            continue
                        negative_is_expense = sign_convention.value == "Negative = expense"
                        is_income = (amt > 0) if negative_is_expense else (amt < 0)
                        candidates.append({"date": d, "description": description, "amount": abs(amt), "is_income": is_income})

                if not candidates:
                    error_label.set_text(
                        "Couldn't parse any rows with that mapping -- double check the date format and columns."
                    )
                    return

                state["candidates"] = candidates
                render_preview_step()

            with ui.row().classes("w-full justify-between mt-2"):
                ui.button("Back", on_click=render_upload_step).props("flat dense no-caps")
                ui.button("Continue", icon="arrow_forward", on_click=build_candidates).props(
                    "color=primary unelevated no-caps")

    def render_pdf_mapping():
        line_candidates = state["table"]
        with card_box().classes("w-full"):
            section_header("Check the dates", subtitle=state.get("filename") or "Your PDF")
            ui.label(
                f"Found {len(line_candidates)} line(s) that look like transactions (a date next to "
                "an amount). You'll review and can exclude any that aren't real transactions on the next screen."
            ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")
            date_format = ui.select(list(DATE_FORMATS.keys()), value="DD/MM/YYYY", label="Date format").props("dense options-dense").classes("w-48")
            sign_convention = segmented(
                "", ["Negative = expense", "Negative = income"], "Negative = expense"
            ).classes("mt-2")
            error_label = ui.label().classes("text-xs mt-1").style(f"color:{RED}")

            def build_candidates():
                candidates = []
                for c in line_candidates:
                    d = parse_date_with_format(c["date_str"], date_format.value)
                    amt = parse_amount(c["amount_str"])
                    if not d or amt is None:
                        continue
                    negative_is_expense = sign_convention.value == "Negative = expense"
                    is_income = (amt > 0) if negative_is_expense else (amt < 0)
                    candidates.append({"date": d, "description": c["description"], "amount": abs(amt), "is_income": is_income})

                if not candidates:
                    error_label.set_text("Couldn't parse any of the detected lines with that date format.")
                    return
                state["candidates"] = candidates
                render_preview_step()

            with ui.row().classes("w-full justify-between mt-2"):
                ui.button("Back", on_click=render_upload_step).props("flat dense no-caps")
                ui.button("Continue", icon="arrow_forward", on_click=build_candidates).props(
                    "color=primary unelevated no-caps")

    # -----------------------------------------------------------------
    def render_preview_step():
        step_container.clear()

        with Session(engine) as session:
            existing_transactions = session.exec(select(Transaction)).all()
            existing_income = session.exec(select(Income)).all()
        existing_expense_keys = {(t.date, round(t.amount, 2)) for t in existing_transactions}
        existing_income_keys = {(i.date, round(i.amount, 2)) for i in existing_income}

        # Per-row category suggestion: reuse how this merchant was categorised
        # before, else a keyword guess, else the blanket default (Misc).
        history_map = build_history_map(existing_transactions)
        name_to_id = {cat.name: cat.id for cat in categories}

        for c in state["candidates"]:
            key = (c["date"], round(c["amount"], 2))
            c["is_duplicate"] = key in (existing_income_keys if c["is_income"] else existing_expense_keys)
            c["include"] = not c["is_duplicate"]
            guess = guess_category_id(c["description"], name_to_id, history_map)
            c["category_id"] = guess if guess is not None else default_category

        with step_container:
            _steps(2)
            num_dupes = sum(1 for c in state["candidates"] if c["is_duplicate"])
            summary_strip([
                ("Found", str(len(state["candidates"])), INDIGO),
                ("Expenses", str(sum(1 for c in state["candidates"] if not c["is_income"])), AMBER),
                ("Income", str(sum(1 for c in state["candidates"] if c["is_income"])), EMERALD),
                ("Look like duplicates", str(num_dupes), RED, "left unticked") if num_dupes else None,
            ])
            ui.label("Everything below can be edited -- fix anything the file got wrong, and untick rows you "
                     "don't want.").classes("b-hint").style("margin:0")

            row_cat_selects = []  # (candidate, select) pairs, for "set every expense" + income toggling
            with ui.column().classes(LIST_GROUP):
                for c in state["candidates"]:
                    with ui.element("div").classes("b-row b-imp").style("cursor:default"):
                        checkbox = ui.checkbox(value=c["include"]).props("color=primary")
                        checkbox.on_value_change(lambda e, cc=c: cc.update({"include": e.value}))
                        with ui.column().classes("flex-1 min-w-0 gap-1"):
                            desc_input = ui.input(value=c["description"]).props("dense borderless").classes(
                                "w-full b-imp-desc")
                            desc_input.on_value_change(lambda e, cc=c: cc.update({"description": e.value}))
                            with ui.row().classes("w-full items-center gap-2"):
                                amount_input = ui.number(value=c["amount"], format="%.2f").props(
                                    f'dense borderless prefix="{CUR}" input-class="font-bold"').classes("w-28")
                                amount_input.on_value_change(lambda e, cc=c: cc.update({"amount": e.value or 0}))
                                date_input = ui.input(value=c["date"].isoformat()).props("dense borderless").classes(
                                    "w-28 b-imp-date")

                                def on_date_change(e, cc=c):
                                    try:
                                        cc["date"] = date.fromisoformat(e.value)
                                    except ValueError:
                                        pass  # keep the previous value until it's a real date

                                date_input.on_value_change(on_date_change)
                                direction = ui.toggle(["Expense", "Income"],
                                                      value="Income" if c["is_income"] else "Expense").props(
                                    "dense no-caps unelevated toggle-color=primary").classes("seg-toggle text-xs")
                                cat_select = ui.select(category_options, value=c["category_id"], with_input=True).props(
                                    "dense options-dense borderless").classes("w-44")
                                cat_select.on_value_change(lambda e, cc=c: cc.update({"category_id": e.value}))
                                cat_select.set_visibility(not c["is_income"])  # income has a source, not a category
                                row_cat_selects.append((c, cat_select))

                                def on_direction(e, cc=c, sel=cat_select):
                                    cc["is_income"] = e.value == "Income"
                                    sel.set_visibility(not cc["is_income"])
                                direction.on_value_change(on_direction)
                                if c["is_duplicate"]:
                                    badge("Possible duplicate", RED)

            with ui.row().classes("w-full items-end gap-2"):
                bulk_category_select = ui.select(
                    category_options, value=default_category, label="Set every expense to…", with_input=True,
                ).props("dense options-dense").classes("w-64")

                def apply_to_all():
                    v = bulk_category_select.value
                    for cc, sel in row_cat_selects:
                        cc["category_id"] = v
                        sel.value = v
                ui.button("Apply", on_click=apply_to_all).props("flat dense no-caps color=primary")

            result_label = ui.label()

            def do_import():
                to_import = [c for c in state["candidates"] if c["include"]]
                if not to_import:
                    result_label.set_text("Nothing ticked to import.")
                    result_label.style(f"color:{RED}")
                    return
                created_tx, created_inc = [], []
                with Session(engine) as session:
                    for c in to_import:
                        if c["is_income"]:
                            entry = Income(date=c["date"], amount=c["amount"], source="Other",
                                           payer=c["description"][:200], notes="Imported from statement")
                        else:
                            entry = Transaction(date=c["date"], amount=c["amount"], merchant=c["description"][:200],
                                                category_id=c["category_id"], notes="Imported from statement")
                        session.add(entry)
                        session.commit()
                        session.refresh(entry)
                        (created_inc if c["is_income"] else created_tx).append(entry.id)
                state["created_ids"] = {"transactions": created_tx, "income": created_inc}
                render_success_step(len(created_tx), len(created_inc))

            with ui.row().classes("w-full items-center justify-between"):
                ui.button("Start again", icon="arrow_back", on_click=render_upload_step).props("flat dense no-caps")
                ui.button("Import ticked rows", icon="download_done", on_click=do_import).props(
                    "color=primary unelevated no-caps")

    # -----------------------------------------------------------------
    def render_success_step(num_tx, num_inc):
        step_container.clear()
        with step_container:
            _steps(3)
            with card_box_accent().classes("w-full gap-3"):
                section_header("Imported", subtitle="Each one is marked \u201cImported from statement\u201d in its notes.")
                summary_strip([
                    ("Transactions", str(num_tx), AMBER),
                    ("Income", str(num_inc), EMERALD),
                ])

                def undo_import():
                    with Session(engine) as session:
                        for tid in state["created_ids"]["transactions"]:
                            obj = session.get(Transaction, tid)
                            if obj:
                                session.delete(obj)
                        for iid in state["created_ids"]["income"]:
                            obj = session.get(Income, iid)
                            if obj:
                                session.delete(obj)
                        session.commit()
                    state["created_ids"] = {"transactions": [], "income": []}
                    ui.notify("Import undone.", type="warning")
                    render_upload_step()

                with ui.row().classes("w-full items-center gap-2"):
                    ui.button("See transactions", icon="receipt_long",
                              on_click=lambda: ui.navigate.to("/transactions")).props("unelevated no-caps color=primary")
                    ui.button("Import another", on_click=render_upload_step).props("flat no-caps color=primary")
                    ui.space()
                    ui.button("Undo this import", icon="undo", on_click=undo_import).props("flat no-caps color=negative")

    render_upload_step()
