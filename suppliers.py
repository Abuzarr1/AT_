"""Supplier lookup (CSV-backed) and brand normalisation."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import config


@dataclass
class Supplier:
    brand: str
    contact_name: str
    email: str
    company: str = ""


class SupplierList(list):
    """List of Suppliers for a brand; acts like a single Supplier for backward compatibility."""

    @property
    def brand(self) -> str:
        return self[0].brand if self else ""

    @property
    def contact_name(self) -> str:
        return self[0].contact_name if self else ""

    @property
    def email(self) -> str:
        return self[0].email if self else ""

    @property
    def company(self) -> str:
        return self[0].company if self else ""


def normalize_brand(raw: Optional[str]) -> Optional[str]:
    """Map aliases to a canonical brand; unknown brands are kept as written."""
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    return config.BRAND_ALIASES.get(cleaned.lower(), cleaned)


def load_suppliers(path: Path | None = None) -> dict[str, SupplierList]:
    path = path or config.SUPPLIERS_FILE
    suppliers: dict[str, SupplierList] = {}
    if not path.exists():
        return suppliers
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            brand = normalize_brand(row.get("brand"))
            if not brand:
                continue
            sup = Supplier(
                brand=brand,
                contact_name=(row.get("contact_name") or "").strip(),
                email=(row.get("email") or "").strip(),
                company=(row.get("company") or row.get("supplier_name") or "").strip(),
            )
            if brand not in suppliers:
                suppliers[brand] = SupplierList()
            suppliers[brand].append(sup)
    return suppliers


def add_supplier(
    brand: str,
    contact_name: str,
    email: str,
    company: str = "",
    path: Path | None = None,
) -> tuple[bool, str]:
    """Append a new supplier contact to data/suppliers.csv."""
    path = path or config.SUPPLIERS_FILE
    canonical_brand = normalize_brand(brand)
    if not canonical_brand:
        return False, "Brand name cannot be empty."
    clean_email = (email or "").strip()
    if not clean_email or "@" not in clean_email:
        return False, "A valid email address is required."
    clean_contact = (contact_name or "").strip() or "Sales Team"
    clean_company = (company or "").strip()

    # Check for duplicate
    current = load_suppliers(path)
    if canonical_brand in current:
        for existing in current[canonical_brand]:
            if existing.email.lower() == clean_email.lower():
                return False, f"Supplier with email '{clean_email}' already exists for {canonical_brand}."

    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["brand", "contact_name", "email", "company"])
        writer.writerow([canonical_brand, clean_contact, clean_email, clean_company])

    return True, f"Added {clean_contact} ({clean_email}) for {canonical_brand}."
