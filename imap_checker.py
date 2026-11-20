"""IMAP inbox checker — polls for supplier quote replies.

Connects to the configured IMAP server, searches INBOX for messages
from known supplier e-mail addresses (or whose subject contains a
known RFQ reference number), and returns a list of match dicts.

All credentials come from .env — nothing is ever printed or logged.
The module is fully testable offline via dependency-injection of a
mock IMAP factory (see tests/test_imap.py).
"""
from __future__ import annotations

import imaplib
import email
import email.header
import os
import re
import time
from datetime import datetime, timezone
from typing import Callable

from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------ config ---
IMAP_HOST = os.getenv("IMAP_HOST", "")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")
IMAP_USE_SSL = os.getenv("IMAP_USE_SSL", "true").lower() != "false"
IMAP_MAILBOX = os.getenv("IMAP_MAILBOX", "INBOX")

# How many recent messages to scan on each poll (keeps it fast)
IMAP_SCAN_LAST_N = int(os.getenv("IMAP_SCAN_LAST_N", "50"))


# ----------------------------------------------------------------- helpers ---

def _decode_header(raw: str) -> str:
    """Decode RFC-2047 encoded mail headers to plain Unicode."""
    parts = email.header.decode_header(raw or "")
    decoded = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            decoded.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(chunk)
    return "".join(decoded)


def _is_configured() -> bool:
    """Return True only when all mandatory IMAP env vars are present."""
    return bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD)


def _build_search_criteria(
    supplier_emails: list[str],
    known_refs: list[str],
) -> list[bytes]:
    """
    Build a list of IMAP SEARCH byte strings to find reply messages.

    We issue one search per supplier e-mail address (FROM) and one per
    RFQ reference in the Subject.  Results are merged and de-duplicated
    by UID in the caller.
    """
    criteria: list[bytes] = []
    for addr in supplier_emails:
        safe = addr.replace('"', "")          # basic injection guard
        criteria.append(f'FROM "{safe}"'.encode())
    for ref in known_refs:
        safe = ref.replace('"', "")
        criteria.append(f'SUBJECT "{safe}"'.encode())
    return criteria


def _fetch_messages(
    imap: imaplib.IMAP4 | imaplib.IMAP4_SSL,
    uids: list[bytes],
) -> list[dict]:
    """Fetch envelope data for a list of message UIDs."""
    messages = []
    for uid in uids:
        typ, body_data = imap.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if typ != "OK" or not body_data or not body_data[0]:
            continue
        raw_header = body_data[0][1] if isinstance(body_data[0], tuple) else b""
        msg = email.message_from_bytes(raw_header)
        messages.append({
            "uid": uid.decode(errors="replace") if isinstance(uid, bytes) else str(uid),
            "from": _decode_header(msg.get("From", "")),
            "subject": _decode_header(msg.get("Subject", "")),
            "date": _decode_header(msg.get("Date", "")),
        })
    return messages


def _match_reply(
    msg: dict,
    supplier_emails: list[str],
    known_refs: list[str],
) -> str | None:
    """
    Return the matched RFQ reference (or supplier email) if this message
    looks like a supplier quote reply, else None.

    Matching rules (case-insensitive):
      1. FROM address contains a known supplier email domain/address.
      2. SUBJECT contains a known RFQ reference number.
    """
    from_lower = msg["from"].lower()
    subject_lower = msg["subject"].lower()

    for addr in supplier_emails:
        if addr.lower() in from_lower:
            return addr

    for ref in known_refs:
        if ref.lower() in subject_lower:
            return ref

    return None


# -------------------------------------------------------------- public API ---

