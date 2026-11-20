"""Tests for imap_checker.py — fully offline, no real IMAP connection."""
from __future__ import annotations

import imaplib
import types
import unittest
from unittest.mock import MagicMock, patch

import imap_checker as ic


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_imap(search_results: dict[bytes, list[bytes]], headers: dict[bytes, dict]):
    """
    Build a fake IMAP object whose uid() method returns canned data.

    search_results: {criterion_bytes: [uid_bytes, ...]}
    headers:        {uid_bytes: {From: str, Subject: str, Date: str}}
    """
    imap = MagicMock()

    def uid_handler(command, *args):
        if command == "search":
            criterion = args[1]
            uids = search_results.get(criterion, [])
            uid_line = b" ".join(uids)
            return ("OK", [uid_line])
        elif command == "fetch":
            uid = args[0]
            if args[1] == "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])":
                hdr = headers.get(uid, {})
                raw = (
                    f"From: {hdr.get('From', '')}\r\n"
                    f"Subject: {hdr.get('Subject', '')}\r\n"
                    f"Date: {hdr.get('Date', 'Thu, 1 Jan 2026 00:00:00 +0500')}\r\n"
                    "\r\n"
                ).encode()
                return ("OK", [(b"", raw)])
            elif args[1] == "(ENVELOPE)":
                return ("OK", [b"envelope-data"])
        return ("OK", [None])

    imap.uid.side_effect = uid_handler
    imap.select.return_value = ("OK", [b"1"])
    imap.login.return_value = ("OK", [b"Logged in"])
    imap.logout.return_value = ("BYE", [b"Logged out"])
    return imap


def _factory(imap_obj):
    """Return a callable that returns `imap_obj` regardless of args."""
    return lambda host, port: imap_obj


# ---------------------------------------------------------------------------
# _decode_header
# ---------------------------------------------------------------------------

class TestDecodeHeader(unittest.TestCase):

    def test_plain_string(self):
        self.assertEqual(ic._decode_header("Hello World"), "Hello World")

    def test_empty_string(self):
        self.assertEqual(ic._decode_header(""), "")

    def test_none_safe(self):
        # _decode_header receives msg.get("From","") which is "" when missing
        self.assertEqual(ic._decode_header(""), "")

    def test_rfc2047_encoded(self):
        # UTF-8 Q-encoded header
        encoded = "=?utf-8?q?Siemens_Sales?="
        result = ic._decode_header(encoded)
        self.assertEqual(result, "Siemens Sales")


# ---------------------------------------------------------------------------
# _is_configured
# ---------------------------------------------------------------------------

class TestIsConfigured(unittest.TestCase):

    def test_all_set(self):
        with patch.multiple(ic, IMAP_HOST="imap.example.com",
                            IMAP_USER="u", IMAP_PASSWORD="p"):
            self.assertTrue(ic._is_configured())

    def test_missing_host(self):
        with patch.multiple(ic, IMAP_HOST="", IMAP_USER="u", IMAP_PASSWORD="p"):
            self.assertFalse(ic._is_configured())

    def test_missing_password(self):
        with patch.multiple(ic, IMAP_HOST="h", IMAP_USER="u", IMAP_PASSWORD=""):
            self.assertFalse(ic._is_configured())


# ---------------------------------------------------------------------------
# _build_search_criteria
# ---------------------------------------------------------------------------

class TestBuildSearchCriteria(unittest.TestCase):

    def test_produces_from_criteria(self):
        criteria = ic._build_search_criteria(["sales@siemens.com"], [])
        self.assertIn(b'FROM "sales@siemens.com"', criteria)

    def test_produces_subject_criteria(self):
        criteria = ic._build_search_criteria([], ["AT-2026-001"])
        self.assertIn(b'SUBJECT "AT-2026-001"', criteria)

    def test_injection_guard_strips_quotes(self):
        criteria = ic._build_search_criteria(['evil"@x.com'], [])
        for c in criteria:
            self.assertNotIn(b'evil"', c)

    def test_both_types(self):
        criteria = ic._build_search_criteria(["a@b.com"], ["REF-01"])
        self.assertEqual(len(criteria), 2)

    def test_empty_inputs(self):
        criteria = ic._build_search_criteria([], [])
        self.assertEqual(criteria, [])


