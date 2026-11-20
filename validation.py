"""Checks on extracted items."""
from __future__ import annotations

from typing import Iterable

from schemas import LineItem


def validate_items(items: Iterable[LineItem]) -> list[str]:
    """Human-readable list of problems (one line per problematic item)."""
    issues = []
    for i, item in enumerate(items, start=1):
        missing = []
        if not item.brand:
            missing.append("brand")
        if not item.part_number:
            missing.append("part number")
        if not item.quantity:
            missing.append("quantity")
        if missing:
            label = (item.description or "item")[:35]
            issues.append(f"Item {i} ({label}): missing {', '.join(missing)}")
    return issues


def needs_retry(items: list[LineItem]) -> bool:
    """Retry the LLM only for hard failures: nothing extracted, or half the items lack brand/quantity.

    A missing part number alone is not retried: the text usually just doesn't contain it,
    and a pointless retry burns the free-tier token cap.
    """
    if not items:
        return True
    hard = sum(1 for it in items if not it.brand or not it.quantity)
    return hard / len(items) >= 0.5
