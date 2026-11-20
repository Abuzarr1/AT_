"""Input helpers (.txt, .md, .pdf, .eml)."""
from __future__ import annotations

import io


def read_input(filename: str, data: bytes) -> str:
    """Return plain text from an uploaded .txt/.md/.pdf file."""
    if filename.lower().endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if filename.lower().endswith(".eml"):
        from email import message_from_bytes, policy

        msg = message_from_bytes(data, policy=policy.default)
        body = msg.get_body(preferencelist=("plain", "html"))
        subject = msg.get("subject", "")
        text = body.get_content() if body is not None else ""
        return f"Subject: {subject}\n\n{text}"
    return data.decode("utf-8", errors="ignore")


def sanitize_csv_cell(val: object) -> object:
    """Neutralize spreadsheet formula injection (CWE-1236) for values written to CSV."""
    if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{val}"
    return val