# ---------------------------------------------------------------------------
# _match_reply
# ---------------------------------------------------------------------------

class TestMatchReply(unittest.TestCase):

    def _msg(self, frm="", subj=""):
        return {"from": frm, "subject": subj, "date": "", "uid": "1"}

    def test_matches_from_address(self):
        m = ic._match_reply(
            self._msg(frm="Siemens Sales <sales@siemens.com>"),
            ["sales@siemens.com"],
            [],
        )
        self.assertEqual(m, "sales@siemens.com")

    def test_matches_subject_ref(self):
        m = ic._match_reply(
            self._msg(subj="Re: AT-2026-001 / RFQ for drives"),
            [],
            ["AT-2026-001"],
        )
        self.assertEqual(m, "AT-2026-001")

    def test_no_match(self):
        m = ic._match_reply(
            self._msg(frm="random@unknown.com", subj="Hello"),
            ["sales@siemens.com"],
            ["AT-2026-001"],
        )
        self.assertIsNone(m)

    def test_case_insensitive_from(self):
        m = ic._match_reply(
            self._msg(frm="SALES@SIEMENS.COM"),
            ["sales@siemens.com"],
            [],
        )
        self.assertEqual(m, "sales@siemens.com")

    def test_case_insensitive_subject(self):
        m = ic._match_reply(
            self._msg(subj="re: at-2026-001"),
            [],
            ["AT-2026-001"],
        )
        self.assertEqual(m, "AT-2026-001")


# ---------------------------------------------------------------------------
# check_supplier_replies — integration-style with mock IMAP
# ---------------------------------------------------------------------------

class TestCheckSupplierReplies(unittest.TestCase):

    def _patch_config(self):
        return patch.multiple(
            ic,
            IMAP_HOST="imap.example.com",
            IMAP_PORT=993,
            IMAP_USER="sales@test.com",
            IMAP_PASSWORD="secret",
        )

    def test_returns_empty_when_not_configured(self):
        with patch.multiple(ic, IMAP_HOST="", IMAP_USER="", IMAP_PASSWORD=""):
            result = ic.check_supplier_replies(["REF-001"], ["a@b.com"])
        self.assertEqual(result, [])

    def test_returns_empty_when_no_refs_or_emails(self):
        with self._patch_config():
            result = ic.check_supplier_replies([], [])
        self.assertEqual(result, [])

    def test_finds_reply_by_from_address(self):
        uid = b"42"
        imap_obj = _make_imap(
            search_results={b'FROM "sales@siemens.com"': [uid]},
            headers={uid: {"From": "Siemens <sales@siemens.com>",
                           "Subject": "Quote for your enquiry",
                           "Date": "Thu, 20 Nov 2026 10:00:00 +0500"}},
        )
        with self._patch_config():
            result = ic.check_supplier_replies(
                known_refs=[], supplier_emails=["sales@siemens.com"],
                imap_factory=_factory(imap_obj),
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["matched_ref"], "sales@siemens.com")
        self.assertIn("siemens", result[0]["from"].lower())

    def test_finds_reply_by_subject_ref(self):
        uid = b"7"
        imap_obj = _make_imap(
            search_results={b'SUBJECT "AT-2026-001"': [uid]},
            headers={uid: {"From": "Supplier <supplier@example.com>",
                           "Subject": "Re: AT-2026-001 Quotation",
                           "Date": "Thu, 20 Nov 2026 09:00:00 +0500"}},
        )
        with self._patch_config():
            result = ic.check_supplier_replies(
                known_refs=["AT-2026-001"], supplier_emails=[],
                imap_factory=_factory(imap_obj),
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["matched_ref"], "AT-2026-001")

    def test_deduplicates_uid(self):
        """Same UID matched by both FROM and SUBJECT should appear once."""
        uid = b"5"
        imap_obj = _make_imap(
            search_results={
                b'FROM "sales@siemens.com"': [uid],
                b'SUBJECT "AT-2026-001"': [uid],
            },
            headers={uid: {"From": "Siemens <sales@siemens.com>",
                           "Subject": "Re: AT-2026-001",
                           "Date": "Thu, 20 Nov 2026 08:00:00 +0500"}},
        )
        with self._patch_config():
            result = ic.check_supplier_replies(
                known_refs=["AT-2026-001"],
                supplier_emails=["sales@siemens.com"],
                imap_factory=_factory(imap_obj),
            )
        uids = [r["uid"] for r in result]
        self.assertEqual(len(uids), len(set(uids)))

    def test_returns_empty_on_connection_error(self):
        """Any IMAP exception must be swallowed — returns [] not raises."""
        def bad_factory(host, port):
            raise ConnectionRefusedError("unreachable")

        with self._patch_config():
            result = ic.check_supplier_replies(
                known_refs=["AT-001"], supplier_emails=["x@y.com"],
                imap_factory=bad_factory,
            )
        self.assertEqual(result, [])

    def test_returns_empty_on_auth_error(self):
        imap_obj = MagicMock()
        imap_obj.login.side_effect = imaplib.IMAP4.error("LOGIN failed")

        with self._patch_config():
            result = ic.check_supplier_replies(
                known_refs=["AT-001"], supplier_emails=["x@y.com"],
                imap_factory=_factory(imap_obj),
            )
        self.assertEqual(result, [])

    def test_no_match_messages_excluded(self):
        """Messages from unknown senders with unrelated subjects are dropped."""
        uid = b"9"
        imap_obj = _make_imap(
            search_results={b'FROM "sales@siemens.com"': [uid]},
            headers={uid: {"From": "Random <random@noone.com>",
                           "Subject": "Newsletter",
                           "Date": "Thu, 20 Nov 2026 07:00:00 +0500"}},
        )
        with self._patch_config():
            result = ic.check_supplier_replies(
                known_refs=[], supplier_emails=["sales@siemens.com"],
                imap_factory=_factory(imap_obj),
            )
        # IMAP returned uid but _match_reply should reject it (wrong FROM)
        self.assertEqual(result, [])

    def test_multiple_replies(self):
        imap_obj = _make_imap(
            search_results={
                b'FROM "sales@siemens.com"': [b"1"],
                b'FROM "eaton@eaton.com"': [b"2"],
            },
            headers={
                b"1": {"From": "Siemens <sales@siemens.com>",
                       "Subject": "Quote", "Date": ""},
                b"2": {"From": "Eaton <eaton@eaton.com>",
                       "Subject": "RFQ Reply", "Date": ""},
            },
        )
        with self._patch_config():
            result = ic.check_supplier_replies(
                known_refs=[],
                supplier_emails=["sales@siemens.com", "eaton@eaton.com"],
                imap_factory=_factory(imap_obj),
            )
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# imap_configured helper
# ---------------------------------------------------------------------------

