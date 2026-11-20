"""Data models shared across the pipeline."""
from __future__ import annotations

from typing import List, Optional

import re

from pydantic import BaseModel, Field, field_validator


class LineItem(BaseModel):
    description: str = Field(description="Short item description, e.g. 'Circuit Breaker' or 'Contactor 3-pole'")
    brand: Optional[str] = Field(default=None, description="Manufacturer exactly as written, null if absent")
    part_number: Optional[str] = Field(default=None, description="Manufacturer order code or model, null if absent")
    quantity: Optional[int] = Field(default=None, description="Integer quantity, null if absent")
    unit: Optional[str] = Field(default="pcs", description="Unit of measure: pcs, m, kg, set ... (EACH means pcs)")
    specs: Optional[str] = Field(default=None, description="Extra technical details only; never repeat description, brand or part number")


class RFQMeta(BaseModel):
    """Request-level details that apply to every supplier RFQ."""

    client_reference: Optional[str] = Field(default=None, description="The request's own RFQ/reference number, e.g. AT-RFQ-00112")
    delivery_terms: Optional[str] = Field(default=None, description="Delivery terms / Incoterm as written, e.g. 'CPT Lahore Airport / FCA'")
    closing_date: Optional[str] = Field(default=None, description="Deadline for quotations, as written")
    require_country_of_origin: bool = Field(default=False, description="True if the request asks suppliers to state country of origin")
    sales_tax_separate: bool = Field(default=False, description="True if the request asks for sales tax to be shown separately")


class ExtractionResult(BaseModel):
    items: List[LineItem] = Field(default_factory=list)
    meta: RFQMeta = Field(default_factory=RFQMeta)
    notes: Optional[str] = Field(default=None, description="Anything ambiguous the buyer should check")


class RFQDraft(BaseModel):
    reference: str
    brand: str
    to_email: str = ""
    contact_name: str = ""
    subject: str
    body: str
    item_count: int
    items: List[LineItem] = Field(default_factory=list)
    meta: RFQMeta = Field(default_factory=RFQMeta)


# ---------- supplier quotes (Sprint 2) ----------
def to_number(value):
    """'USD 1,250.50' -> 1250.5; None/'' -> None; unparseable -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^0-9.,\-]", "", str(value))
    if not text or text in {"-", ".", ","}:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):      # European style: 1.250,50
            text = text.replace(".", "").replace(",", ".")
        else:                                       # US style: 1,250.50
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = head.replace(",", "") + ("." + tail if len(tail) <= 2 else tail)
    try:
        return float(text)
    except ValueError:
        return None


class QuoteLine(BaseModel):
    part_number: Optional[str] = Field(default=None, description="Part / model offered, as written")
    description: Optional[str] = Field(default=None, description="Short item description")
    quantity: Optional[float] = Field(default=None, description="Quantity quoted")
    unit_price: Optional[float] = Field(default=None, description="Price per unit as a plain number, no currency symbol")
    total_price: Optional[float] = Field(default=None, description="Line total as a plain number, null if not stated")
    lead_time: Optional[str] = Field(default=None, description="Lead time as written, e.g. '4-6 weeks'")
    moq: Optional[str] = Field(default=None, description="Minimum order quantity as written")
    country_of_origin: Optional[str] = Field(default=None, description="Country of origin if stated")
    alternative_offered: bool = Field(default=False, description="True if the supplier offers a different/alternative item than requested")
    notes: Optional[str] = Field(default=None, description="Line-specific remarks")

    @field_validator("quantity", "unit_price", "total_price", mode="before")
    @classmethod
    def _numbers(cls, v):
        return to_number(v)


class QuoteResult(BaseModel):
    supplier_name: Optional[str] = Field(default=None, description="Company that sent the quote")
    quote_ref: Optional[str] = Field(default=None, description="Our RFQ reference quoted in the reply (e.g. AT-RFQ-00112-SCHN), null if absent")
    quote_date: Optional[str] = Field(default=None, description="Date of the quotation as written")
    currency: Optional[str] = Field(default=None, description="3-letter currency code, e.g. USD, EUR, PKR")
    validity: Optional[str] = Field(default=None, description="Offer validity as written, e.g. '30 days'")
    payment_terms: Optional[str] = Field(default=None, description="Payment terms as written")
    delivery_terms: Optional[str] = Field(default=None, description="Incoterm / delivery basis as written")
    lead_time: Optional[str] = Field(default=None, description="Overall lead time when given once for all items")
    prices_include_tax: Optional[bool] = Field(default=None, description="True/false if the quote says prices include/exclude sales tax, null if unstated")
    declined: bool = Field(default=False, description="True if the supplier declines to quote")
    lines: List[QuoteLine] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None, description="Conditions, exclusions or anything the buyer should check")
