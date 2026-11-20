from datetime import date

import pytest

import config
from agent import build_graph
from extractor import RateLimitExhausted, call_with_backoff, extract_items, parse_wait_seconds, promote_model
from exporter import export_eml
from rfq_drafter import (
    UNASSIGNED,
    BannedTermError,
    assert_clean,
    build_drafts,
    group_by_brand,
    redact,
)
from schemas import ExtractionResult, LineItem, RFQMeta
from suppliers import Supplier, load_suppliers, normalize_brand
from validation import needs_retry, validate_items

BANNED = ["ACME Power", "Globex"]
SUPPLIERS = {"Siemens": Supplier("Siemens", "Mr Khan", "khan@example.com")}


def item(**kw):
    base = dict(description="Contactor", brand="Siemens", part_number="3RT2026", quantity=5)
    base.update(kw)
    return LineItem(**base)


# ---------- rate limit ----------
def test_parse_wait_seconds():
    assert parse_wait_seconds("Please try again in 7m12.5s.") == pytest.approx(433.5)
    assert parse_wait_seconds("try again in 850ms") == pytest.approx(1.85)
    assert parse_wait_seconds("something else") is None


def test_backoff_retries_then_succeeds():
    calls, slept = [], []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise Exception("Error 429 rate_limit_exceeded. Please try again in 1s")
        return "ok"

    assert call_with_backoff(flaky, sleep=slept.append) == "ok"
    assert slept == [pytest.approx(2.0)]


def test_backoff_stops_on_daily_cap():
    slept = []

    def capped():
        raise Exception("429 rate_limit_exceeded. Please try again in 20m0s")

    with pytest.raises(RateLimitExhausted):
        call_with_backoff(capped, sleep=slept.append)
    assert slept == []


def test_backoff_propagates_other_errors():
    with pytest.raises(ValueError):
        call_with_backoff(lambda: (_ for _ in ()).throw(ValueError("boom")))


# ---------- brands / suppliers ----------
def test_normalize_brand():
    assert normalize_brand(" siemens ") == "Siemens"
    assert normalize_brand("GF") == "GF+"
    assert normalize_brand("Georg Fischer") == "GF+"
    assert normalize_brand("ABB") == "ABB"
    assert normalize_brand("") is None
    assert normalize_brand(None) is None