class TestImapConfigured(unittest.TestCase):

    def test_true_when_all_set(self):
        with patch.multiple(ic, IMAP_HOST="h", IMAP_USER="u", IMAP_PASSWORD="p"):
            self.assertTrue(ic.imap_configured())

    def test_false_when_missing(self):
        with patch.multiple(ic, IMAP_HOST="", IMAP_USER="u", IMAP_PASSWORD="p"):
            self.assertFalse(ic.imap_configured())


# ---------------------------------------------------------------------------
# save_draft_to_imap
# ---------------------------------------------------------------------------

class TestSaveDraftToImap(unittest.TestCase):

    def test_returns_false_when_not_configured(self):
        with patch.multiple(ic, IMAP_HOST="", IMAP_USER="", IMAP_PASSWORD=""):
            ok, msg = ic.save_draft_to_imap(b"fake-eml-bytes")
            self.assertFalse(ok)
            self.assertIn("not configured", msg)

    def test_appends_successfully_with_mock(self):
        mock_imap = MagicMock()
        mock_imap.login.return_value = ("OK", [b"Logged in"])
        mock_imap.list.return_value = ("OK", [b'(\\HasNoChildren \\Drafts) "." INBOX.Drafts'])
        mock_imap.append.return_value = ("OK", [b"Append completed"])

        with patch.multiple(ic, IMAP_HOST="imap.test", IMAP_PORT=993, IMAP_USER="u", IMAP_PASSWORD="p"):
            with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
                ok, msg = ic.save_draft_to_imap(b"fake-eml-bytes")
                self.assertTrue(ok)
                self.assertIn("saved", msg.lower())
                mock_imap.append.assert_called_once()


if __name__ == "__main__":
    unittest.main()
