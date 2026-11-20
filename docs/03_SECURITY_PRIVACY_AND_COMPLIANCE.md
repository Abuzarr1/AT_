# Security, Privacy & Compliance Architecture

**Document Class:** Technical Risk & Compliance Specification  
**Target Audience:** CTO / Chief Information Security Officer (CISO) / Compliance Auditor  
**Scope:** Confidentiality, Input Sanitization, Cryptographic Secrets, and POSIX Concurrency  

---

## 1. Threat Model & Design Principles

Industrial procurement indenters face two existential risks:
1. **Disintermediation (Client Leakage):** If an international OEM or regional distributor discovers the end-user (e.g., an oil refinery, power plant, or municipal authority), the OEM may bypass the intermediary and quote direct.
2. **Data Poisoning & Injection:** Malicious or malformed supplier PDFs, quote spreadsheets, or email inputs could compromise backend stores or downstream spreadsheet consumers.

---

## 2. Multi-Layer Confidentiality Enforcement (Hard Rule 2)

### 2.1 The Banned Terms Engine
The core confidentiality engine operates on `data/banned_terms.txt` (a private, git-ignored file containing end-client corporate names, project titles, and geographical plant identifiers).

```python
# Multi-word regex pattern generator with arbitrary whitespace handling
def _pattern(term: str) -> re.Pattern:
    tokens = [re.escape(tok) for tok in term.strip().split()]
    regex = r"\b" + r"\s+".join(tokens) + r"\b"
    return re.compile(regex, re.IGNORECASE)
```

### 2.2 Inspection Gates
Banned terms are checked at five independent barriers:
1. **Extraction Display Gate:** Extracted items displayed in Streamlit are flagged if client terms slipped through.
2. **Template Composition Gate (`assert_clean`):** The email generator raises `BannedTermError` if any subject or body string contains a match.
3. **Delivery Terms Sanitization:**
   - In Pakistan Local mode: Site addresses are permitted only if explicitly allowed.
   - In International mode: Site references (`"plant"`, `"site"`, `"power station"`, `"ccpp"`, etc.) are unconditionally stripped, falling back to international airport/port terms:
     `"CPT Lahore Airport / FCA (Incoterms 2020)"`.
4. **PDF Document Generation Gate:** The ReportLab canvas stream is validated before writing to disk; presence of any banned string aborts PDF generation.
5. **Supplier Web Search Gate:** Queries sent to external search engines (Alibaba, Made-in-China, ThomasNet, Google) are scrubbed through `find_banned()`; if a banned term is detected, the URL generation is blocked.

---

## 3. Human-in-the-Loop Safeguards (Hard Rule 1)

The system enforces a strict boundary between draft preparation and network dispatch:
- **No Direct Send by Default:** Outgoing RFQs are generated as RFC-822 `.eml` files with the header `X-Unsent: 1`. When opened in Microsoft Outlook, Apple Mail, or Thunderbird, the email opens in an editable draft window for human review.
- **Webmail Deep-Linking:** For browser-based Roundcube dispatch, pre-filled URL query parameters load the draft into the Roundcube compose window without automated transmission.
- **UI Approval Checkbox:** In `app.py`, the `"Approve & Export .eml"` button is disabled until the operator ticks an explicit confirmation checkbox verifying they have reviewed line items, quantities, and delivery terms.

---

## 4. Input Sanitization & Injection Defense

### 4.1 CSV Formula Injection Protection
To prevent arbitrary code execution when procurement analysts open exported CSV files in Microsoft Excel or Google Sheets, all exported cells are passed through `utils.sanitize_csv_cell()`:

```python
def sanitize_csv_cell(value: object) -> str:
    """Prepend a single quote if a cell starts with formula characters (=, +, -, @, tab, CR)."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text
```
This is applied universally across `exporter.py`, `quote_store.py`, and the downloadable comparison tables in `pages/3_Compare_Quotes.py`.

### 4.2 File Upload & Path Sanitization
- File uploads are processed in-memory via byte buffers; temporary filenames are sanitized via `re.sub(r"[^A-Za-z0-9_.-]", "_", ...)`.
- File extensions are restricted to `.txt`, `.md`, and `.pdf`.

---

## 5. Secret Management & Private File Isolation

### 5.1 Environment Isolation
- All API keys (`GROQ_API_KEY`) and mail credentials (`IMAP_PASSWORD`, `SMTP_PASSWORD`) are loaded strictly from `.env` via `python-dotenv`.
- Neither `.env` nor credentials are ever logged to stdout, included in exception traces, or rendered in UI debug states.

### 5.2 Git Exclusion
The repository's `.gitignore` guarantees that client, company, and operational data never escape local infrastructure:
```gitignore
.env
data/suppliers.csv
data/banned_terms.txt
data/company.json
outputs/
evaluation/cases/*.json
```

---

## 6. Concurrency & Data Integrity

The system uses POSIX file locking (`fcntl.flock`) with `LOCK_EX` / `LOCK_UN` wrappers across all persistent file writes:
- `outputs/rfq_log.csv` (write-locked during RFQ generation)
- `outputs/quotes.csv` (write-locked during quote saves and batch updates)

This prevents corrupted rows or race conditions during simultaneous multi-analyst access over shared network drives.
