"""LLM-based line-item extraction (Groq) with rate-limit-aware retries."""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

import config
from schemas import ExtractionResult
from suppliers import normalize_brand

SYSTEM_PROMPT = """You extract procurement line items from messy client requests (emails, BOMs, chat text).

Rules:
- One entry per distinct item.
- brand: the manufacturer exactly as written (Siemens, Eaton, Danfoss, GF+ ...). null if not stated.
- part_number: the manufacturer order/part code OR model name exactly as written, keeping spaces and punctuation (e.g. "Compact NSX 100N" stays "Compact NSX 100N"). null if not stated. NEVER invent one.
- quantity: an integer. null if not stated.
- unit: pcs, m, kg, set ... default "pcs".
- specs: extra technical details only (rating, size, voltage, module, frequency). Never repeat the description, brand or part number there.
- specs must keep every technical qualifier found in the item text, including descriptive lines such as type, pressure class or standard (e.g. "Rising Stem Gate Valve (CL125)", "CL150", "PN16"). Never drop a qualifier because it looks like a second description line.
- If the source repeats the same text in a "Specs" section, do not duplicate it: capture each item once.
- unit: EACH or PCS means "pcs".
- Ignore letterhead, sender address, tax numbers and phone numbers: they are not items.
- meta.client_reference: the request's own RFQ / reference number if present.
- meta.delivery_terms: delivery terms or Incoterm exactly as written (e.g. "CPT Lahore Airport / FCA").
- meta.closing_date: the quotation deadline as written.
- meta.require_country_of_origin: true only if suppliers are asked to state country of origin.
- meta.sales_tax_separate: true only if sales tax must be shown separately.
- Leave meta fields null/false when the request does not say.
- Do NOT include end-client, project or site names anywhere in your output (keep project titles out of items and meta).
- Put anything ambiguous or contradictory in notes."""


class MissingApiKeyError(RuntimeError):
    pass


class RateLimitExhausted(RuntimeError):
    pass


# ---------- rate-limit handling ----------
_HINT = re.compile(r"try again in\s+((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)", re.IGNORECASE)
_TOKEN = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)", re.IGNORECASE)
_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_wait_seconds(message: str) -> Optional[float]:
    """Read the wait time out of an error like 'Please try again in 7m12.5s'. +1s buffer."""
    match = _HINT.search(message or "")
    if not match:
        return None
    total = sum(float(v) * _UNIT_SECONDS[u.lower()] for v, u in _TOKEN.findall(match.group(1)))
    return total + 1.0


def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "rate_limit" in text or "rate limit" in text


def call_with_backoff(
    fn: Callable,
    max_retries: int = 3,
    max_wait: float = config.MAX_RATE_LIMIT_WAIT_S,
    sleep: Callable[[float], None] = time.sleep,
):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not _is_rate_limit(exc):
                raise
            wait = parse_wait_seconds(str(exc))
            if wait is None:
                wait = min(5 * 2**attempt, max_wait)
            if wait > max_wait:
                raise RateLimitExhausted(
                    f"Groq asks to wait ~{int(wait)}s, which usually means the daily token cap is used up. "
                    "Try again later or switch GROQ_MODEL."
                ) from exc
            if attempt == max_retries:
                raise RateLimitExhausted("Rate limit persisted after several retries.") from exc
            sleep(wait)


# ---------- extraction ----------
def get_llm(api_key: Optional[str] = None, model: Optional[str] = None):
    from langchain_groq import ChatGroq

    key = api_key or config.GROQ_API_KEY
    if not key:
        raise MissingApiKeyError("GROQ_API_KEY is not set (.env or Streamlit secrets).")
    return ChatGroq(model=model or config.GROQ_MODEL, temperature=0, api_key=key)


def _coerce(raw) -> ExtractionResult:
    if raw is None:
        return ExtractionResult(items=[])
    if isinstance(raw, ExtractionResult):
        return raw
    if isinstance(raw, dict):
        return ExtractionResult.model_validate(raw)
    raise TypeError(f"Unexpected extraction output: {type(raw)}")


_MODEL = re.compile(r"^\s*(?:Model|Type|Part\s*(?:No\.?|Number))\s*:\s*([^,;]+?)\s*(?:[,;]\s*|$)", re.IGNORECASE)


def promote_model(item) -> None:
    """If the LLM left part_number empty but specs start with 'Model: X', move X into part_number."""
    if item.part_number or not item.specs:
        return
    match = _MODEL.match(item.specs)
    if match:
        item.part_number = match.group(1).strip()
        item.specs = item.specs[match.end():].strip() or None


def extract_items(text: str, feedback: Optional[str] = None, llm=None) -> ExtractionResult:
    llm = llm or get_llm()
    text = (text or "").strip()[: config.MAX_INPUT_CHARS]
    user = f'Client request:\n"""\n{text}\n"""'
    if feedback:
        user += (
            f"\n\nYour previous attempt had problems: {feedback}\n"
            "Re-read the request and fix them. Use null only when the information is truly absent."
        )
    structured = llm.with_structured_output(ExtractionResult)
    raw = call_with_backoff(lambda: structured.invoke([("system", SYSTEM_PROMPT), ("human", user)]))
    result = _coerce(raw)
    for item in result.items:
        item.brand = normalize_brand(item.brand)
        promote_model(item)
    return result
