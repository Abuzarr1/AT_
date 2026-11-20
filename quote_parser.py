"""Parse supplier quotation replies into structured quotes (Sprint 2)."""
from __future__ import annotations

import re
from typing import Iterable, Optional

import config
from extractor import call_with_backoff, get_llm
from schemas import QuoteResult

SYSTEM_PROMPT = """You read a supplier's reply to a request for quotation (email body or PDF text) and extract the offer.

Rules:
- One entry in lines per offered item. Copy part/model numbers exactly as written.
- unit_price and total_price: plain numbers, no currency symbol or thousands separator. null if not stated. NEVER calculate or invent a price.
- currency: 3-letter code (USD, EUR, GBP, PKR, CNY...). If only a symbol is shown, map it ($ -> USD, EUR sign -> EUR).
- quote_ref: our RFQ reference if the reply quotes it (subject line or body), else null.
- lead_time: per line if given per item; otherwise put the single lead time in the top-level lead_time.
- moq, validity, payment_terms, delivery_terms, country_of_origin: exactly as written, null if absent.
- prices_include_tax: true/false only if the text says so.
- alternative_offered: true when the supplier offers a different model than requested.
- declined: true only if the supplier says they cannot or will not quote.
- Ignore email signatures, disclaimers and marketing text.
- Put exclusions, conditions or anything ambiguous in notes."""


def _coerce(raw) -> QuoteResult:
    if raw is None:
        return QuoteResult()
    if isinstance(raw, QuoteResult):
        return raw
    if isinstance(raw, dict):
        return QuoteResult.model_validate(raw)
    raise TypeError(f"Unexpected quote output: {type(raw)}")


def finalize(result: QuoteResult) -> QuoteResult:
    """Deterministic clean-up after the LLM: currency code, line totals, shared lead time."""
    if result.currency:
        result.currency = result.currency.strip().upper()[:3] or None
    for line in result.lines:
        if line.total_price is None and line.unit_price is not None and line.quantity:
            line.total_price = round(line.unit_price * line.quantity, 2)
        if not line.lead_time and result.lead_time:
            line.lead_time = result.lead_time
    return result


def parse_quote(text: str, llm=None) -> QuoteResult:
    llm = llm or get_llm()
    text = (text or "").strip()[: config.MAX_INPUT_CHARS]
    structured = llm.with_structured_output(QuoteResult)
    user = f'Supplier reply:\n"""\n{text}\n"""'
    raw = call_with_backoff(lambda: structured.invoke([("system", SYSTEM_PROMPT), ("human", user)]))
    return finalize(_coerce(raw))


def validate_quote(result: QuoteResult) -> list[str]:
    """Things the buyer should check before saving the quote."""
    issues: list[str] = []
    if result.declined:
        issues.append("Supplier declined to quote.")
    if not result.lines:
        issues.append("No offered items found.")
    if not result.currency:
        issues.append("Currency not found.")
    if not result.validity:
        issues.append("Offer validity not stated.")
    for i, line in enumerate(result.lines, start=1):
        label = (line.part_number or line.description or "item")[:30]
        if line.unit_price is None:
            issues.append(f"Line {i} ({label}): no unit price.")
        if line.unit_price is not None and line.quantity and line.total_price is not None:
            expected = line.unit_price * line.quantity
            if expected and abs(expected - line.total_price) / expected > 0.01:
                issues.append(
                    f"Line {i} ({label}): total {line.total_price:g} does not match "
                    f"{line.quantity:g} x {line.unit_price:g} = {expected:g}."
                )
        if not line.lead_time:
            issues.append(f"Line {i} ({label}): no lead time.")
        if line.alternative_offered:
            issues.append(f"Line {i} ({label}): alternative item offered. Check it is acceptable.")
    return issues


def find_reference(text: str, known_refs: Iterable[str], quoted: Optional[str] = None) -> Optional[str]:
    """Match a reply to one of our RFQ references (exact, then case/space-insensitive)."""
    refs = [r for r in known_refs if r]
    haystack = f"{quoted or ''}\n{text or ''}"
    norm = lambda s: re.sub(r"[\s_]+", "-", s.strip().upper())  # noqa: E731
    for ref in sorted(refs, key=len, reverse=True):
        if ref in haystack:
            return ref
    hay_norm = norm(haystack)
    for ref in sorted(refs, key=len, reverse=True):
        if norm(ref) in hay_norm:
            return ref
    return None
