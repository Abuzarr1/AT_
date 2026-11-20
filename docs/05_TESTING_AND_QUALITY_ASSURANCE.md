# Testing & Quality Assurance Architecture

**Document Class:** QA Strategy & Test Coverage Matrix  
**Target Audience:** CTO / QA Lead / Principal Test Engineer  
**Test Runner:** `pytest`  
**Execution Time:** ~0.55s (100% offline, zero API expenditure)  

---

## 1. Testing Philosophy & Guardrails

The testing architecture follows three strict principles:
1. **Zero External Flakiness:** All 134 automated tests run completely offline. No live calls are made to Groq API or the IMAP mail server during unit/regression test runs.
2. **Deterministic Mocking:** LLM extraction is validated using injected fake models; IMAP polling is validated using an in-memory mock IMAP socket factory.
3. **Hard Rule Regression Protection:** Every security boundary (redaction, zero auto-send, formula sanitization, Incoterm rules) has dedicated negative assertions.

---

## 2. Test Suite Breakdown (134 Total Tests)

```
============================= 134 passed in 0.58s =============================
```

| Test Module | Test Count | Focus Areas Covered |
|---|---|---|
| **`tests/test_core.py`** | ~40 tests | - Extraction prompt & schema fidelity<br>- Brand alias routing (GF+, Schneider, Siemens, etc.)<br>- Multi-brand item grouping & partitioning<br>- Missing field detection (hard vs soft failures)<br>- Retry gate limiting (max 1 retry)<br>- RFC-822 `.eml` header formatting (`X-Unsent: 1`)<br>- Redaction engine (`assert_clean` & `BannedTermError`)<br>- Multi-word whitespace-insensitive regex matching |
| **`tests/test_pdf.py`** | ~15 tests | - ReportLab Flowable table layout & styles<br>- Local Pakistan PDF (NTN/STRN & provincial octroi clauses)<br>- International PDF (Incoterms 2020 CPT/FCA, strict site stripping)<br>- Byte-stream redaction guard |
| **`tests/test_quotes.py`** | ~20 tests | - Quote line item parsing from unstructured text/emails<br>- Unit price & line total coercion<br>- Total price cross-validation (arithmetic check)<br>- Quote storage & retrieval (`outputs/quotes.csv`)<br>- Multi-currency separation (no cross-currency ranking)<br>- Edit & delete quote operations (`save_all_quotes`, `delete_quotes`) |
| **`tests/test_reminder.py`** | ~29 tests | - Overdue calculation from `rfq_log.csv`<br>- Reminder subject and greeting composition<br>- Banned-term checks on reminder bodies<br>- Generation of `REMINDER-*.eml` draft artifacts |
| **`tests/test_imap.py`** | ~28 tests | - RFC-2047 mail header decoding (`_decode_header`)<br>- Search criteria builder with quote injection defense<br>- Envelope and body peek fetching<br>- Subject and sender reply matching algorithms<br>- UID deduplication<br>- Connection error and authentication failure graceful fallback |
| **`tests/test_utils.py` / Other** | ~2 tests | - `sanitize_csv_cell()` against `=`, `+`, `-`, `@`, `\t`, `\r` injection |

---

## 3. Critical Test Scenarios & Edge Cases

### 3.1 Banned Term Whitespace Invariance
**Scenario:** A client name like `"Kot Addu Power Company"` appears in a request split across a line break or with multiple tabs.  
**Assertion:** `rfq_drafter._pattern()` generates a tokenized regex `\bKot\s+Addu\s+Power\s+Company\b`, catching all whitespace variations.

### 3.2 CSV Formula Injection Defense
**Scenario:** A supplier submits a part number or notes beginning with `=cmd|' /C calc'!A0` or `-2+3`.  
**Assertion:** `sanitize_csv_cell()` prepends a single quote (`'`), ensuring spreadsheet software treats the cell as literal text.

### 3.3 International Incoterms Site Leak Prevention
**Scenario:** An estimator leaves a local power plant address in the delivery terms while switching form style to International.  
**Assertion:** `rfq_pdf.build_rfq_pdf()` detects site-specific keywords (`site`, `plant`, `ccpp`) and automatically overrides delivery terms with `"CPT Lahore Airport / FCA (Incoterms 2020)"`.

---

## 4. Benchmark & Accuracy Evaluation Harness

In addition to unit tests, `evaluation/eval_extract.py` provides an offline accuracy benchmark against golden test cases (`evaluation/cases/`):
```bash
make eval
```
- Compares extracted line items against verified BOM ground truth.
- Computes Precision, Recall, and Brand Accuracy.
- Ensures model upgrades or prompt tweaks do not regress extraction fidelity.