def test_load_suppliers(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("brand,contact_name,email\nsiemens,Ali,a@example.com\n,x,y\n", encoding="utf-8")
    s = load_suppliers(f)
    assert list(s) == ["Siemens"] and s["Siemens"].email == "a@example.com"


# ---------- redaction ----------
def test_redact_and_assert_clean():
    text, found = redact("For acme power plant, Globex site", BANNED)
    assert "acme" not in text.lower() and "globex" not in text.lower()
    assert set(found) == set(BANNED)
    with pytest.raises(BannedTermError):
        assert_clean("ship to ACME Power", BANNED)
    assert_clean("ordinary text", BANNED)


def test_banned_whitespace_and_case_flexible():
    # Multiple spaces or newlines between words in a banned term must still match
    text, found = redact("Ship to ACME   Power station", BANNED)
    assert "ACME Power" in found
    assert "[REMOVED]" in text
    with pytest.raises(BannedTermError):
        assert_clean("for ACME\nPower site", BANNED)


def test_sanitize_csv_cell():
    from utils import sanitize_csv_cell
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("-100") == "'-100"
    assert sanitize_csv_cell("+cmd") == "'+cmd"
    assert sanitize_csv_cell("@formula") == "'@formula"
    assert sanitize_csv_cell("Normal Text") == "Normal Text"
    assert sanitize_csv_cell(123) == 123
    assert sanitize_csv_cell(None) is None


# ---------- grouping and drafting ----------
def test_group_by_brand():
    groups = group_by_brand([item(), item(brand="siemens"), item(brand=None), item(brand="GF")])
    assert list(groups) == ["Siemens", UNASSIGNED, "GF+"]
    assert len(groups["Siemens"]) == 2


def test_build_drafts_redacts_and_warns():
    items = [item(specs="for ACME Power turbine"), item(brand=None, description="Cable gland", part_number=None)]
    drafts, warnings = build_drafts(items, SUPPLIERS, BANNED, "Abuzar", "Abdullah Traders", today=date(2026, 11, 14))
    assert [d.brand for d in drafts] == ["Siemens", UNASSIGNED]
    siemens = drafts[0]
    assert siemens.to_email == "khan@example.com"
    assert siemens.reference == "RFQ-20261114-SIEM-01"
    assert "acme" not in siemens.body.lower()
    assert "Dear Mr Khan" in siemens.body
    assert any("restricted term removed" in w for w in warnings)
    assert any("no brand" in w for w in warnings)


def test_missing_supplier_warns():
    drafts, warnings = build_drafts([item(brand="Eaton")], SUPPLIERS, BANNED, "A", "B")
    assert drafts[0].to_email == ""
    assert any("No supplier on file for Eaton" in w for w in warnings)


def test_no_items():
    drafts, warnings = build_drafts([], SUPPLIERS, BANNED, "A", "B")
    assert drafts == [] and warnings


# ---------- validation ----------
def test_validate_and_retry_rules():
    good = item()
    no_part = item(part_number=None)
    no_brand = item(brand=None)
    assert validate_items([good]) == []
    assert "part number" in validate_items([no_part])[0]
    assert needs_retry([]) is True
    assert needs_retry([good, no_part]) is False        # part number alone never triggers a retry
    assert needs_retry([good, no_brand]) is True        # half the items lack a brand


# ---------- extractor with a fake LLM ----------
class FakeLLM:
    def __init__(self, output):
        self.output = output

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        return self.output


def test_extract_items_normalizes_brand_and_accepts_dict():
    llm = FakeLLM({"items": [{"description": "Valve", "brand": "gf", "quantity": 15}]})
    result = extract_items("text", llm=llm)
    assert result.items[0].brand == "GF+"
    assert extract_items("text", llm=FakeLLM(None)).items == []


# ---------- graph ----------
def make_extract(*results):
    calls = []

    def fn(text, feedback=None):
        calls.append(feedback)
        return results[min(len(calls) - 1, len(results) - 1)]

    fn.calls = calls
    return fn


def test_graph_happy_path():
    fn = make_extract(ExtractionResult(items=[item()]))
    app = build_graph(fn, SUPPLIERS, BANNED, "A", "B")
    state = app.invoke({"raw_text": "x", "attempts": 0})
    assert state["attempts"] == 1 and len(state["drafts"]) == 1


def test_graph_retries_once_with_feedback():
    fn = make_extract(ExtractionResult(items=[]), ExtractionResult(items=[item()]))
    app = build_graph(fn, SUPPLIERS, BANNED, "A", "B")
    state = app.invoke({"raw_text": "x", "attempts": 0})
    assert state["attempts"] == 2
    assert fn.calls[0] is None and fn.calls[1]
    assert len(state["drafts"]) == 1


def test_graph_stops_after_max_attempts():
    bad = ExtractionResult(items=[item(brand=None, quantity=None)])
    fn = make_extract(bad)
    app = build_graph(fn, SUPPLIERS, BANNED, "A", "B")
    state = app.invoke({"raw_text": "x", "attempts": 0})
    assert len(fn.calls) == config.MAX_EXTRACT_ATTEMPTS
    assert state["drafts"][0].brand == UNASSIGNED


# ---------- export ----------
def test_export_blocks_banned_edits_and_writes_eml(tmp_path):
    drafts, _ = build_drafts([item()], SUPPLIERS, BANNED, "A", "B", today=date(2026, 11, 14))
    d = drafts[0]
    with pytest.raises(BannedTermError):
        export_eml(d, d.to_email, d.subject, d.body + "\nfor ACME Power", BANNED, out_dir=tmp_path / "approved")
    path = export_eml(d, d.to_email, d.subject, d.body, BANNED, out_dir=tmp_path / "approved")
    assert path.exists() and b"X-Unsent" in path.read_bytes()
    assert (tmp_path / "rfq_log.csv").exists()


# ---------- request-level meta (Sprint 1.1) ----------
META = RFQMeta(
    client_reference="AT-RFQ-00112",
    delivery_terms="CPT Lahore Airport / FCA",
    closing_date="19-Oct-2026",
    require_country_of_origin=True,
    sales_tax_separate=True,
)


def test_meta_in_email_and_reference():
    drafts, _ = build_drafts([item()], SUPPLIERS, BANNED, "A", "B", today=date(2026, 11, 14), meta=META)
    d = drafts[0]
    assert d.reference == "AT-RFQ-00112-SIEM"
    assert "AT-RFQ-00112-SIEM" in d.subject
    for text in ("Delivery terms: CPT Lahore Airport / FCA", "Please respond by: 19-Oct-2026",
                 "- Country of origin", "- Sales tax amount shown separately"):
        assert text in d.body


def test_no_meta_keeps_generated_reference_and_no_extra_lines():
    d = build_drafts([item()], SUPPLIERS, BANNED, "A", "B", today=date(2026, 11, 14))[0][0]
    assert d.reference == "RFQ-20261114-SIEM-01"
    assert "Delivery terms" not in d.body and "Country of origin" not in d.body


def test_meta_is_redacted():
    meta = RFQMeta(delivery_terms="Ship to ACME Power site", client_reference="ACME Power/001")
    drafts, warnings = build_drafts([item()], SUPPLIERS, BANNED, "A", "B", meta=meta)
    d = drafts[0]
    assert "acme" not in (d.body + d.subject + d.reference).lower()
    assert any("delivery terms" in w for w in warnings)


def test_schneider_alias():
    assert normalize_brand("Schneider") == "Schneider Electric"
    assert normalize_brand("schneider electric") == "Schneider Electric"


def test_graph_passes_meta_to_drafts():
    fn = make_extract(ExtractionResult(items=[item()], meta=META))
    state = build_graph(fn, SUPPLIERS, BANNED, "A", "B").invoke({"raw_text": "x", "attempts": 0})
    assert state["meta"].client_reference == "AT-RFQ-00112"
    assert "Delivery terms: CPT Lahore Airport / FCA" in state["drafts"][0].body


def test_extract_items_reads_meta_from_dict():
    llm = FakeLLM({"items": [{"description": "Breaker", "brand": "Schneider", "quantity": 1}],
                   "meta": {"client_reference": "X-1", "require_country_of_origin": True}})
    r = extract_items("text", llm=llm)
    assert r.items[0].brand == "Schneider Electric"
    assert r.meta.client_reference == "X-1" and r.meta.require_country_of_origin


def test_promote_model_from_specs():
    a = LineItem(description="Circuit Breaker", part_number=None, specs="Model: Compact NSX100N, Module: MT100/160, Ui:800V")
    promote_model(a)
    assert a.part_number == "Compact NSX100N" and a.specs == "Module: MT100/160, Ui:800V"

    b = LineItem(description="Circuit Breaker", part_number=None, specs="Model: Compact NSX 100N")
    promote_model(b)
    assert b.part_number == "Compact NSX 100N" and b.specs is None

    c = LineItem(description="x", part_number="ABC-1", specs="Model: Other, 50Hz")
    promote_model(c)
    assert c.part_number == "ABC-1" and c.specs == "Model: Other, 50Hz"   # existing part number wins

    d = LineItem(description="x", part_number=None, specs="24V DC coil")
    promote_model(d)
    assert d.part_number is None and d.specs == "24V DC coil"


def test_extract_items_promotes_model():
    llm = FakeLLM({"items": [{"description": "Circuit Breaker", "brand": "Schneider", "quantity": 1,
                              "specs": "Model: Compact NSX100N, Ui:800V"}]})
    it = extract_items("text", llm=llm).items[0]
    assert it.part_number == "Compact NSX100N" and it.specs == "Ui:800V"


def test_pall_alias_and_grouping():
    assert normalize_brand("Pall") == "PALL Corporation"
    assert normalize_brand("PALL Corporation") == "PALL Corporation"
    groups = group_by_brand([item(brand="Pall"), item(brand="PALL Corporation")])
    assert list(groups) == ["PALL Corporation"] and len(groups["PALL Corporation"]) == 2


def test_prompt_keeps_pressure_class_qualifiers():
    from extractor import SYSTEM_PROMPT

    assert "CL125" in SYSTEM_PROMPT and "pressure class" in SYSTEM_PROMPT


# ---------- multi-supplier per brand ----------
def test_multi_supplier_load(tmp_path):
    f = tmp_path / "multi_suppliers.csv"
    f.write_text(
        "brand,contact_name,email,company\n"
        "Siemens,Mr Khan,khan@siemens-dist.com,Siemens Dist\n"
        "Siemens,Mr Tariq,tariq@siemens-partner.com,Partner Co\n",
        encoding="utf-8",
    )
    s = load_suppliers(f)
    assert "Siemens" in s
    assert len(s["Siemens"]) == 2
    assert s["Siemens"][0].contact_name == "Mr Khan"
    assert s["Siemens"][1].contact_name == "Mr Tariq"
    # backward-compatible properties
    assert s["Siemens"].email == "khan@siemens-dist.com"
    assert s["Siemens"].contact_name == "Mr Khan"


def test_multi_supplier_drafts_same_rfq_number(tmp_path):
    f = tmp_path / "multi_suppliers.csv"
    f.write_text(
        "brand,contact_name,email\n"
        "Siemens,Mr Khan,khan@example.com\n"
        "Siemens,Mr Tariq,tariq@example.com\n",
        encoding="utf-8",
    )
    suppliers = load_suppliers(f)
    items = [item(brand="Siemens", description="Contactor", part_number="3RT2026")]
    drafts, warnings = build_drafts(items, suppliers, BANNED, "Abuzar", "Abdullah Traders", today=date(2026, 11, 14))

    assert len(drafts) == 2
    d1, d2 = drafts[0], drafts[1]

    # same RFQ reference
    assert d1.reference == d2.reference == "RFQ-20261114-SIEM-01"
    assert d1.brand == d2.brand == "Siemens"

    # separate contacts and emails
    assert d1.to_email == "khan@example.com"
    assert d1.contact_name == "Mr Khan"
    assert "Dear Mr Khan," in d1.body

    assert d2.to_email == "tariq@example.com"
    assert d2.contact_name == "Mr Tariq"
    assert "Dear Mr Tariq," in d2.body


def test_multi_supplier_export_no_overwrite(tmp_path):
    f = tmp_path / "multi_suppliers.csv"
    f.write_text(
        "brand,contact_name,email\n"
        "Siemens,Mr Khan,khan@example.com\n"
        "Siemens,Mr Tariq,tariq@example.com\n",
        encoding="utf-8",
    )
    suppliers = load_suppliers(f)
    drafts, _ = build_drafts([item(brand="Siemens")], suppliers, BANNED, "A", "B", today=date(2026, 11, 14))
    assert len(drafts) == 2

    out_dir = tmp_path / "approved"
    p1 = export_eml(drafts[0], drafts[0].to_email, drafts[0].subject, drafts[0].body, BANNED, out_dir=out_dir)
    p2 = export_eml(drafts[1], drafts[1].to_email, drafts[1].subject, drafts[1].body, BANNED, out_dir=out_dir)

    assert p1.exists()
    assert p2.exists()
    assert p1 != p2
    assert p1.name == "RFQ-20261114-SIEM-01.eml"
    assert p2.name == "RFQ-20261114-SIEM-01_tariq.eml"

    # check rfq_log
    log_file = tmp_path / "rfq_log.csv"
    assert log_file.exists()
    log_content = log_file.read_text(encoding="utf-8")
    assert "khan@example.com" in log_content
    assert "tariq@example.com" in log_content


def test_add_supplier(tmp_path):
    from suppliers import add_supplier

    f = tmp_path / "suppliers.csv"
    ok, msg = add_supplier("ABB", "David", "david@abb.example", path=f)
    assert ok is True and "ABB" in msg
    assert f.exists()

    s = load_suppliers(f)
    assert "ABB" in s
    assert s["ABB"].email == "david@abb.example"

    # Reject duplicate email for same brand
    ok_dup, msg_dup = add_supplier("ABB", "David 2", "david@abb.example", path=f)
    assert ok_dup is False
    assert "already exists" in msg_dup

    # Reject invalid email or empty brand
    ok_bad, _ = add_supplier("", "X", "x@example.com", path=f)
    assert ok_bad is False
    ok_bad_email, _ = add_supplier("Danfoss", "X", "not-an-email", path=f)
    assert ok_bad_email is False

    # Normalizes brand aliases
    ok_alias, _ = add_supplier("schneider", "Team", "team@se.example", path=f)
    assert ok_alias is True
    s2 = load_suppliers(f)
    assert "Schneider Electric" in s2


# ---------- RFQ-00118 regression tests (Step 2) ----------
def test_rfq_00118_regression():
    raw_items = [
        {"brand": "MINIMAX", "description": "Flanged OS&Y Gate Valve", "part_number": "ZG445027 / ZG621030", "quantity": 1, "unit": "pcs", "specs": "Size NPS 2, 300 PSI"},
        {"brand": "Minimax", "description": "Flanged OS&Y Gate Valve", "part_number": "CZH309606", "quantity": 2, "unit": "pcs", "specs": "Size NPS 3, 300 PSI"},
        {"brand": "minimax", "description": "Flanged OS&Y Gate Valve", "part_number": "ZGX14329", "quantity": 1, "unit": "pcs", "specs": "Size NPS 4, 300 PSI"},
        {"brand": "MINIMAX", "description": "Flanged OS&Y Gate Valve", "part_number": "CZH310138", "quantity": 2, "unit": "pcs", "specs": "Model XZ41X, Size NPS 350, 300 PSI, Body ASTM A536"},
        {"brand": "Minimax", "description": "Flanged OS&Y Gate Valve", "part_number": "ZG445028", "quantity": 1, "unit": "pcs", "specs": "Size NPS 6, 300 PSI"},
        {"brand": "MINIMAX", "description": "Flanged OS&Y Gate Valve", "part_number": "ZG621031", "quantity": 2, "unit": "pcs", "specs": "Size NPS 8, 300 PSI"},
        {"brand": "MINIMAX", "description": "Flanged OS&Y Gate Valve", "part_number": "NSX 100N", "quantity": 1, "unit": "pcs", "specs": "Size NPS 10, 300 PSI"},
    ]
    llm = FakeLLM({"items": raw_items})
    res = extract_items("text", llm=llm)

    # 1. 7 items keep their quantities
    assert len(res.items) == 7
    assert [it.quantity for it in res.items] == [1, 2, 1, 2, 1, 2, 1]

    # 2. part number ZG445027 / ZG621030 stays in one piece, and CZH309606 stays in one piece
    assert res.items[0].part_number == "ZG445027 / ZG621030"
    assert res.items[1].part_number == "CZH309606"

    # 3. "NPS 350" is kept
    assert "NPS 350" in res.items[3].specs

    # 4. Spacing in part numbers is preserved exactly ("NSX 100N")
    assert res.items[6].part_number == "NSX 100N"

    # 5. Brand stays Minimax on every row, so no "Unassigned" draft appears
    for it in res.items:
        assert it.brand == "Minimax"

    suppliers = {"Minimax": Supplier("Minimax", "Mr Ali", "ali@example.com")}
    drafts, warnings = build_drafts(res.items, suppliers, BANNED, "Abuzar", "Abdullah Traders")
    assert len(drafts) == 1
    assert drafts[0].brand == "Minimax"
    assert drafts[0].item_count == 7
    assert not any("no brand" in w for w in warnings)
    assert not any(d.brand == UNASSIGNED for d in drafts)
