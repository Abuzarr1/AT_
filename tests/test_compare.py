from datetime import datetime

from compare import (
    base_reference,
    build_comparison,
    item_key,
    latest_per_supplier,
    pending_rfqs,
    rfq_groups,
    supplier_scorecard,
)


def row(supplier, ref, part, unit, qty="1", cur="USD", lead="4 weeks", ts="2026-11-01T10:00:00", **kw):
    base = {"timestamp": ts, "rfq_ref": ref, "supplier": supplier, "part_number": part, "description": "",
            "quantity": qty, "unit_price": unit, "total_price": "", "currency": cur, "lead_time": lead,
            "validity": "30 days", "payment_terms": "", "delivery_terms": "CPT", "prices_include_tax": "False",
            "alternative_offered": "False"}
    base.update(kw)
    return base


def test_base_reference_and_key():
    assert base_reference("AT-RFQ-00112-SCHN") == "AT-RFQ-00112"
    assert base_reference("RFQ-20261101-PALL-01") == "RFQ-20261101-PALL-01"
    assert item_key("Compact NSX 100N", "") == item_key("COMPACT NSX100N", "x")


def test_best_price_and_totals():
    rows = [row("A", "AT-RFQ-00112-SCHN", "NSX 100N", "900", qty="2"),
            row("B", "AT-RFQ-00112-EATN", "NSX100N", "850", qty="2")]
    c = build_comparison(rows, "AT-RFQ-00112")
    assert len(c["items"]) == 1 and c["items"][0]["best"] == "B"
    totals = {s["supplier"]: s["total"] for s in c["suppliers"]}
    assert totals == {"A": 1800.0, "B": 1700.0}


def test_mixed_currency_is_not_ranked():
    rows = [row("A", "AT-RFQ-1-AAAA", "X1", "10", cur="USD"), row("B", "AT-RFQ-1-BBBB", "X1", "9", cur="EUR")]
    c = build_comparison(rows, "AT-RFQ-1")
    assert c["items"][0]["best"] is None and c["items"][0]["mixed_currency"]
    assert any("currencies" in f for f in c["flags"])


def test_missing_item_alternative_and_tax_flags():
    rows = [row("A", "AT-RFQ-1-AAAA", "X1", "10"), row("A", "AT-RFQ-1-AAAA", "X2", "5", alternative_offered="True"),
            row("B", "AT-RFQ-1-BBBB", "X1", "9", prices_include_tax="True")]
    flags = " ".join(build_comparison(rows, "AT-RFQ-1")["flags"])
    assert "not quoted by every supplier" in flags and "alternative" in flags and "include sales tax" in flags


def test_latest_quote_wins():
    rows = [row("A", "AT-RFQ-1-AAAA", "X1", "10", ts="2026-11-01T10:00:00"),
            row("A", "AT-RFQ-1-AAAA", "X1", "8", ts="2026-11-02T10:00:00")]
    kept = latest_per_supplier(rows)
    assert [r["unit_price"] for r in kept] == ["8"]
    assert rfq_groups(rows) == ["AT-RFQ-1"]


def test_pending_rfqs():
    log = [{"timestamp": "2026-11-10T09:00:00", "reference": "AT-RFQ-1-AAAA", "brand": "A", "to_email": "a@x.com"},
           {"timestamp": "2026-11-10T09:00:00", "reference": "AT-RFQ-1-BBBB", "brand": "B", "to_email": "b@x.com"},
           {"timestamp": "2026-11-17T09:00:00", "reference": "AT-RFQ-2-CCCC", "brand": "C", "to_email": ""}]
    quotes = [{"rfq_ref": "AT-RFQ-1-AAAA"}]
    out = pending_rfqs(log, quotes, days=3, now=datetime(2026, 11, 18, 12, 0))
    assert [o["reference"] for o in out] == ["AT-RFQ-1-BBBB"] and out[0]["days_waiting"] == 8


# ---------- supplier history / scorecard (Sprint 3.1) ----------
def test_supplier_scorecard_empty():
    assert supplier_scorecard([]) == []


def test_supplier_scorecard_win_rate():
    # Supplier A and B compete on two items
    rows = [
        row("Supplier A", "AT-RFQ-1-SCHN", "NSX100N", "100", qty="2"),
        row("Supplier A", "AT-RFQ-1-SCHN", "C10N3TM", "250", qty="1"),
        row("Supplier B", "AT-RFQ-1-SCHN", "NSX100N", "120", qty="2"),
        row("Supplier B", "AT-RFQ-1-SCHN", "C10N3TM", "220", qty="1"),
    ]
    sc = supplier_scorecard(rows)
    assert len(sc) == 2

    by_name = {s["Supplier"]: s for s in sc}
    # Both won 1 out of 2 items
    assert by_name["Supplier A"]["Win Rate"] == "1/2 (50%)"
    assert by_name["Supplier B"]["Win Rate"] == "1/2 (50%)"
    assert by_name["Supplier A"]["RFQs Quoted"] == 1
    assert by_name["Supplier A"]["Items Quoted"] == 2


def test_supplier_scorecard_turnaround_and_lead_time():
    log = [{"timestamp": "2026-11-10T10:00:00", "reference": "AT-RFQ-1-SIEM", "brand": "Siemens", "to_email": "a@x.com"}]
    quotes = [
        row("Siemens Direct", "AT-RFQ-1-SIEM", "3RT2026", "50", lead="2 weeks", ts="2026-11-12T10:00:00"),
        row("Siemens Direct", "AT-RFQ-1-SIEM", "3RT2027", "70", lead="2 weeks", ts="2026-11-12T10:00:00", alternative_offered="True"),
    ]
    sc = supplier_scorecard(quotes, log)
    assert len(sc) == 1
    entry = sc[0]
    assert entry["Supplier"] == "Siemens Direct"
    assert entry["Avg Turnaround"] == "2.0 days"
    assert entry["Typical Lead Time"] == "2 weeks"
    assert entry["Alternative Rate"] == "50%"
