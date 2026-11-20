# Strategic Roadmap, Technical Debt & Next Steps

**Document Class:** Engineering Roadmap & Technical Debt Audit  
**Target Audience:** CTO / Product Owner / Engineering Leadership  
**Current Milestone:** Sprints 1 – 3.3 Complete + Live IMAP Subsystem Active  

---

## 1. Project Velocity & Delivery Milestones

```
Sprint 1.0 (Core Engine)        ──► Ingestion, LangGraph extraction, Pydantic validation, EML export
Sprint 1.1 (Request Metadata)   ──► Global delivery terms, taxes, country of origin, RFQ serials
Sprint 2.0 (Quote Parser)       ──► Parsing supplier quote files, total checks, quotes.csv store
Sprint 2.5 (PDF Forms)          ──► Publication-quality PDF RFQs (ReportLab Local vs International)
Sprint 3.0 (Matrix Comparison)  ──► Line-by-line price comparison, currency isolation, overdue tracking
Sprint 3.1 (Multi-Contact & Score)► Multiple suppliers per OEM brand, win-rate & turnaround scorecard
Sprint 3.2 (Reminder Engine)    ──► 1-click overdue follow-up EML drafts, banned-term checks
Sprint 3.3 (Supplier Discovery) ──► Multi-market supplier discovery (Alibaba, Made-in-China, ThomasNet)
Sprint 3.4 (IMAP Monitoring)    ──► Live SSL mail polling, reply detection, Streamlit caching
```

---

## 2. Technical Debt & Architectural Observations

As with any rapid-delivery production system, several technical debt items should be addressed in subsequent iterations:

### 2.1 File-Based Storage vs. Relational Database
- **Current State:** State is stored in CSV files (`rfq_log.csv`, `quotes.csv`) protected by `fcntl.flock`.
- **Limitation:** While robust for small-to-medium single-server deployments (up to 50,000 quotes), CSV lacks ACID transactions, multi-table joins, and fine-grained indexing.
- **Recommended Action:** Migrate to **PostgreSQL** or **SQLite (WAL mode)** with an SQLAlchemy ORM layer.

### 2.2 OCR for Scanned Image PDFs
- **Current State:** PDF text extraction uses `pypdf`, which requires digital/selectable text streams. Scanned raster PDFs produce empty text and prompt the user to paste manually.
- **Recommended Action:** Integrate **Tesseract OCR** or a lightweight Vision LLM pipeline (e.g. `llama-3.2-vision`) to parse scanned physical spec sheets automatically.

### 2.3 Automated Multi-Currency Normalization
- **Current State:** To prevent invalid comparisons, quotes in USD, EUR, and PKR are strictly segregated. Analysts cannot sort quotes across currencies in a single table.
- **Recommended Action:** Implement an optional toggle for live currency conversion using a daily spot-rate API (e.g. Open Exchange Rates / State Bank of Pakistan daily rates) with visual badges marking converted prices.

### 2.4 Multi-User Authentication & Role-Based Access Control (RBAC)
- **Current State:** The Streamlit app runs in single-tenant mode where any analyst accessing the URL shares the global `outputs/` ledger.
- **Recommended Action:** Add Streamlit Authenticator or OAuth2/OIDC SSO with role separation:
  - *Junior Estimator:* Can extract BOMs and draft RFQs.
  - *Senior Estimator / Manager:* Can approve exports, edit supplier rosters, and review scorecards.

---

## 3. High-Priority Next Actions (Sprint 4 & Beyond)

1. **Enterprise Database Migration (PostgreSQL):** Transition from CSVs to relational tables (`rfqs`, `rfq_items`, `quotes`, `quote_items`, `suppliers`).
2. **Automated Quote Reply Parser from Webmail:** Currently, incoming replies are detected via IMAP and flagged in the sidebar. The next logical step is a **1-click "Ingest Reply" button** that extracts the attached quote PDF directly from IMAP and passes it to `quote_parser.py`.
3. **Containerization & Helm Chart:** Package the entire system into a multi-stage Docker container (`Dockerfile` + `docker-compose.yml`) for one-command deployment in staging and production clusters.
