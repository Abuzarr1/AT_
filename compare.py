"""Quote comparison (Sprint 3): line-by-line price comparison across suppliers, plus pending-reply reminders.

Pure functions over the rows saved in quotes.csv / rfq_log.csv, so everything is testable offline.
No currency conversion is done: prices are only ranked when every offer for an item uses the same currency.
"""
from __future__ import annotations

import re
from datetime import datetime
from collections import Counter
from typing import Optional

_CODE_SUFFIX = re.compile(r"-[A-Z]{4}$")


def base_reference(ref: str) -> str:
    """AT-RFQ-00112-SCHN -> AT-RFQ-00112 (the client RFQ shared by all of its supplier emails)."""
    return _CODE_SUFFIX.sub("", (ref or "").strip())


def num(value) -> Optional[float]:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def item_key(part_number: str, description: str) -> str:
    """Match the same item across suppliers: part number without spaces/punctuation, else description."""
    key = re.sub(r"[^A-Z0-9]", "", (part_number or "").upper())
    return key or re.sub(r"[^A-Z0-9]", "", (description or "").upper())


def latest_per_supplier(rows: list[dict]) -> list[dict]:
    """If a supplier was saved more than once for the same RFQ, keep only its latest quote."""
    latest: dict[tuple, str] = {}
    for r in rows:
        k = (r.get("rfq_ref", ""), r.get("supplier", ""))
        latest[k] = max(latest.get(k, ""), r.get("timestamp", ""))
    return [r for r in rows if r.get("timestamp", "") == latest[(r.get("rfq_ref", ""), r.get("supplier", ""))]]


def rfq_groups(rows: list[dict]) -> list[str]:
    return sorted({base_reference(r.get("rfq_ref", "")) for r in rows if r.get("rfq_ref")})


def line_total(row: dict) -> Optional[float]:
    total = num(row.get("total_price"))
    if total is not None:
        return total
    qty, unit = num(row.get("quantity")), num(row.get("unit_price"))
    return round(qty * unit, 2) if qty is not None and unit is not None else None


def build_comparison(rows: list[dict], group: str) -> dict:
    """Return {'suppliers': [...], 'items': [...], 'flags': [...]} for one client RFQ."""
    rows = latest_per_supplier([r for r in rows if base_reference(r.get("rfq_ref", "")) == group])
    suppliers: dict[str, dict] = {}
    items: dict[str, dict] = {}
    for r in rows:
        name = r.get("supplier") or "Unknown supplier"
        s = suppliers.setdefault(name, {
            "supplier": name, "rfq_ref": r.get("rfq_ref", ""), "currency": r.get("currency", ""),
            "validity": r.get("validity", ""), "payment_terms": r.get("payment_terms", ""),
            "delivery_terms": r.get("delivery_terms", ""), "prices_include_tax": r.get("prices_include_tax", ""),
            "total": 0.0, "priced_lines": 0, "alternatives": 0, "lead_times": set(),
        })
        total = line_total(r)
        if total is not None:
            s["total"] += total
            s["priced_lines"] += 1
        if str(r.get("alternative_offered", "")).lower() == "true":
            s["alternatives"] += 1
        if r.get("lead_time"):
            s["lead_times"].add(r["lead_time"])
        key = item_key(r.get("part_number", ""), r.get("description", ""))
        it = items.setdefault(key, {"key": key, "label": r.get("part_number") or r.get("description") or key,
                                    "quantity": num(r.get("quantity")), "offers": {}})
        it["offers"][name] = r

    for it in items.values():
        priced = {n: num(o.get("unit_price")) for n, o in it["offers"].items() if num(o.get("unit_price")) is not None}
        currencies = {it["offers"][n].get("currency") or "" for n in priced}
        it["mixed_currency"] = len(currencies) > 1
        it["best"] = None
        if len(priced) > 1 and not it["mixed_currency"]:
            it["best"] = min(priced, key=priced.get)

    flags = []
    for s in suppliers.values():
        s["lead_time"] = " / ".join(sorted(s.pop("lead_times"))) or ""
        s["total"] = round(s["total"], 2) if s["priced_lines"] else None
        if s["alternatives"]:
            flags.append(f"{s['supplier']} offered an alternative item on {s['alternatives']} line(s): check it is acceptable.")
        if str(s["prices_include_tax"]).lower() == "true":
            flags.append(f"{s['supplier']}'s prices include sales tax; others may not.")
    if len({s["currency"] for s in suppliers.values()}) > 1:
        flags.append("Suppliers quoted in different currencies: no ranking across currencies.")
    taxes = {str(s["prices_include_tax"]).lower() for s in suppliers.values()}
    if len(taxes) > 1:
        flags.append("Tax treatment differs between suppliers: compare with care.")
    n = len(suppliers)
    for it in items.values():
        if len(it["offers"]) < n:
            flags.append(f"Item {it['label']} was not quoted by every supplier.")
    return {"suppliers": list(suppliers.values()), "items": list(items.values()), "flags": flags}


