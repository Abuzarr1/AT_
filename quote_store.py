"""CSV store for parsed quotes and the RFQ log (Sprint 2). Saving is a human-approved action."""
from __future__ import annotations

import csv
import fcntl
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from schemas import QuoteResult
from utils import sanitize_csv_cell

COLUMNS = [
    "timestamp", "rfq_ref", "supplier", "quote_date", "part_number", "description", "quantity",
    "unit_price", "total_price", "currency", "lead_time", "moq", "country_of_origin",
    "validity", "payment_terms", "delivery_terms", "prices_include_tax", "alternative_offered", "notes", "source",
]


def known_references(path: Optional[Path] = None) -> list[str]:
    path = path or config.RFQ_LOG_FILE
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [row["reference"] for row in csv.DictReader(f) if row.get("reference")]


def save_quote(result: QuoteResult, rfq_ref: str = "", source: str = "", path: Optional[Path] = None) -> int:
    """Append one row per quoted line. Returns the number of rows written."""
    path = path or config.QUOTES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    stamp = datetime.now().isoformat(timespec="seconds")
    rows = 0
    with path.open("a", newline="", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except (AttributeError, OSError):
            pass
        try:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if new:
                writer.writeheader()
            for line in result.lines:
                writer.writerow(
                    {
                        "timestamp": stamp,
                        "rfq_ref": sanitize_csv_cell(rfq_ref),
                        "supplier": sanitize_csv_cell(result.supplier_name or ""),
                        "quote_date": sanitize_csv_cell(result.quote_date or ""),
                        "part_number": sanitize_csv_cell(line.part_number or ""),
                        "description": sanitize_csv_cell(line.description or ""),
                        "quantity": "" if line.quantity is None else line.quantity,
                        "unit_price": "" if line.unit_price is None else line.unit_price,
                        "total_price": "" if line.total_price is None else line.total_price,
                        "currency": sanitize_csv_cell(result.currency or ""),
                        "lead_time": sanitize_csv_cell(line.lead_time or ""),
                        "moq": sanitize_csv_cell(line.moq or ""),
                        "country_of_origin": sanitize_csv_cell(line.country_of_origin or ""),
                        "validity": sanitize_csv_cell(result.validity or ""),
                        "payment_terms": sanitize_csv_cell(result.payment_terms or ""),
                        "delivery_terms": sanitize_csv_cell(result.delivery_terms or ""),
                        "prices_include_tax": "" if result.prices_include_tax is None else result.prices_include_tax,
                        "alternative_offered": line.alternative_offered,
                        "notes": sanitize_csv_cell(" | ".join(x for x in (line.notes, result.notes) if x)),
                        "source": sanitize_csv_cell(source),
                    }
                )
                rows += 1
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (AttributeError, OSError):
                pass
    return rows


def load_quotes(path: Optional[Path] = None) -> list[dict]:
    path = path or config.QUOTES_FILE
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_rfq_log(path: Optional[Path] = None) -> list[dict]:
    path = path or config.RFQ_LOG_FILE
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_all_quotes(rows: list[dict], path: Optional[Path] = None) -> None:
    """Overwrite quotes.csv with the given list of dict rows."""
    path = path or config.QUOTES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except (AttributeError, OSError):
            pass
        try:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            for r in rows:
                writer.writerow({
                    col: sanitize_csv_cell("" if r.get(col) is None else r.get(col))
                    for col in COLUMNS
                })
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (AttributeError, OSError):
                pass


def delete_quotes(indices: list[int], path: Optional[Path] = None) -> int:
    """Delete rows by 0-based indices and save. Returns count deleted."""
    rows = load_quotes(path)
    to_delete = set(indices)
    kept = [row for i, row in enumerate(rows) if i not in to_delete]
    deleted_count = len(rows) - len(kept)
    if deleted_count > 0:
        save_all_quotes(kept, path)
    return deleted_count


def delete_quotes_by_batch(rfq_ref: str, supplier: str, timestamp: str = "", path: Optional[Path] = None) -> int:
    """Delete all rows matching RFQ reference and supplier (and optional timestamp)."""
    rows = load_quotes(path)
    kept = []
    deleted = 0
    for r in rows:
        match_ref = r.get("rfq_ref", "") == rfq_ref
        match_sup = r.get("supplier", "") == supplier
        match_ts = (r.get("timestamp", "") == timestamp) if timestamp else True
        if match_ref and match_sup and match_ts:
            deleted += 1
        else:
            kept.append(r)
    if deleted > 0:
        save_all_quotes(kept, path)
    return deleted

