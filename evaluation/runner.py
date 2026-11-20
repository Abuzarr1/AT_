"""Benchmark runner.

Usage (from the project folder, venv active):
    python -m evaluation.runner --extractor module:function

The function takes the request text and returns an object (or dict) that holds
the extracted items. Real LLM runs are manual: they use the Groq free-tier cap.
"""
from __future__ import annotations

import argparse
import importlib
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from evaluation.metrics import aggregate, score_case

RATE_LIMIT_MARKERS = ("429", "rate limit", "rate_limit", "tokens per day")


def find_items(result: Any) -> list:
    """Pull the items list out of a model, dict, list or LangGraph state."""
    if isinstance(result, (list, tuple)):
        return list(result)
    if isinstance(result, dict):
        if isinstance(result.get("items"), (list, tuple)):
            return list(result["items"])
        for value in result.values():
            found = getattr(value, "items", None)
            if isinstance(found, (list, tuple)):
                return list(found)
            if isinstance(value, dict) and isinstance(value.get("items"), (list, tuple)):
                return list(value["items"])
        return []
    found = getattr(result, "items", None)
    return list(found) if isinstance(found, (list, tuple)) else []


def resolve_extractor(spec: str) -> Callable[[str], Any]:
    if not spec or ":" not in spec:
        raise SystemExit(
            "Pass --extractor module:function (the function takes request text). "
            "Find candidates with: grep -n '^def ' extractor.py agent.py"
        )
    module_name, func_name = spec.split(":", 1)
    sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module(module_name)
    return getattr(module, func_name)


def _read_input(case: dict, base: Path) -> str:
    if "text" in case:
        return case["text"]
    path = base / case["input_file"]
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8")


def load_cases(cases_dir: Path) -> list[dict]:
    cases = []
    for path in sorted(cases_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        case = json.loads(path.read_text(encoding="utf-8"))
        case["id"] = case.get("id", path.stem)
        case["_text"] = _read_input(case, cases_dir)
        cases.append(case)
    return cases


def run_cases(cases: list[dict], extract: Callable[[str], Any], sleep: float = 2.0) -> dict:
    results, stopped = [], None
    for index, case in enumerate(cases):
        start = time.perf_counter()
        try:
            items = find_items(extract(case["_text"]))
        except Exception as exc:  # noqa: BLE001 - report and decide below
            message = str(exc)
            if any(m in message.lower() for m in RATE_LIMIT_MARKERS):
                stopped = f"Stopped at case '{case['id']}': rate limit. Wait, then re-run."
                break
            results.append({"id": case["id"], "error": message[:300], "seconds": time.perf_counter() - start})
            continue
        seconds = time.perf_counter() - start
        score = score_case(case["expected_items"], items, case["_text"])
        entry = {"id": case["id"], "seconds": seconds, "score": score}
        for key in ("manual_minutes", "review_minutes"):
            if key in case:
                entry[key] = case[key]
        results.append(entry)
        if sleep and index < len(cases) - 1:
            time.sleep(sleep)

    scored = [r for r in results if "score" in r]
    seconds = [r["seconds"] for r in scored]
    summary = aggregate([r["score"] for r in scored]) if scored else {}
    latency = {}
    if seconds:
        ordered = sorted(seconds)
        latency = {
            "median_seconds": statistics.median(seconds),
            "p95_seconds": ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))],
            "total_seconds": sum(seconds),
        }
    timed = [
        r for r in scored
        if r.get("manual_minutes") is not None and r.get("review_minutes") is not None
    ]
    saved = None
    if timed:
        saved = statistics.mean(
            r["manual_minutes"] - (r["review_minutes"] + r["seconds"] / 60) for r in timed
        )
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "cases_run": len(results), "cases_scored": len(scored),
        "cases_requested": len(cases), "stopped": stopped,
        "summary": summary, "latency": latency,
        "time_saved_minutes_per_rfq": saved, "time_saved_cases": len(timed),
        "results": results,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_markdown(report: dict) -> str:
    s, lat = report["summary"], report["latency"]
    lines = [f"# Benchmark report ({report['generated']})", ""]
    if report["stopped"]:
        lines += [f"**{report['stopped']}** Results below are partial.", ""]
    lines += [f"Cases scored: {report['cases_scored']} of {report['cases_requested']}", ""]
    if s:
        lines += [
            "| Metric | Value |", "|---|---|",
            f"| Item recall | {_pct(s['item_recall'])} |",
            f"| Item precision | {_pct(s['item_precision'])} |",
            f"| Item F1 | {_pct(s['item_f1'])} |",
            f"| Brand accuracy (matched items) | {_pct(s['brand_accuracy'])} |",
            f"| Part number exact (spacing counts) | {_pct(s['part_number_exact'])} |",
            f"| Part number loose (spacing ignored) | {_pct(s['part_number_loose'])} |",
            f"| Quantity accuracy | {_pct(s['quantity_accuracy'])} |",
            f"| Invented part numbers | {_pct(s['invented_part_number_rate'])} |",
            "",
        ]
    if lat:
        lines += [f"Latency: median {lat['median_seconds']:.1f}s, p95 {lat['p95_seconds']:.1f}s per request.", ""]
    if report["time_saved_minutes_per_rfq"] is not None:
        lines += [f"Time saved: {report['time_saved_minutes_per_rfq']:.1f} min per RFQ "
                  f"(measured on {report['time_saved_cases']} cases with manual and review times).", ""]
    else:
        lines += ["Time saved: not measured (add manual_minutes and review_minutes to cases).", ""]
    lines += ["## Per-case errors", ""]
    for r in report["results"]:
        if "error" in r:
            lines.append(f"- **{r['id']}**: run failed: {r['error']}")
        elif r["score"]["errors"]:
            lines.append(f"- **{r['id']}**")
            lines += [f"  - {e}" for e in r["score"]["errors"]]
        else:
            lines.append(f"- **{r['id']}**: no errors")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the extraction benchmark.")
    parser.add_argument("--extractor", default="", help="module:function taking request text")
    parser.add_argument("--cases", default="evaluation/cases")
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--sleep", type=float, default=2.0, help="seconds between cases")
    parser.add_argument("--limit", type=int, default=0, help="run only the first N cases")
    args = parser.parse_args(argv)

    extract = resolve_extractor(args.extractor)
    cases = load_cases(Path(args.cases))
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("No cases found. See evaluation/cases/README.md.")

    report = run_cases(cases, extract, sleep=args.sleep)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (out / "eval_report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
