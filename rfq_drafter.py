"""Deterministic RFQ drafting with end-client redaction.

Emails are built from a template (not free LLM text) so the rules always hold:
restricted names are removed, then the final text is re-checked and blocked if any remain.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date
from typing import Optional

from schemas import LineItem, RFQDraft, RFQMeta
from suppliers import Supplier, normalize_brand

UNASSIGNED = "Unassigned"


class BannedTermError(ValueError):
    """Raised when text still contains a restricted (end-client) term."""


def _pattern(term: str) -> re.Pattern:
    parts = [re.escape(p) for p in re.split(r"\s+", term.strip()) if p]
    if not parts:
        return re.compile(r"$^")
    body = r"\s+".join(parts)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def find_banned(text: str, banned: list[str]) -> list[str]:
    return [t for t in banned if t and _pattern(t).search(text or "")]


def redact(text: Optional[str], banned: list[str]) -> tuple[str, list[str]]:
    out = text or ""
    found = []
    for term in banned:
        if not term:
            continue
        pat = _pattern(term)
        if pat.search(out):
            found.append(term)
            out = pat.sub("[REMOVED]", out)
    return out, found


def assert_clean(text: str, banned: list[str]) -> None:
    found = find_banned(text, banned)
    if found:
        raise BannedTermError(f"Blocked: text contains restricted term(s): {', '.join(found)}")


def group_by_brand(items: list[LineItem]) -> "OrderedDict[str, list[LineItem]]":
    groups: "OrderedDict[str, list[LineItem]]" = OrderedDict()
    for item in items:
        brand = normalize_brand(item.brand) or UNASSIGNED
        groups.setdefault(brand, []).append(item)
    return groups


def _item_line(n: int, item: LineItem) -> str:
    part = item.part_number or "Part no. not specified"
    qty = item.quantity if item.quantity else "TBC"
    unit = item.unit or "pcs"
    line = f"{n}. {part} | {item.description} | Qty: {qty} {unit}"
    if item.specs:
        line += f" | {item.specs}"
    return line


def _clean_meta(meta: Optional[RFQMeta], banned: list[str], warnings: list[str], brand: str) -> RFQMeta:
    """Redact restricted terms inside the request-level fields."""
    meta = meta or RFQMeta()
    cleaned = meta.model_copy()
    for field in ("client_reference", "delivery_terms", "closing_date"):
        value = getattr(meta, field)
        if value:
            new, found = redact(value, banned)
            if found:
                warnings.append(f"{brand}: restricted term removed from {field.replace('_', ' ')} ({', '.join(found)})")
            setattr(cleaned, field, new)
    return cleaned


def _reference(meta: RFQMeta, code: str, today: date, seq: int) -> str:
    if meta.client_reference:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", meta.client_reference.strip()).strip("-")
        if safe:
            return f"{safe}-{code}"
    return f"RFQ-{today:%Y%m%d}-{code}-{seq:02d}"


def build_rfq(
    brand: str,
    items: list[LineItem],
    supplier: Optional[Supplier],
    sender_name: str,
    company: str,
    banned: list[str],
    today: Optional[date] = None,
    seq: int = 1,
    meta: Optional[RFQMeta] = None,
) -> tuple[RFQDraft, list[str]]:
    today = today or date.today()
    warnings: list[str] = []
    meta = _clean_meta(meta, banned, warnings, brand)

    clean_items = []
    for n, item in enumerate(items, start=1):
        desc, f1 = redact(item.description, banned)
        specs, f2 = redact(item.specs, banned)
        part, f3 = redact(item.part_number, banned)
        found = sorted(set(f1 + f2 + f3))
        if found:
            warnings.append(f"{brand}: restricted term removed from item {n} ({', '.join(found)})")
        clean_items.append(
            LineItem(
                description=desc,
                brand=item.brand,
                part_number=part or None,
                quantity=item.quantity,
                unit=item.unit,
                specs=specs or None,
            )
        )

    code = re.sub(r"[^A-Z0-9]", "", brand.upper())[:4] or "GEN"
    reference = _reference(meta, code, today, seq)
    contact = (supplier.contact_name if supplier else "") or "Sales Team"
    lines = "\n".join(_item_line(i, it) for i, it in enumerate(clean_items, start=1))

    terms = []
    if meta.delivery_terms:
        d_term = meta.delivery_terms
        if any(w in d_term.lower() for w in ["haveli", "bahadur", "jhang", "ccpp", "plant", "site"]):
            d_term = "CPT Lahore Airport / Delivered to our Lahore facility"
        terms.append(f"Delivery terms: {d_term}")
    if meta.closing_date:
        terms.append(f"Please respond by: {meta.closing_date}")
    terms_block = ("\n".join(terms) + "\n\n") if terms else ""

    asks = [
        "- Unit price and total price (state currency and Incoterm / delivery basis)",
        "- Lead time",
        "- Minimum order quantity (if applicable)",
        "- Quotation validity",
        "- Payment terms",
    ]
    if meta.require_country_of_origin:
        asks.append("- Country of origin")
    if meta.sales_tax_separate:
        asks.append("- Sales tax amount shown separately")

    body = (
        f"Dear {contact},\n\n"
        "Please provide your best quotation for the following items:\n\n"
        f"{lines}\n\n"
        f"{terms_block}"
        "In your quotation, please include:\n"
        + "\n".join(asks)
        + "\n\n"
        "Kind regards,\n"
        f"{sender_name}\n"
        f"{company}\n"
    )
    count = len(clean_items)
    if brand == UNASSIGNED:
        subject = f"Request for Quotation - {count} item(s) - {reference}"
    else:
        subject = f"Request for Quotation - {brand} - {count} item(s) - {reference}"

    assert_clean(body, banned)
    assert_clean(subject, banned)

    draft = RFQDraft(
        reference=reference,
        brand=brand,
        to_email=supplier.email if supplier else "",
        contact_name=supplier.contact_name if supplier else "",
        subject=subject,
        body=body,
        item_count=count,
        items=clean_items,
        meta=meta,
    )
    return draft, warnings


def build_drafts(
    items: list[LineItem],
    suppliers: dict[str, Supplier] | dict[str, list[Supplier]],
    banned: list[str],
    sender_name: str,
    company: str,
    today: Optional[date] = None,
    meta: Optional[RFQMeta] = None,
) -> tuple[list[RFQDraft], list[str]]:
    """Route items by brand and build RFQ drafts (one per supplier contact, sharing the brand RFQ number)."""
    warnings: list[str] = []
    if not items:
        return [], ["No items to draft."]

    drafts: list[RFQDraft] = []
    for seq, (brand, group) in enumerate(group_by_brand(items).items(), start=1):
        brand_suppliers = suppliers.get(brand) if suppliers else None
        if brand_suppliers is None:
            supplier_list: list[Optional[Supplier]] = []
        elif isinstance(brand_suppliers, (list, tuple)):
            supplier_list = list(brand_suppliers)
        else:
            supplier_list = [brand_suppliers]

        if brand == UNASSIGNED:
            warnings.append(f"{len(group)} item(s) have no brand. Assign a brand before sending.")
            draft, w = build_rfq(brand, group, None, sender_name, company, banned, today, seq, meta)
            drafts.append(draft)
            warnings.extend(w)
        elif not supplier_list:
            warnings.append(f"No supplier on file for {brand}. Add it to data/suppliers.csv.")
            draft, w = build_rfq(brand, group, None, sender_name, company, banned, today, seq, meta)
            drafts.append(draft)
            warnings.extend(w)
        else:
            for supplier in supplier_list:
                draft, w = build_rfq(brand, group, supplier, sender_name, company, banned, today, seq, meta)
                drafts.append(draft)
                warnings.extend(w)

    seen = set()
    unique_warnings = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            unique_warnings.append(w)
    return drafts, unique_warnings