def check_supplier_replies(
    known_refs: list[str],
    supplier_emails: list[str],
    *,
    imap_factory: Callable | None = None,
) -> list[dict]:
    """
    Poll the IMAP inbox and return a list of match dicts for messages that
    look like supplier quote replies.

    Each dict has keys: uid, from, subject, date, matched_ref.

    Parameters
    ----------
    known_refs       : RFQ reference strings to look for in subjects.
    supplier_emails  : Known supplier e-mail addresses to look for in FROM.
    imap_factory     : Optional callable ``(host, port) -> imap_connection``
                       used for testing (injected mock).  When None the real
                       ``imaplib.IMAP4_SSL`` / ``IMAP4`` is used.

    Returns an empty list (never raises) on any connectivity or auth error
    so the sidebar just stays blank when IMAP is unreachable.
    """
    if not _is_configured():
        return []
    if not known_refs and not supplier_emails:
        return []

    try:
        if imap_factory is not None:
            imap = imap_factory(IMAP_HOST, IMAP_PORT)
        elif IMAP_USE_SSL:
            imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=6)
        else:
            imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT, timeout=6)

        imap.login(IMAP_USER, IMAP_PASSWORD)
        imap.select(IMAP_MAILBOX, readonly=True)

        # Collect unique UIDs across all search criteria
        all_uids: set[bytes] = set()
        for criterion in _build_search_criteria(supplier_emails, known_refs):
            typ, data = imap.uid("search", None, criterion)
            if typ == "OK" and data and data[0]:
                for uid in data[0].split():
                    all_uids.add(uid)

        if not all_uids:
            imap.logout()
            return []

        # Limit to the N most-recent by UID (UIDs are roughly chronological)
        sorted_uids = sorted(all_uids, key=lambda u: int(u))[-IMAP_SCAN_LAST_N:]

        raw_messages = _fetch_messages(imap, sorted_uids)
        imap.logout()

        # Filter to only genuine reply matches
        results: list[dict] = []
        seen_uids: set[str] = set()
        for msg in raw_messages:
            if msg["uid"] in seen_uids:
                continue
            matched = _match_reply(msg, supplier_emails, known_refs)
            if matched:
                seen_uids.add(msg["uid"])
                results.append({**msg, "matched_ref": matched})

        return results

    except Exception:  # noqa: BLE001 — never surface IMAP errors to the UI
        return []


def imap_configured() -> bool:
    """Return True when IMAP credentials are present in the environment."""
    return _is_configured()


def poll_supplier_replies(
    known_refs: tuple[str, ...] | list[str],
    supplier_emails: tuple[str, ...] | list[str],
) -> tuple[bool, str, list[dict]]:
    """
    Check connection and poll replies in one call.
    Returns (success: bool, status_message: str, replies: list[dict]).
    """
    ok, status = test_imap_connection()
    if not ok:
        return False, status, []
    replies = check_supplier_replies(list(known_refs), list(supplier_emails))
    return True, status, replies


def test_imap_connection() -> tuple[bool, str]:
    """
    Test IMAP connection and credentials.

    Returns (success: bool, status_message: str).
    Never exposes passwords.
    """
    if not _is_configured():
        return False, "IMAP credentials not configured in .env"

    try:
        if IMAP_USE_SSL:
            imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=8)
        else:
            imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT, timeout=8)
        imap.login(IMAP_USER, IMAP_PASSWORD)
        typ, data = imap.select(IMAP_MAILBOX, readonly=True)
        count = data[0].decode() if (data and data[0]) else "0"
        imap.logout()
        return True, f"Connected ({IMAP_MAILBOX}: {count} messages)"
    except imaplib.IMAP4.error as e:
        return False, f"Login failed: {e}"
    except TimeoutError:
        return False, f"Connection timed out to {IMAP_HOST}:{IMAP_PORT}"
    except Exception as e:
        return False, f"Error ({type(e).__name__}): {e}"


def save_draft_to_imap(eml_bytes: bytes, mailbox: str = "INBOX.Drafts") -> tuple[bool, str]:
    """
    Append a complete draft email (with PDF attachment) to the IMAP Drafts mailbox.

    Returns (success: bool, status_message: str).
    Never sends any email; strictly stores in Drafts folder for human review.
    """
    if not _is_configured():
        return False, "IMAP credentials not configured in .env"

    try:
        if IMAP_USE_SSL:
            imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=10)
        else:
            imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT, timeout=10)
        imap.login(IMAP_USER, IMAP_PASSWORD)

        # Detect Drafts folder name (e.g. INBOX.Drafts or Drafts)
        target_mb = mailbox
        typ, mboxes = imap.list()
        if typ == "OK" and mboxes:
            names = [mb.decode(errors="replace") for mb in mboxes]
            if not any(target_mb in name for name in names):
                for name in names:
                    if "\\Drafts" in name or "Drafts" in name:
                        parts = name.split(' "." ')
                        if len(parts) == 2:
                            target_mb = parts[1].strip('"')
                            break

        typ, res = imap.append(target_mb, "\\Draft", imaplib.Time2Internaldate(time.time()), eml_bytes)
        imap.logout()
        if typ == "OK":
            return True, f"Draft saved to {target_mb} with PDF attached!"
        return False, f"Failed to save draft to {target_mb}: {res}"
    except Exception as e:
        return False, f"Error ({type(e).__name__}): {e}"


