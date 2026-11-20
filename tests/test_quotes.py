import csv

import pytest

from extractor import RateLimitExhausted
from quote_parser import finalize, find_reference, parse_quote, validate_quote
from quote_store import (
    delete_quotes,
    delete_quotes_by_batch,
    known_references,
    load_quotes,
    save_all_quotes,
    save_quote,
)
from schemas import QuoteLine, QuoteResult, to_number
from utils import read_input


class FakeLLM:
    def __init__(self, output):
        self.output = output

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        return self.output


def test_to_number():
    assert to_number("USD 1,250.50") == 1250.5
    assert to_number("EUR 1.250,50") == 1250.5
    assert to_number("12,5") == 12.5
    assert to_number("1,250") == 1250.0
    assert to_number(None) is None and to_number("") is None and to_number("n/a") is None
    assert to_number(7) == 7.0 and to_number(True) is None


def test_lines_coerce_string_prices():
    line = QuoteLine(unit_price="USD 1,412.50", quantity="2", total_price="2,825.00")
    assert line.unit_price == 1412.5 and line.quantity == 2.0 and line.total_price == 2825.0


def test_finalize_computes_total_currency_and_shared_lead_time():
    r = QuoteResult(currency=" usd ", lead_time="3 weeks", lines=[QuoteLine(quantity=3, unit_price=10.5)])
    finalize(r)
    assert r.currency == "USD"
    assert r.lines[0].total_price == 31.5
    assert r.lines[0].lead_time == "3 weeks"


def test_finalize_keeps_stated_total_and_does_not_invent_prices():
    r = QuoteResult(lines=[QuoteLine(quantity=3, unit_price=10, total_price=99), QuoteLine(quantity=2)])
    finalize(r)
    assert r.lines[0].total_price == 99
    assert r.lines[1].unit_price is None and r.lines[1].total_price is None


def test_validate_quote_flags_problems():
    r = QuoteResult(
        lines=[
            QuoteLine(part_number="A", quantity=2, unit_price=10, total_price=50, lead_time="2w"),
            QuoteLine(part_number="B", quantity=1),
            QuoteLine(part_number="C", quantity=1, unit_price=5, lead_time="1w", alternative_offered=True),
        ]
    )
    text = "\n".join(validate_quote(r))
    assert "Currency not found" in text and "validity not stated" in text
    assert "does not match" in text           # line 1 total mismatch
    assert "Line 2 (B): no unit price" in text and "Line 2 (B): no lead time" in text
    assert "alternative item offered" in text


def test_validate_clean_quote():
    r = QuoteResult(currency="USD", validity="30 days",
                    lines=[QuoteLine(part_number="A", quantity=2, unit_price=10, total_price=20, lead_time="2w")])
    assert validate_quote(r) == []
    assert "declined" in " ".join(validate_quote(QuoteResult(declined=True, currency="USD", validity="x"))).lower()
    assert "No offered items" in " ".join(validate_quote(QuoteResult()))


def test_find_reference():
    refs = ["AT-RFQ-00112-SCHN", "AT-RFQ-00113-PALL", "RFQ-20261115-SIEM-01"]
    assert find_reference("Re: Request for Quotation - AT-RFQ-00113-PALL", refs) == "AT-RFQ-00113-PALL"
    assert find_reference("ref at rfq 00112", refs) is None
    assert find_reference("blah", refs, quoted="at-rfq-00112-schn") == "AT-RFQ-00112-SCHN"
    assert find_reference("nothing here", refs) is None
    assert find_reference("AT-RFQ-00112-SCHN", []) is None


def test_parse_quote_with_fake_llm_dict():
    llm = FakeLLM({
        "supplier_name": "Example FZE", "currency": "usd", "validity": "30 days", "lead_time": "4 weeks",
        "lines": [{"part_number": "NSX100N", "quantity": 1, "unit_price": "1,412.50"}],
    })
    r = parse_quote("text", llm=llm)
    assert r.currency == "USD" and r.lines[0].unit_price == 1412.5
    assert r.lines[0].total_price == 1412.5 and r.lines[0].lead_time == "4 weeks"
    assert parse_quote("text", llm=FakeLLM(None)).lines == []


def test_parse_quote_stops_on_daily_cap():
    class Capped(FakeLLM):
        def invoke(self, messages):
            raise Exception("429 rate_limit_exceeded. Please try again in 30m0s")

    with pytest.raises(RateLimitExhausted):
        parse_quote("text", llm=Capped(None))


def test_save_and_load_quotes(tmp_path):
    path = tmp_path / "out" / "quotes.csv"
    r = QuoteResult(supplier_name="Ex FZE", currency="USD", validity="30 days", prices_include_tax=False,
                    lines=[QuoteLine(part_number="A", quantity=1, unit_price=5, total_price=5, lead_time="2w"),
                           QuoteLine(part_number="B", quantity=2, unit_price=3, total_price=6)])
    assert save_quote(r, rfq_ref="AT-RFQ-1-SCHN", source="x.pdf", path=path) == 2
    assert save_quote(r, path=path) == 2                      # appends, header written once
    rows = load_quotes(path)
    assert len(rows) == 4 and rows[0]["rfq_ref"] == "AT-RFQ-1-SCHN" and rows[0]["currency"] == "USD"
    assert rows[0]["prices_include_tax"] == "False"
    assert path.read_text().count("timestamp,rfq_ref") == 1


def test_known_references(tmp_path):
    log = tmp_path / "rfq_log.csv"
    log.write_text("timestamp,reference,brand,to_email,item_count\n2026-11-15,AT-RFQ-1-SCHN,Schneider,a@b.c,2\n")
    assert known_references(log) == ["AT-RFQ-1-SCHN"]
    assert known_references(tmp_path / "missing.csv") == []


def test_read_eml():
    eml = (b"From: a@example.com\nTo: b@example.com\nSubject: RE: RFQ AT-RFQ-1\n"
           b"Content-Type: text/plain; charset=utf-8\n\nUnit price USD 10\n")
    out = read_input("reply.eml", eml)
    assert "RE: RFQ AT-RFQ-1" in out and "Unit price USD 10" in out


def test_save_all_and_delete_quotes(tmp_path):
    path = tmp_path / "quotes.csv"
    initial_rows = [
        {"rfq_ref": "RFQ-1", "supplier": "Siemens", "part_number": "P1", "unit_price": "10", "timestamp": "2026-11-01"},
        {"rfq_ref": "RFQ-1", "supplier": "Siemens", "part_number": "P2", "unit_price": "20", "timestamp": "2026-11-01"},
        {"rfq_ref": "RFQ-2", "supplier": "Danfoss", "part_number": "D1", "unit_price": "50", "timestamp": "2026-11-02"},
    ]
    save_all_quotes(initial_rows, path)
    loaded = load_quotes(path)
    assert len(loaded) == 3

    # Delete index 1
    assert delete_quotes([1], path) == 1
    loaded2 = load_quotes(path)
    assert len(loaded2) == 2
    assert loaded2[0]["part_number"] == "P1"
    assert loaded2[1]["part_number"] == "D1"

    # Delete batch RFQ-1 Siemens
    assert delete_quotes_by_batch(rfq_ref="RFQ-1", supplier="Siemens", path=path) == 1
    loaded3 = load_quotes(path)
    assert len(loaded3) == 1
    assert loaded3[0]["supplier"] == "Danfoss"

