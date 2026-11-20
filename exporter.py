"""Approved-RFQ export + reminder drafts.

Calling export_eml() IS the human approval step — nothing is ever sent automatically.
build_reminder_eml() produces an unsent .eml follow-up for overdue RFQs; again, never sent automatically.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

import config
from rfq_drafter import assert_clean
from schemas import RFQDraft


def export_eml(
    draft: RFQDraft,
    to_email: str,
    subject: str,
    body: str,
    banned: list[str],
    out_dir: Optional[Path] = None,
    pdf_bytes: Optional[bytes] = None,
) -> Path:
    """Re-check the (possibly human-edited) text, write an unsent .eml, and log it."""
    assert_clean(subject, banned)
    assert_clean(body, banned)

    out_dir = out_dir or (config.OUTPUT_DIR / "approved")
    out_dir.mkdir(parents=True, exist_ok=True)

    msg = EmailMessage()
    company = config.load_company()
    sender_email = company.get("email") or "sales@abdullah-traders.com.pk"
    sender_name = config.SENDER_NAME or "Abuzar Rashid"
    msg["From"] = f"{sender_name} <{sender_email}>"
    if to_email:
        msg["To"] = to_email
    msg["Subject"] = subject
    msg["X-Unsent"] = "1"  # opens as an editable draft in Outlook / Thunderbird
    msg.set_content(body)
    if pdf_bytes:
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=f"{draft.reference}.pdf")
        (out_dir / f"{draft.reference}.pdf").write_bytes(pdf_bytes)

    path = out_dir / f"{draft.reference}.eml"
    if path.exists() and to_email:
        user_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", to_email.split("@")[0].strip())
        if user_slug:
            path = out_dir / f"{draft.reference}_{user_slug}.eml"
    path.write_bytes(bytes(msg))

    log = out_dir.parent / "rfq_log.csv"
    new = not log.exists()
    import fcntl
    from utils import sanitize_csv_cell

    with log.open("a", newline="", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except (AttributeError, OSError):
            pass
        try:
            writer = csv.writer(f)
            if new:
                writer.writerow(["timestamp", "reference", "brand", "to_email", "item_count"])
            writer.writerow([
                datetime.now().isoformat(timespec="seconds"),
                sanitize_csv_cell(draft.reference),
                sanitize_csv_cell(draft.brand),
                sanitize_csv_cell(to_email),
                draft.item_count,
            ])
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (AttributeError, OSError):
                pass
    return path


# ---------------------------------------------------------------------------
# Reminder emails
# ---------------------------------------------------------------------------

def build_reminder_eml(
    *,
    draft_ref: str,
    brand: str,
    to_email: str,
    contact_name: str,
    original_items: list[str],
    sent_date: str,
    banned: list[str],
    out_dir: Optional[Path] = None,
) -> tuple[bytes, Path]:
    """Build a polite follow-up .eml for an unanswered RFQ.

    Returns (eml_bytes, file_path).  Nothing is sent — the caller saves / offers a download.
    """
    company = config.load_company()
    sender_email = company.get("email") or "sales@abdullah-traders.com.pk"
    sender_name  = config.SENDER_NAME or "Abuzar Rashid"
    company_name = company.get("name", "Abdullah Traders")

    contact = contact_name.strip() if contact_name and contact_name.strip() else "Sales Team"
    subject = f"Reminder: RFQ – {brand} – {draft_ref}"

    # Build item list block
    item_lines = "\n".join(
        f"  {i + 1}. {item}" for i, item in enumerate(original_items)
    ) if original_items else "  (see original RFQ)"

    body = (
        f"Dear {contact},\n\n"
        f"We hope you are well.\n\n"
        f"We are following up on our Request for Quotation (Ref: {draft_ref}) sent on {sent_date}. "
        f"We have not yet received your quotation and would appreciate your earliest response.\n\n"
        f"Items requested:\n{item_lines}\n\n"
        "Please send your best prices, lead time, and commercial terms at your earliest convenience. "
        "If you require any further information or clarification, do not hesitate to contact us.\n\n"
        "Kind regards,\n"
        f"{sender_name}\n"
        f"Procurement, {company_name}\n"
        f"Mail: {sender_email}\n"
    )

    assert_clean(subject, banned)
    assert_clean(body, banned)

    msg = EmailMessage()
    msg["From"]     = f"{sender_name} <{sender_email}>"
    msg["To"]       = to_email
    msg["Subject"]  = subject
    msg["X-Unsent"] = "1"
    msg.set_content(body)

    eml_bytes = bytes(msg)

    out_dir = out_dir or (config.OUTPUT_DIR / "approved")
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_ref = re.sub(r"[^A-Za-z0-9._-]", "-", draft_ref)
    path = out_dir / f"REMINDER-{safe_ref}.eml"
    path.write_bytes(eml_bytes)

    return eml_bytes, path

