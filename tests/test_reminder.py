"""Offline tests for the reminder email builder (exporter.build_reminder_eml).

All tests run without any network or API calls.
"""
from __future__ import annotations

import email
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exporter import build_reminder_eml  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reminder(tmp_path: Path, **kwargs) -> tuple[bytes, Path]:
    defaults = dict(
        draft_ref="AT-RFQ-00200-SCHN",
        brand="Schneider Electric",
        to_email="sales@schneider.com",
        contact_name="Mr Hassan",
        original_items=["3RT2026-1BB40  x2", "DILM9-10  x4"],
        sent_date="2026-11-10",
        banned=[],
        out_dir=tmp_path,
    )
    defaults.update(kwargs)
    return build_reminder_eml(**defaults)


# ---------------------------------------------------------------------------
# Structure & headers
# ---------------------------------------------------------------------------

class TestReminderStructure:
    def test_returns_bytes_and_path(self, tmp_path):
        eml_bytes, path = _make_reminder(tmp_path)
        assert isinstance(eml_bytes, bytes) and len(eml_bytes) > 0
        assert isinstance(path, Path)

    def test_eml_file_created_on_disk(self, tmp_path):
        _, path = _make_reminder(tmp_path)
        assert path.exists() and path.suffix == ".eml"

    def test_filename_contains_REMINDER_prefix(self, tmp_path):
        _, path = _make_reminder(tmp_path)
        assert path.name.startswith("REMINDER-")

    def test_filename_contains_reference(self, tmp_path):
        _, path = _make_reminder(tmp_path, draft_ref="AT-RFQ-00999-EMER")
        assert "AT-RFQ-00999-EMER" in path.name

    def test_eml_is_parseable(self, tmp_path):
        eml_bytes, _ = _make_reminder(tmp_path)
        msg = email.message_from_bytes(eml_bytes)
        assert msg["Subject"] is not None

    def test_x_unsent_header_present(self, tmp_path):
        eml_bytes, _ = _make_reminder(tmp_path)
        msg = email.message_from_bytes(eml_bytes)
        assert msg["X-Unsent"] == "1"

    def test_from_header_contains_sender(self, tmp_path):
        eml_bytes, _ = _make_reminder(tmp_path)
        msg = email.message_from_bytes(eml_bytes)
        assert "Abuzar Rashid" in msg["From"] or "abdullah-traders" in msg["From"].lower()

    def test_to_header_matches_input(self, tmp_path):
        eml_bytes, _ = _make_reminder(tmp_path, to_email="buyer@example.com")
        msg = email.message_from_bytes(eml_bytes)
        assert "buyer@example.com" in msg["To"]


# ---------------------------------------------------------------------------
# Subject line
# ---------------------------------------------------------------------------

class TestReminderSubject:
    def _subject(self, tmp_path, **kwargs) -> str:
        eml_bytes, _ = _make_reminder(tmp_path, **kwargs)
        msg = email.message_from_bytes(eml_bytes)
        from email.header import decode_header, make_header
        return str(make_header(decode_header(msg["Subject"])))

    def test_subject_contains_reminder_keyword(self, tmp_path):
        assert "Reminder" in self._subject(tmp_path)

    def test_subject_contains_brand(self, tmp_path):
        assert "Danfoss" in self._subject(tmp_path, brand="Danfoss")

    def test_subject_contains_reference(self, tmp_path):
        assert "AT-RFQ-00200-SCHN" in self._subject(tmp_path, draft_ref="AT-RFQ-00200-SCHN")


# ---------------------------------------------------------------------------
# Body content
# ---------------------------------------------------------------------------

