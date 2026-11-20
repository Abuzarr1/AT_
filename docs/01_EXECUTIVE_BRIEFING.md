# Executive Briefing: Agentic Procurement Assistant

**Document Class:** Executive Technical Briefing  
**Target Audience:** Chief Technology Officer (CTO) / VP Engineering  
**Organization:** Abdullah Traders (Industrial Procurement & Indenting)  
**Status:** In Production / Active Evolution (Sprints 1 – 3.3 + IMAP Inbox Live)  

---

## 1. Executive Summary

The **Agentic Procurement Assistant** is an enterprise-grade automation system designed to eliminate manual data entry, brand routing errors, and client confidentiality leaks in high-volume industrial procurement operations.

In industrial trading and indenting, Abdullah Traders receives unstructured, complex multi-line requests and Bills of Materials (BOMs) from end-clients (e.g., power plants, chemical refineries, cement plants). A single client BOM often spans 5–50 distinct parts across multiple global OEMs (Siemens, Eaton, Danfoss, GF+, Schneider Electric, Minimax, etc.).

Historically, technical estimators spent hours manually:
1. Parsing unstructured client text/PDFs into discrete line items.
2. Grouping parts by manufacturer/OEM.
3. Manually redacting end-client identities and site locations to prevent disintermediation.
4. Formatting professional Request for Quotation (RFQ) emails and PDF specification sheets.
5. Ingesting incoming supplier quotation emails and spreadsheets.
6. Comparing unit prices, currencies, minimum order quantities (MOQ), and delivery lead times.

This project automates the entire ingestion-to-comparison lifecycle while enforcing **strict Human-in-the-Loop (HITL) review** and **cryptographic/regex confidentiality guardrails**.

---

## 2. Business Objectives & Strategic Impact

| Objective | Baseline (Manual) | System Target / Achievement |
|---|---|---|
| **Turnaround Time (BOM to Supplier RFQ)** | 45–90 minutes per RFQ | **< 2 minutes** review and generation |
| **Confidentiality / Client Leak Risk** | High (human copy-paste oversight) | **Zero Tolerance**: Multi-layer regex & Incoterm redaction |
| **Brand Misrouting** | Frequent alias confusion | **100% deterministic alias normalization** |
| **Quote Comparison Velocity** | Manual spreadsheet aggregation (1–2 days) | **Instant matrix comparison** with lowest-price marking |
| **Supplier Chasing & Reminders** | Manual calendar reminders (often dropped) | **Automated overdue tracking + 1-click reminder drafts** |
| **Supplier Reply Detection** | Manual inbox checking | **Real-time IMAP SSL inbox reply monitoring & alerting** |

---

## 3. Project Scope & Operational Boundaries

### In Scope
1. **Unstructured Ingestion:** Accepts free-form client emails, raw text tables, and text-based PDF BOMs.
2. **Deterministic Extraction & Validation:** Structured extraction via Groq OSS LLMs (`openai/gpt-oss-120b`) backed by Pydantic models with guided retry logic.
3. **Brand Canonicalization & Routing:** Automatically groups extracted items by brand and maps aliases to authorized supplier contacts in `data/suppliers.csv`.
4. **Multi-tier Confidentiality Redaction:** Replaces prohibited client names, project names, and site locations across email subject lines, email bodies, PDF forms, delivery terms, and exported filenames.
5. **Dual-Format Document Generation:** Generates draft standard `.eml` emails (RFC-822 with `X-Unsent: 1`) and publication-grade PDF forms (Local Pakistan vs. International Incoterms).
6. **Quote Ingestion & Matrix Comparison:** Parses incoming quotes (.txt, .pdf, .eml), checks arithmetic totals, and builds side-by-side comparison tables segregated strictly by currency (no invalid FX cross-ranking).
7. **Supplier Performance Analytics:** Calculates supplier turnaround time, quote responsiveness, and historical price competitiveness.
8. **Live IMAP Webmail Monitoring:** Background polling of `mail.abdullah-traders.com.pk:993` to detect incoming supplier replies by RFQ reference or sender email.

### Out of Scope (Explicit Non-Goals)
- **Zero Autonomous Sending:** The system **never** sends emails directly or autonomously. All outgoing communications are exported as drafts or opened in webmail for explicit human review and sign-off.
- **Speculative Cross-Currency Normalization:** The system refuses to rank USD, EUR, and PKR quotes against each other without explicit spot-rate configuration, preventing FX exposure.
- **Autonomous Pricing Negotiation:** The system does not negotiate or propose counter-offers without estimator input.

---

## 4. The 4 Non-Negotiable Hard Architectural Rules

1. **Rule 1 — Zero Auto-Send (HITL Enforcement):** Every outgoing email requires an explicit user review tick-box and approval action before generating `.eml` or launching Roundcube.
2. **Rule 2 — Absolute Client Redaction:** End-client names, project names, plant identifiers, and site addresses must never reach a supplier. Checked before extraction display, before PDF rendering, before `.eml` export, and before web supplier search generation.
3. **Rule 3 — Zero Credential Leakage:** All secrets (`GROQ_API_KEY`, `IMAP_PASSWORD`, `SMTP_PASSWORD`) reside exclusively in `.env`, are excluded from git, and are never logged or exposed in client UI.
4. **Rule 4 — Immutable Auditability:** Every generated RFQ and parsed quote is recorded with POSIX file locks (`fcntl.flock`) in local CSV stores with automatic CSV formula injection sanitization.
