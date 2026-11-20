import io
from datetime import date

import pytest
from pypdf import PdfReader

from exporter import export_eml
from rfq_drafter import BannedTermError, build_drafts
from rfq_pdf import build_rfq_pdf
from schemas import LineItem, RFQMeta
from suppliers import Supplier

BANNED = ["ACME Power"]
COMPANY = {"name": "Test Traders", "address": "1 Main Rd, Lahore, PAKISTAN", "phone": "+92 300 0000000",
           "email": "sales@test.example", "ntn": "1111111-1", "strn": "0300222333444", "ship_to": "Test Traders, 1 Main Rd, Lahore, PAKISTAN.",
           "accent": "#EA7424", "logo_text": "TT"}
META = RFQMeta(client_reference="T-RFQ-9", delivery_terms="CPT Lahore Airport / FCA", closing_date="05-Nov-2026",
               require_country_of_origin=True, sales_tax_separate=True)


def make_draft(n=2, specs="Size: NPS 3", meta=META, desc="Gate Valve"):
    items = [LineItem(description=desc, brand="Minimax", part_number=f"PN{i}", quantity=i, unit="pcs", specs=specs)
             for i in range(1, n + 1)]
    drafts, _ = build_drafts(items, {"Minimax": Supplier("Minimax", "Mr Ali", "ali@example.com")}, BANNED,
                             "Abuzar", "Test Traders", today=date(2026, 11, 2), meta=meta)
    return drafts[0]


def text_of(pdf: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


def test_international_form_content():
    pdf = build_rfq_pdf(make_draft(), COMPANY, BANNED, "Abuzar Rashid", international=True, issue_date=date(2026, 11, 2))
    assert pdf.startswith(b"%PDF")
    t = text_of(pdf)
    for needle in ("TEST TRADERS", "REQUEST FOR QUOTATION", "T-RFQ-9-MINI", "02-Nov-2026", "05-Nov-2026",
                   "Part No: PN1", "MAKE : MINIMAX", "CPT Lahore Airport / FCA", "country of origin", "Attn: Mr Ali"):
        assert needle in t, needle
    for banned_local in ("NTN", "STRN", "octroi", "1111111-1"):
        assert banned_local not in t, banned_local


def test_local_form_has_tax_ids_and_local_clauses():
    t = text_of(build_rfq_pdf(make_draft(), COMPANY, BANNED, "Abuzar Rashid", international=False))
    for needle in ("NTN 1111111-1", "STRN 0300222333444", "octroi", "Sales Tax amount separately",
                   "Attn: Abuzar Rashid", "TEST TRADERS"):
        assert needle in t, needle


def test_sales_tax_clause_follows_meta_flag():
    meta = RFQMeta(client_reference="T-RFQ-9", sales_tax_separate=False)
    t = text_of(build_rfq_pdf(make_draft(meta=meta), COMPANY, BANNED, "A", international=False))
    assert "Sales Tax amount" not in t


def test_international_delivery_terms_strips_site_name():
    meta = RFQMeta(client_reference="T-RFQ-9", delivery_terms="CPT Haveli Power Plant Site")
    t = text_of(build_rfq_pdf(make_draft(meta=meta), COMPANY, BANNED, "Abuzar Rashid", international=True))
    assert "CPT Lahore Airport / FCA (Incoterms 2020)" in t
    assert "Haveli" not in t



def test_many_items_paginate():
    pdf = build_rfq_pdf(make_draft(n=60), COMPANY, BANNED, "A")
    assert len(PdfReader(io.BytesIO(pdf)).pages) >= 2


def test_restricted_term_is_redacted_before_pdf():
    t = text_of(build_rfq_pdf(make_draft(desc="Valve for ACME Power plant"), COMPANY, BANNED, "A"))
    assert "ACME" not in t and "[REMOVED]" in t


def test_final_guard_blocks_restricted_term_in_company_profile():
    bad = dict(COMPANY, address="ACME Power Road, Lahore")
    with pytest.raises(BannedTermError):
        build_rfq_pdf(make_draft(), bad, BANNED, "A")


def test_eml_attaches_pdf(tmp_path):
    draft = make_draft()
    pdf = build_rfq_pdf(draft, COMPANY, BANNED, "A")
    path = export_eml(draft, draft.to_email, draft.subject, draft.body, BANNED, out_dir=tmp_path / "approved", pdf_bytes=pdf)
    raw = path.read_bytes()
    assert b"application/pdf" in raw and f"{draft.reference}.pdf".encode() in raw
    assert (tmp_path / "approved" / f"{draft.reference}.pdf").exists()


def test_eml_without_pdf_unchanged(tmp_path):
    draft = make_draft()
    path = export_eml(draft, draft.to_email, draft.subject, draft.body, BANNED, out_dir=tmp_path / "approved")
    assert b"application/pdf" not in path.read_bytes()


def test_draft_carries_items_and_meta():
    d = make_draft()
    assert len(d.items) == 2 and d.meta.client_reference == "T-RFQ-9"