class TestReminderBody:
    def _body(self, tmp_path, **kwargs) -> str:
        eml_bytes, _ = _make_reminder(tmp_path, **kwargs)
        msg = email.message_from_bytes(eml_bytes)
        return msg.get_payload(decode=True).decode("utf-8", errors="replace")

    def test_body_greets_contact(self, tmp_path):
        body = self._body(tmp_path, contact_name="Mr Hassan")
        assert "Mr Hassan" in body

    def test_body_fallback_salutation_when_no_contact(self, tmp_path):
        body = self._body(tmp_path, contact_name="")
        assert "Sales Team" in body

    def test_body_contains_reference(self, tmp_path):
        body = self._body(tmp_path, draft_ref="AT-RFQ-00200-SCHN")
        assert "AT-RFQ-00200-SCHN" in body

    def test_body_contains_sent_date(self, tmp_path):
        body = self._body(tmp_path, sent_date="2026-11-10")
        assert "2026-11-10" in body

    def test_body_lists_items(self, tmp_path):
        body = self._body(tmp_path, original_items=["Fuse XRNP3A x6", "Contactor DILM9 x2"])
        assert "Fuse XRNP3A x6" in body
        assert "Contactor DILM9 x2" in body

    def test_body_fallback_when_no_items(self, tmp_path):
        body = self._body(tmp_path, original_items=[])
        assert "(see original RFQ)" in body

    def test_body_contains_sender_email(self, tmp_path):
        body = self._body(tmp_path)
        assert "abdullah-traders" in body.lower() or "@" in body

    def test_body_polite_followup_phrase(self, tmp_path):
        body = self._body(tmp_path)
        assert "following up" in body.lower() or "quotation" in body.lower()

    def test_eml_bytes_match_file_on_disk(self, tmp_path):
        eml_bytes, path = _make_reminder(tmp_path)
        assert path.read_bytes() == eml_bytes


# ---------------------------------------------------------------------------
# Banned-term enforcement
# ---------------------------------------------------------------------------

class TestReminderBannedTerms:
    def test_banned_term_in_items_raises(self, tmp_path):
        with pytest.raises(ValueError):
            _make_reminder(
                tmp_path,
                original_items=["Haveli Bahadur Shah item x1"],
                banned=["Haveli Bahadur Shah"],
            )

    def test_banned_term_in_contact_raises(self, tmp_path):
        with pytest.raises(ValueError):
            _make_reminder(
                tmp_path,
                contact_name="1263MW CCPP rep",
                banned=["1263MW CCPP"],
            )

    def test_clean_content_does_not_raise(self, tmp_path):
        # Must not raise
        _make_reminder(tmp_path, banned=["Haveli Bahadur Shah", "1263MW CCPP"])

    def test_empty_banned_list_always_passes(self, tmp_path):
        _make_reminder(tmp_path, banned=[])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestReminderEdgeCases:
    def test_special_chars_in_reference_sanitised_in_filename(self, tmp_path):
        _, path = _make_reminder(tmp_path, draft_ref="AT RFQ/00200 SCHN")
        # file must not contain spaces or slashes
        assert " " not in path.name and "/" not in path.name

    def test_whitespace_only_contact_falls_back_to_sales_team(self, tmp_path):
        eml_bytes, _ = _make_reminder(tmp_path, contact_name="   ")
        msg = email.message_from_bytes(eml_bytes)
        body = msg.get_payload(decode=True).decode()
        assert "Sales Team" in body

    def test_to_email_empty_string_accepted(self, tmp_path):
        """Empty to_email should still produce a valid .eml (user fills it in)."""
        eml_bytes, path = _make_reminder(tmp_path, to_email="")
        assert path.exists()

    def test_out_dir_created_if_missing(self, tmp_path):
        new_dir = tmp_path / "deep" / "sub"
        _make_reminder(new_dir)
        assert new_dir.exists()

    def test_overwrite_produces_valid_eml(self, tmp_path):
        """Calling twice with the same ref overwrites the file without error."""
        _make_reminder(tmp_path)
        eml_bytes, path = _make_reminder(tmp_path)
        assert path.exists() and len(eml_bytes) > 0
