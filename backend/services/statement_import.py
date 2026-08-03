"""
Bank statement import: CSV (reliable, structured -- no guessing involved)
and PDF (best-effort, works well for genuine digital-text statements,
but a scanned/image PDF has no extractable text and gets flagged rather
than silently producing garbage).

Nothing here writes to the database. It only parses and returns
candidate rows for the person to review, edit, and explicitly confirm --
mirroring the lesson learned from receipt scanning: never auto-commit
something extracted from a document.
"""
import csv
import io
import re
from datetime import date, datetime
from typing import Optional


class StatementImportError(Exception):
    pass


# ---------------------------------------------------------------------------
# CSV -- exact, since it's structured data. The only genuine ambiguity is
# date format (e.g. 03/04/2026 could be 3 April or 4 March), which is left
# to the person to pick rather than guessed at.
# ---------------------------------------------------------------------------
def parse_csv(file_bytes: bytes) -> dict:
    """Returns {"headers": [...], "rows": [[...], ...]} for column mapping."""
    try:
        text = file_bytes.decode("utf-8-sig")  # utf-8-sig handles the BOM some banks include
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise StatementImportError("That CSV looks empty.")

    headers = rows[0]
    data_rows = [row for row in rows[1:] if len(row) == len(headers)]
    return {"headers": headers, "rows": data_rows}


DATE_FORMATS = {
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD-MM-YYYY": "%d-%m-%Y",
    "DD.MM.YYYY": "%d.%m.%Y",
}


def parse_date_with_format(value: str, format_key: str) -> Optional[date]:
    fmt = DATE_FORMATS.get(format_key)
    if not fmt or not value:
        return None
    try:
        return datetime.strptime(value.strip(), fmt).date()
    except ValueError:
        return None


def parse_amount(value: str) -> Optional[float]:
    """Handles £, thousands commas, and parentheses-as-negative (a common
    accounting convention some banks use for debits)."""
    if not value:
        return None
    cleaned = value.strip().replace("£", "").replace(",", "").replace(" ", "")
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1]
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:]
    if not cleaned:
        return None
    try:
        amount = float(cleaned)
    except ValueError:
        return None
    return -amount if negative else amount


# ---------------------------------------------------------------------------
# PDF -- best-effort. Only works on genuine digital-text statements; a
# scanned image PDF has no embedded text layer and gets flagged honestly
# rather than guessed at, same lesson as receipt scanning.
# ---------------------------------------------------------------------------
LINE_DATE_PATTERN = re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\b")
LINE_AMOUNT_PATTERN = re.compile(r"-?£?\s?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\b")


def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise StatementImportError("PDF support isn't installed on the server.") from exc

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise StatementImportError(f"Couldn't open that PDF: {exc}") from exc

    text = "\n".join(pages_text)
    # A genuine digital statement has a healthy amount of text per page.
    # A near-empty result almost always means it's a scanned image with no
    # embedded text layer -- flag it rather than pretending it'll work.
    if len(text.strip()) < 50 * max(len(pages_text), 1):
        raise StatementImportError(
            "This PDF doesn't seem to have readable text -- it's likely a scanned image rather "
            "than a digital statement. Exporting a CSV from your bank instead will be far more "
            "reliable."
        )
    return text


def parse_pdf_lines(text: str) -> list:
    """
    Best-effort line-by-line extraction: a line containing both a date and
    a money-shaped value is treated as a transaction candidate. Many bank
    statement lines have two amounts (the transaction, then a running
    balance) -- the first is assumed to be the transaction amount, since
    that's the more common column order, but this is a heuristic, not a
    guarantee. Every row is meant to be reviewed before import.
    """
    candidates = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        date_match = LINE_DATE_PATTERN.search(line)
        amount_matches = LINE_AMOUNT_PATTERN.findall(line)
        if date_match and amount_matches:
            amount_str = amount_matches[0].strip()
            description = line.replace(date_match.group(0), "", 1)
            for amt in amount_matches:
                description = description.replace(amt, "", 1)
            description = description.strip(" -|\t")
            candidates.append({
                "date_str": date_match.group(0),
                "description": description or "(description not detected)",
                "amount_str": amount_str,
                "had_second_amount": len(amount_matches) > 1,
            })
    return candidates
