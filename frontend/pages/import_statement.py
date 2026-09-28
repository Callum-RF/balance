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

from ..common import _category_label, _read_upload_bytes
from ..components import (
    card_box,
    page_header,
    section_header,
    segmented,
)
from ..theme import (
    BORDER,
    EMERALD,
    INDIGO,
    RED,
    TEXT_DIM,
)


# ---------------------------------------------------------------------------
# Import bank statement (CSV or PDF)
# ---------------------------------------------------------------------------
def import_statement_page():
    page_header("Import Statement",
                "Bring in a CSV or PDF bank statement — nothing saves until you review and confirm.",
                icon="upload_file")

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
            with card_box().classes("w-full max-w-xl"):
                section_header("1. Upload a file", icon="upload_file", icon_color=INDIGO)
                upload_status = ui.label().classes("text-xs")

                async def handle_upload(e):
                    upload_status.set_text("Reading file...")
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
                            text = extract_pdf_text(file_bytes)
                            state["table"] = parse_pdf_lines(text)
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
                        return
                    except Exception as exc:
                        upload_status.set_text(f"Couldn't process that file: {exc}")
                        upload_status.style(f"color:{RED}")
                        return

                    render_mapping_step()

                ui.upload(on_upload=handle_upload, auto_upload=True, max_files=1).props(
                    'accept=".csv,.pdf"'
                ).classes("max-w-full")

    # -----------------------------------------------------------------
    def render_mapping_step():
        step_container.clear()
        with step_container:
            if state["source_type"] == "csv":
                render_csv_mapping()
            else:
                render_pdf_mapping()

    def render_csv_mapping():
        headers = state["table"]["headers"]
        header_options = {i: h for i, h in enumerate(headers)}

        with card_box().classes("w-full max-w-2xl"):
            section_header("2. Match up the columns", icon="view_column", icon_color=INDIGO)
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
                day_first = date_format.value in ("DD/MM/YYYY", "DD-MM-YYYY", "DD.MM.YYYY")
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
                ui.button("Continue", on_click=build_candidates).props("color=primary unelevated")

    def render_pdf_mapping():
        line_candidates = state["table"]
        with card_box().classes("w-full max-w-2xl"):
            section_header("2. Confirm date format", icon="event", icon_color=INDIGO)
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
                ui.button("Continue", on_click=build_candidates).props("color=primary unelevated")

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
            with card_box().classes("w-full"):
                section_header("3. Review before importing", icon="fact_check", icon_color=INDIGO)
                num_dupes = sum(1 for c in state["candidates"] if c["is_duplicate"])
                num_expense = sum(1 for c in state["candidates"] if not c["is_income"])
                num_income = sum(1 for c in state["candidates"] if c["is_income"])
                ui.label(
                    f"{len(state['candidates'])} row(s) found: {num_expense} expense, {num_income} income. "
                    f"{num_dupes} look like duplicates of transactions you already have and are unchecked below."
                ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")

                ui.label(
                    "Every field below is editable -- fix anything the parser got wrong before importing."
                ).classes("text-xs mb-2").style(f"color:{TEXT_DIM}")

                rows_container = ui.column().classes("w-full gap-1")
                row_cat_selects = []  # (candidate, select) pairs, for "apply to all" + income toggling
                with rows_container:
                    for c in state["candidates"]:
                        with ui.row().classes("w-full items-center gap-2 py-2 flex-wrap border-b").style(f"border-color:{BORDER}"):
                            checkbox = ui.checkbox(value=c["include"])
                            checkbox.on_value_change(lambda e, cc=c: cc.update({"include": e.value}))

                            date_input = ui.input(value=c["date"].isoformat()).props("dense").classes("w-28")

                            def on_date_change(e, cc=c):
                                try:
                                    cc["date"] = date.fromisoformat(e.value)
                                except ValueError:
                                    pass  # leave the previous value if what they typed isn't a real date

                            date_input.on_value_change(on_date_change)

                            desc_input = ui.input(value=c["description"]).props("dense").classes("flex-grow min-w-[140px]")
                            desc_input.on_value_change(lambda e, cc=c: cc.update({"description": e.value}))

                            amount_input = ui.number(value=c["amount"], format="%.2f").props("dense").classes("w-24")
                            amount_input.on_value_change(lambda e, cc=c: cc.update({"amount": e.value or 0}))

                            direction_toggle = ui.toggle(
                                ["Expense", "Income"], value="Income" if c["is_income"] else "Expense"
                            ).props("dense toggle-color=primary")

                            cat_select = ui.select(
                                category_options, value=c["category_id"], with_input=True,
                            ).props("dense options-dense").classes("w-44")
                            cat_select.on_value_change(lambda e, cc=c: cc.update({"category_id": e.value}))
                            cat_select.set_visibility(not c["is_income"])  # income uses source, not category
                            row_cat_selects.append((c, cat_select))

                            def on_direction(e, cc=c, sel=cat_select):
                                cc["is_income"] = e.value == "Income"
                                sel.set_visibility(not cc["is_income"])
                            direction_toggle.on_value_change(on_direction)

                            if c["is_duplicate"]:
                                ui.label("possible duplicate").classes("text-xs").style(f"color:{TEXT_DIM}")

                with ui.row().classes("items-center gap-2 mb-2 mt-2"):
                    bulk_category_select = ui.select(
                        category_options, value=default_category, label="Set all expenses to…", with_input=True,
                    ).props("dense options-dense").classes("w-64")

                    def apply_to_all():
                        v = bulk_category_select.value
                        for cc, sel in row_cat_selects:
                            cc["category_id"] = v
                            sel.value = v
                    ui.button("Apply to all", on_click=apply_to_all).props("flat dense no-caps")

                result_label = ui.label().classes("mt-2")

                def do_import():
                    to_import = [c for c in state["candidates"] if c["include"]]
                    if not to_import:
                        result_label.set_text("Nothing selected to import.")
                        result_label.style(f"color:{RED}")
                        return
                    created_tx, created_inc = [], []
                    with Session(engine) as session:
                        for c in to_import:
                            if c["is_income"]:
                                entry = Income(date=c["date"], amount=c["amount"], source="Other", payer=c["description"][:200], notes="Imported from statement")
                                session.add(entry)
                                session.commit()
                                session.refresh(entry)
                                created_inc.append(entry.id)
                            else:
                                entry = Transaction(date=c["date"], amount=c["amount"], merchant=c["description"][:200], category_id=c["category_id"], notes="Imported from statement")
                                session.add(entry)
                                session.commit()
                                session.refresh(entry)
                                created_tx.append(entry.id)
                    state["created_ids"] = {"transactions": created_tx, "income": created_inc}
                    render_success_step(len(created_tx), len(created_inc))

                with ui.row().classes("w-full justify-between mt-2"):
                    ui.button("Back", on_click=render_upload_step).props("flat dense no-caps")
                    ui.button("Import selected", on_click=do_import).props("color=primary unelevated")

    # -----------------------------------------------------------------
    def render_success_step(num_tx, num_inc):
        step_container.clear()
        with step_container:
            with card_box().classes("w-full max-w-xl"):
                ui.label("Imported").classes("text-lg font-semibold mb-1").style(f"color:{EMERALD}")
                ui.label(f"Added {num_tx} transaction(s) and {num_inc} income entr{'y' if num_inc == 1 else 'ies'}.").classes("text-sm mb-2")

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

                with ui.row().classes("gap-2"):
                    ui.button("Undo this import", icon="undo", on_click=undo_import).props("flat dense no-caps color=red")
                    ui.link("View Transactions", "/transactions").classes("no-underline").style(f"color:{INDIGO}")
                    ui.button("Import another file", on_click=render_upload_step).props("flat dense no-caps")

    render_upload_step()