def pending_rfqs(log_rows: list[dict], quote_rows: list[dict], days: int = 3, now: Optional[datetime] = None) -> list[dict]:
    """RFQs exported at least `days` ago that have no saved quote yet (oldest first)."""
    now = now or datetime.now()
    answered = {r.get("rfq_ref", "") for r in quote_rows}
    out = []
    for r in log_rows:
        ref = r.get("reference", "")
        try:
            sent = datetime.fromisoformat(r.get("timestamp", ""))
        except ValueError:
            continue
        age = (now - sent).days
        if ref and ref not in answered and age >= days:
            out.append({"reference": ref, "brand": r.get("brand", ""), "to_email": r.get("to_email", ""),
                        "sent": sent.date().isoformat(), "days_waiting": age})
    return sorted(out, key=lambda x: -x["days_waiting"])


def supplier_scorecard(quote_rows: list[dict], log_rows: Optional[list[dict]] = None) -> list[dict]:
    """Calculate performance metrics per supplier from quote history and RFQ logs (Sprint 3.1)."""
    if not quote_rows:
        return []

    # 1. Track item competition & wins
    wins_per_supplier: dict[str, int] = {}
    competed_per_supplier: dict[str, int] = {}
    for group in rfq_groups(quote_rows):
        cmp = build_comparison(quote_rows, group)
        for it in cmp["items"]:
            if len(it["offers"]) > 1 and it.get("best"):
                for supp in it["offers"]:
                    competed_per_supplier[supp] = competed_per_supplier.get(supp, 0) + 1
                winner = it["best"]
                wins_per_supplier[winner] = wins_per_supplier.get(winner, 0) + 1

    # 2. Sent timestamps from rfq_log
    log_sent_times: dict[str, datetime] = {}
    for r in (log_rows or []):
        ref = r.get("reference", "")
        ts = r.get("timestamp", "")
        if ref and ts:
            try:
                log_sent_times[ref] = datetime.fromisoformat(ts)
            except ValueError:
                pass

    # 3. Group by supplier and compute turnaround
    by_supplier: dict[str, list[dict]] = {}
    turnaround_times: dict[str, list[float]] = {}
    for r in quote_rows:
        supp = (r.get("supplier") or "").strip() or "Unknown"
        by_supplier.setdefault(supp, []).append(r)

        ref = r.get("rfq_ref", "")
        ts = r.get("timestamp", "")
        sent_time = log_sent_times.get(ref) or log_sent_times.get(base_reference(ref))
        if sent_time and ts:
            try:
                q_time = datetime.fromisoformat(ts)
                turnaround_days = (q_time - sent_time).total_seconds() / 86400.0
                if turnaround_days >= 0:
                    turnaround_times.setdefault(supp, []).append(turnaround_days)
            except ValueError:
                pass

    scorecard = []
    for supp, quotes in by_supplier.items():
        distinct_rfqs = len({r.get("rfq_ref", "") for r in quotes if r.get("rfq_ref")})
        items_quoted = len(quotes)

        # Most typical lead time
        lts = [r["lead_time"].strip() for r in quotes if (r.get("lead_time") or "").strip()]
        typical_lt = Counter(lts).most_common(1)[0][0] if lts else "Not stated"

        # Alternative items rate
        alt_count = sum(1 for r in quotes if str(r.get("alternative_offered", "")).lower() == "true")
        alt_rate = f"{(alt_count / items_quoted * 100):.0f}%" if items_quoted else "0%"

        # Win rate
        wins = wins_per_supplier.get(supp, 0)
        comp = competed_per_supplier.get(supp, 0)
        win_pct = round((wins / comp) * 100, 1) if comp > 0 else None
        win_str = f"{wins}/{comp} ({win_pct:.0f}%)" if comp > 0 else "N/A"

        # Avg Turnaround
        tt = turnaround_times.get(supp, [])
        if tt:
            avg_d = sum(tt) / len(tt)
            avg_turnaround = f"{avg_d:.1f} days" if avg_d >= 1.0 else f"{avg_d * 24:.0f} hrs"
        else:
            avg_turnaround = "-"

        scorecard.append({
            "Supplier": supp,
            "RFQs Quoted": distinct_rfqs,
            "Items Quoted": items_quoted,
            "Win Rate": win_str,
            "_win_pct": win_pct if win_pct is not None else -1.0,
            "Avg Turnaround": avg_turnaround,
            "Typical Lead Time": typical_lt,
            "Alternative Rate": alt_rate,
        })

    scorecard.sort(key=lambda x: (x["_win_pct"], x["Items Quoted"]), reverse=True)
    for s in scorecard:
        s.pop("_win_pct", None)
    return scorecard
