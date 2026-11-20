"""Central configuration for the Procurement Assistant."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"

load_dotenv(BASE_DIR / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
SENDER_NAME = os.getenv("SENDER_NAME", "Abuzar Rashid")
SENDER_COMPANY = os.getenv("SENDER_COMPANY", "Abdullah Traders")
WEBMAIL_URL = os.getenv("WEBMAIL_URL", "https://rc.ds.network/")

# IMAP inbox monitoring (supplier reply notifications)
IMAP_HOST     = os.getenv("IMAP_HOST", "")
IMAP_PORT     = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER     = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")          # never printed / logged
IMAP_USE_SSL  = os.getenv("IMAP_USE_SSL", "true").lower() != "false"
IMAP_MAILBOX  = os.getenv("IMAP_MAILBOX", "INBOX")

MAX_EXTRACT_ATTEMPTS = 2        # first try + one guided retry (protects the Groq token cap)
MAX_RATE_LIMIT_WAIT_S = 90      # waits longer than this mean a daily cap: stop, don't loop
MAX_INPUT_CHARS = 12_000        # trim very long inputs before sending to the LLM

# Lower-case alias -> canonical brand name
BRAND_ALIASES = {
    "siemens": "Siemens",
    "eaton": "Eaton",
    "danfoss": "Danfoss",
    "gf": "GF+",
    "gf+": "GF+",
    "gf piping": "GF+",
    "gf piping systems": "GF+",
    "georg fischer": "GF+",
    "georg fischer piping systems": "GF+",
    "pall": "PALL Corporation",
    "pall corp": "PALL Corporation",
    "pall corporation": "PALL Corporation",
    "schneider": "Schneider Electric",
    "schneider electric": "Schneider Electric",
    "minimax": "Minimax",
}

COMPANY_FILE = DATA_DIR / "company.json"
COMPANY_EXAMPLE_FILE = DATA_DIR / "company.example.json"
SUPPLIERS_FILE = DATA_DIR / "suppliers.csv"
RFQ_LOG_FILE = OUTPUT_DIR / "rfq_log.csv"
QUOTES_FILE = OUTPUT_DIR / "quotes.csv"
_BANNED_REAL = DATA_DIR / "banned_terms.txt"
_BANNED_EXAMPLE = DATA_DIR / "banned_terms.example.txt"
DEFAULT_BANNED_FILE = _BANNED_REAL if _BANNED_REAL.exists() else _BANNED_EXAMPLE


def load_banned_terms(path: Path | None = None) -> list[str]:
    """End-client / project names that must never appear in an outgoing RFQ."""
    path = path or DEFAULT_BANNED_FILE
    if not path.exists():
        return []
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def load_company(path: Path | None = None) -> dict:
    """Company details printed on RFQ forms. Private file first, example as fallback."""
    import json

    path = path or (COMPANY_FILE if COMPANY_FILE.exists() else COMPANY_EXAMPLE_FILE)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault("name", SENDER_COMPANY)
    for key in ("address", "phone", "email", "ntn", "strn", "ship_to"):
        data.setdefault(key, "")
    if not data.get("email"):
        data["email"] = "sales@abdullah-traders.com.pk"
    data.setdefault("accent", "#EA7424")
    data.setdefault("logo_text", "".join(w[0] for w in data["name"].split()[:2]).upper() or "RFQ")
    return data
