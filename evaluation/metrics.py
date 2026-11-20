"""Pure scoring functions. No network, no LLM, no project imports."""
from __future__ import annotations

import difflib
import re
from typing import Any

DESC_KEYS = ("description", "name", "item", "item_description")


def alnum(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def parse_qty(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text.split()[0])
    except ValueError:
        return None


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, "")
    return getattr(obj, name, "")


def to_item(obj: Any) -> dict:
    desc = ""
    for key in DESC_KEYS:
        value = _get(obj, key)
        if value:
            desc = str(value)
            break
    return {
        "brand": str(_get(obj, "brand") or "").strip(),
        "part_number": str(_get(obj, "part_number") or "").strip(),
        "quantity": _get(obj, "quantity"),
        "description": desc,
    }


def _match_key(item: dict) -> str:
    return alnum(item["part_number"] + " " + item["description"])


def match_items(gold: list[dict], pred: list[dict]) -> list[tuple[int, int]]:
    """Pair gold items with predicted items: exact part number first, then fuzzy."""
    pairs: list[tuple[int, int]] = []
    used_g: set[int] = set()
    used_p: set[int] = set()
    for gi, g in enumerate(gold):
        gpn = alnum(g["part_number"])
        if not gpn:
            continue
        for pi, p in enumerate(pred):
            if pi not in used_p and alnum(p["part_number"]) == gpn:
                pairs.append((gi, pi))
                used_g.add(gi)
                used_p.add(pi)
                break
    for gi, g in enumerate(gold):
        if gi in used_g or not _match_key(g):
            continue
        best, best_ratio = None, 0.75
        for pi, p in enumerate(pred):
            if pi in used_p or not _match_key(p):
                continue
            ratio = difflib.SequenceMatcher(None, _match_key(g), _match_key(p)).ratio()
            if ratio >= best_ratio:
                best, best_ratio = pi, ratio
        if best is not None:
            pairs.append((gi, best))
            used_g.add(gi)
            used_p.add(best)
    return sorted(pairs)


def score_case(gold_raw: list, pred_raw: list, source_text: str = "") -> dict:
    gold = [to_item(x) for x in gold_raw]
    pred = [to_item(x) for x in pred_raw]
    pairs = match_items(gold, pred)
    errors: list[str] = []
    brand_ok = pn_strict = pn_loose = qty_ok = 0

    for gi, pi in pairs:
        g, p = gold[gi], pred[pi]
        label = g["part_number"] or g["description"] or f"item {gi + 1}"
        if g["brand"].lower() == p["brand"].lower():
            brand_ok += 1
        else:
            errors.append(f"{label}: brand expected '{g['brand']}', got '{p['brand']}'")
        if g["part_number"] == p["part_number"]:
            pn_strict += 1
        else:
            errors.append(f"{label}: part number expected '{g['part_number']}', got '{p['part_number']}'")
        if alnum(g["part_number"]) == alnum(p["part_number"]):
            pn_loose += 1
        if parse_qty(g["quantity"]) == parse_qty(p["quantity"]):
            qty_ok += 1
        else:
            errors.append(f"{label}: quantity expected '{g['quantity']}', got '{p['quantity']}'")

    matched_g = {gi for gi, _ in pairs}
    matched_p = {pi for _, pi in pairs}
    for gi, g in enumerate(gold):
        if gi not in matched_g:
            errors.append(f"MISSED: {g['part_number'] or g['description'] or f'item {gi + 1}'}")
    for pi, p in enumerate(pred):
        if pi not in matched_p:
            errors.append(f"EXTRA: {p['part_number'] or p['description'] or f'item {pi + 1}'}")

    src = alnum(source_text)
    pn_pred = invented = 0
    for p in pred:
        if p["part_number"]:
            pn_pred += 1
            if source_text and alnum(p["part_number"]) not in src:
                invented += 1
                errors.append(f"INVENTED part number (not in source): {p['part_number']}")

    return {
        "gold_n": len(gold), "pred_n": len(pred), "matched": len(pairs),
        "brand_ok": brand_ok, "pn_strict_ok": pn_strict, "pn_loose_ok": pn_loose,
        "qty_ok": qty_ok, "pn_pred": pn_pred, "pn_invented": invented,
        "errors": errors,
    }


def _rate(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def aggregate(scores: list[dict]) -> dict:
    total = {k: sum(s[k] for s in scores) for k in (
        "gold_n", "pred_n", "matched", "brand_ok", "pn_strict_ok",
        "pn_loose_ok", "qty_ok", "pn_pred", "pn_invented")}
    recall = _rate(total["matched"], total["gold_n"])
    precision = _rate(total["matched"], total["pred_n"])
    f1 = None
    if recall is not None and precision is not None and (recall + precision) > 0:
        f1 = 2 * recall * precision / (recall + precision)
    return {
        "cases": len(scores), **total,
        "item_recall": recall, "item_precision": precision, "item_f1": f1,
        "brand_accuracy": _rate(total["brand_ok"], total["matched"]),
        "part_number_exact": _rate(total["pn_strict_ok"], total["matched"]),
        "part_number_loose": _rate(total["pn_loose_ok"], total["matched"]),
        "quantity_accuracy": _rate(total["qty_ok"], total["matched"]),
        "invented_part_number_rate": _rate(total["pn_invented"], total["pn_pred"]),
    }
