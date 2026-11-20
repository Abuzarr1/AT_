import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from evaluation.metrics import aggregate, score_case
from evaluation.runner import find_items, render_markdown, resolve_extractor, run_cases

GOLD = [
    {"brand": "Schneider", "part_number": "NSX 100N", "quantity": 2},
    {"brand": "Pall", "part_number": "XLDM4.5-404-HFJ", "quantity": "10"},
]
SOURCE = "Schneider NSX 100N qty 2. Pall XLDM4.5-404-HFJ qty 10."


def test_perfect_score():
    s = score_case(GOLD, GOLD, SOURCE)
    assert s["matched"] == 2 and s["errors"] == []
    assert aggregate([s])["item_f1"] == 1.0


def test_spacing_counts_for_exact_but_not_loose():
    pred = [dict(GOLD[0], part_number="NSX100N"), GOLD[1]]
    s = score_case(GOLD, pred, SOURCE)
    assert s["matched"] == 2
    assert s["pn_strict_ok"] == 1 and s["pn_loose_ok"] == 2


def test_missed_and_extra_items():
    pred = [GOLD[0], {"brand": "ABB", "part_number": "ZZ999", "quantity": 1}]
    s = score_case(GOLD, pred, SOURCE)
    assert s["matched"] == 1
    assert any(e.startswith("MISSED") for e in s["errors"])
    assert any(e.startswith("EXTRA") for e in s["errors"])


def test_invented_part_number_detected():
    pred = [GOLD[0], dict(GOLD[1], part_number="PALL-FAKE-1")]
    s = score_case(GOLD, pred, SOURCE)
    assert s["pn_invented"] >= 1


def test_wrong_brand_and_quantity():
    pred = [dict(GOLD[0], brand="ABB", quantity=3), GOLD[1]]
    s = score_case(GOLD, pred, SOURCE)
    assert s["brand_ok"] == 1 and s["qty_ok"] == 1


def test_aggregate_handles_zero_denominators():
    s = score_case([], [], "")
    agg = aggregate([s])
    assert agg["item_recall"] is None and agg["item_f1"] is None


def test_find_items_variants():
    class Req:
        items = [1, 2]
    assert find_items({"items": [1]}) == [1]
    assert find_items(Req()) == [1, 2]
    assert find_items({"request": Req()}) == [1, 2]
    assert find_items([3]) == [3]


def _cases():
    return [{"id": "c1", "_text": SOURCE, "expected_items": GOLD,
             "manual_minutes": 30, "review_minutes": 5},
            {"id": "c2", "_text": SOURCE, "expected_items": GOLD}]


def test_run_cases_scores_and_renders():
    report = run_cases(_cases(), lambda text: {"items": GOLD}, sleep=0)
    assert report["cases_scored"] == 2 and report["stopped"] is None
    assert report["time_saved_cases"] == 1
    assert 24 < report["time_saved_minutes_per_rfq"] < 26
    assert "Item recall" in render_markdown(report)


def test_rate_limit_stops_cleanly_without_retry():
    calls = []

    def extract(text):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("Error code: 429 rate limit reached")
        return {"items": GOLD}

    report = run_cases(_cases() + _cases(), extract, sleep=0)
    assert len(calls) == 2
    assert report["stopped"] and report["cases_scored"] == 1


def test_other_errors_are_recorded_and_run_continues():
    def extract(text):
        raise ValueError("bad output")

    report = run_cases(_cases(), extract, sleep=0)
    assert report["cases_scored"] == 0 and len(report["results"]) == 2


def test_resolve_extractor_requires_spec():
    with pytest.raises(SystemExit):
        resolve_extractor("")
