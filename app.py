"""Streamlit UI: paste/upload a request -> review extracted items -> review RFQ drafts -> approve & export."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import config
from agent import build_graph
from exporter import export_eml
from extractor import MissingApiKeyError, RateLimitExhausted, extract_items, get_llm
from imap_checker import check_supplier_replies, imap_configured, poll_supplier_replies, save_draft_to_imap
from rfq_drafter import BannedTermError, build_drafts
from rfq_pdf import build_rfq_pdf
from schemas import LineItem, RFQMeta
from suppliers import add_supplier, load_suppliers, normalize_brand
from ui_theme import apply_theme, render_header
from utils import read_input
from validation import validate_items

st.set_page_config(page_title="Procurement Assistant", page_icon="📦", layout="wide")
apply_theme()
render_header("Procurement Assistant", "Extract items → Route by brand → Redact restricted terms → Review & export branded RFQs", page_tag="RFQ Drafting")

COLUMNS = ["description", "brand", "part_number", "quantity", "unit", "specs"]
SAMPLE_PATH = config.DATA_DIR / "sample_request.txt"


def get_api_key() -> str:
    try:
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"]
    except Exception:  # noqa: BLE001
        pass
    return config.GROQ_API_KEY


def items_to_df(items: list[LineItem]) -> pd.DataFrame:
    df = pd.DataFrame([i.model_dump() for i in items], columns=COLUMNS)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
    return df


def df_to_items(df: pd.DataFrame) -> list[LineItem]:
    items = []
    for row in df.astype(object).where(df.notna(), None).to_dict("records"):
        desc = (row.get("description") or "").strip()
        if not desc:
            continue
        qty = row.get("quantity")
        items.append(
            LineItem(
                description=desc,
                brand=(row.get("brand") or None),
                part_number=(row.get("part_number") or None),
                quantity=int(qty) if qty is not None else None,
                unit=(row.get("unit") or "pcs"),
                specs=(row.get("specs") or None),
            )
        )
    return items


def load_sample():
    if SAMPLE_PATH.exists():
        st.session_state["raw_text"] = SAMPLE_PATH.read_text(encoding="utf-8")


# ---------- sidebar ----------
suppliers = load_suppliers()
banned = config.load_banned_terms()
with st.sidebar:
    st.header("Settings")
    sender_name = st.text_input("Sender name", config.SENDER_NAME)
    company = st.text_input("Company", config.SENDER_COMPANY)
    contact_count = sum(len(v) for v in suppliers.values()) if suppliers else 0
    st.markdown(f"**Suppliers on file:** {contact_count} contact(s) across {len(suppliers)} brand(s)")
    with st.expander("➕ Add New Supplier", expanded=False):
        with st.form("add_supplier_form", clear_on_submit=True):
            new_brand = st.text_input("Brand", placeholder="e.g. ABB, Yokogawa")
            new_contact = st.text_input("Contact Name", placeholder="e.g. Sales Team or Mr Khan")
            new_email = st.text_input("Email", placeholder="sales@example.com")
            new_co = st.text_input("Company (optional)", placeholder="e.g. Partner Dist.")
            if st.form_submit_button("Save Supplier", type="primary"):
                ok, msg = add_supplier(new_brand, new_contact, new_email, new_co)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    st.markdown(f"**Restricted terms:** {len(banned)} (`{config.DEFAULT_BANNED_FILE.name}`)")
    if config.DEFAULT_BANNED_FILE.name.endswith("example.txt"):
        st.warning("Using the example restricted-terms file. Create data/banned_terms.txt with your real end-client names.")
    form_style = st.radio(
        "RFQ form style",
        ["Local (Pakistan)", "International"],
        index=0,
        key="rfq_form_style_v2",
        help="Local (Pakistan): standard Pakistan form with NTN/STRN and local clauses (Abdullah Traders standard).",
    )
    company_profile = config.load_company()
    st.caption(f"Form company: {company_profile['name']} (edit data/company.json)")
    st.markdown("**API key:** " + ("✅ found" if get_api_key() else "❌ missing"))

    # ---- supplier reply notifications (IMAP) ----
    st.markdown("---")
    st.markdown("### 🔔 Supplier Inbox")
    if imap_configured():
        _supplier_emails = tuple(
            getattr(s, "email", "")
            for contacts in load_suppliers().values()
            for s in contacts
            if getattr(s, "email", "")
        )
        _known_refs = []
        try:
            import pandas as _pd
            _log_path = config.OUTPUT_DIR / "rfq_log.csv"
            if _log_path.exists():
                _log_df = _pd.read_csv(_log_path)
                _known_refs = _log_df["reference"].dropna().tolist() if "reference" in _log_df.columns else []
        except Exception:  # noqa: BLE001
            pass

        @st.cache_data(ttl=120, show_spinner="Checking inbox…")
        def _cached_poll(refs: tuple[str, ...], emails: tuple[str, ...]):
            return poll_supplier_replies(refs, emails)

        _ok, _status, _replies = _cached_poll(tuple(_known_refs), _supplier_emails)
        if not _ok:
            st.warning(f"⚠️ {_status}")
            st.caption("Check your IMAP settings in `.env`.")
        elif _replies:
            st.error(f"🔔 **{len(_replies)} new supplier reply(ies)** in your inbox!")
            for _r in _replies:
                st.markdown(
                    f"- **{_r['from']}** · _{_r['subject'][:60]}_  \n"
                    f"  Ref matched: `{_r['matched_ref']}` · {_r['date']}"
                )
        else:
            st.success(f"📭 {_status} — no new supplier replies.")
        st.link_button("Open Webmail 📬", config.WEBMAIL_URL)
        if st.button("🔄 Refresh inbox", key="sidebar_refresh_imap"):
            _cached_poll.clear()
            st.rerun()
    else:
        st.caption("💡 Add `IMAP_HOST / IMAP_USER / IMAP_PASSWORD` to `.env` to enable supplier reply notifications.")

# ---------- input ----------
st.markdown('<div class="step-pill">Step 1</div><div class="step-title">Client Request & BOM Input</div>', unsafe_allow_html=True)
uploaded = st.file_uploader("Upload a request (.txt, .md, .pdf)", type=["txt", "md", "pdf"])
if uploaded is not None and st.session_state.get("_uploaded_name") != uploaded.name:
    st.session_state["raw_text"] = read_input(uploaded.name, uploaded.getvalue())
    st.session_state["_uploaded_name"] = uploaded.name
    if not st.session_state["raw_text"].strip():
        st.warning("No text found in that file (scanned PDF?). Paste the text instead.")

st.button("Load sample request", on_click=load_sample)
raw_text = st.text_area("Paste the BOM / client message here", key="raw_text", height=220)

if st.button("Extract & draft RFQs", type="primary", disabled=not raw_text.strip()):
    try:
        llm = get_llm(get_api_key())
        graph = build_graph(
            extract_fn=lambda text, feedback=None: extract_items(text, feedback, llm=llm),
            suppliers=suppliers,
            banned_terms=banned,
            sender_name=sender_name,
            company=company,
        )
        started = datetime.now()
        with st.spinner("Extracting items and drafting RFQs..."):
            state = graph.invoke({"raw_text": raw_text, "attempts": 0})
        st.session_state.update(
            items=state["items"],
            issues=state.get("issues", []),
            notes=state.get("notes"),
            meta=state.get("meta") or RFQMeta(),
            drafts=state.get("drafts", []),
            warnings=state.get("warnings", []),
            attempts=state.get("attempts", 1),
            seconds=(datetime.now() - started).total_seconds(),
            draft_version=st.session_state.get("draft_version", 0) + 1,
            exported={},
        )
    except MissingApiKeyError as exc:
        st.error(str(exc))
    except RateLimitExhausted as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "connect" in msg.lower() or "connection" in msg.lower() or "network" in msg.lower():
            st.error(
                "⚠️ Could not reach Groq — check your internet connection. "
                "If the connection is fine, Groq may be temporarily down. "
                "Try again in a moment."
            )
        else:
            st.error(f"Something went wrong: {exc}")

# ---------- review items ----------
if "items" in st.session_state:
    st.divider()
    st.markdown('<div class="step-pill">Step 2</div><div class="step-title">Review Extracted Line Items</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Items", len(st.session_state["items"]))
    c2.metric("LLM attempts", st.session_state.get("attempts", 1))
    c3.metric("Time", f"{st.session_state.get('seconds', 0):.1f}s")

    if st.session_state.get("notes"):
        st.info(f"Extraction notes: {st.session_state['notes']}")
    if st.session_state.get("issues"):
        with st.expander(f"⚠️ {len(st.session_state['issues'])} item(s) need attention", expanded=True):
            for issue in st.session_state["issues"]:
                st.write("• " + issue)

    edited = st.data_editor(
        items_to_df(st.session_state["items"]),
        num_rows="dynamic",
        width="stretch",
        key=f"editor_{st.session_state.get('draft_version', 0)}",
    )
    meta = st.session_state.get("meta") or RFQMeta()
    ver = st.session_state.get("draft_version", 0)
    with st.expander("Request details (added to every RFQ)", expanded=True):
        d1, d2, d3 = st.columns(3)
        ref_in = d1.text_input("Your RFQ no.", meta.client_reference or "", key=f"m_ref_{ver}")
        terms_in = d2.text_input("Delivery terms", meta.delivery_terms or "", key=f"m_terms_{ver}")
        close_in = d3.text_input("Quote deadline", meta.closing_date or "", key=f"m_close_{ver}")
        e1, e2 = st.columns(2)
        origin_in = e1.checkbox("Ask for country of origin", meta.require_country_of_origin, key=f"m_origin_{ver}")
        tax_in = e2.checkbox("Ask for sales tax shown separately", meta.sales_tax_separate, key=f"m_tax_{ver}")

    def rebuild(rows_df: pd.DataFrame, fill_brand: str = "") -> None:
        new_items = df_to_items(rows_df)
        if fill_brand.strip():
            for it in new_items:
                if not (it.brand or "").strip():
                    it.brand = normalize_brand(fill_brand)
        new_meta = RFQMeta(
            client_reference=ref_in.strip() or None,
            delivery_terms=terms_in.strip() or None,
            closing_date=close_in.strip() or None,
            require_country_of_origin=origin_in,
            sales_tax_separate=tax_in,
        )
        drafts, warnings = build_drafts(new_items, suppliers, banned, sender_name, company, meta=new_meta)
        st.session_state.update(
            meta=new_meta,
            items=new_items,
            issues=validate_items(new_items),
            drafts=drafts,
            warnings=warnings,
            draft_version=st.session_state.get("draft_version", 0) + 1,
            exported={},
        )
        st.rerun()

    brand_col = edited["brand"].astype(object).where(edited["brand"].notna(), "")
    unassigned = brand_col.astype(str).str.strip() == ""
    named = [b for b in brand_col.astype(str).str.strip().tolist() if b]
    if unassigned.any():
        f1, f2 = st.columns([3, 1])
        fill = f1.text_input(
            f"{int(unassigned.sum())} row(s) have no brand: apply this brand to them",
            named[0] if named else "",
            key=f"fill_{ver}",
        )
        if f2.button("Apply & rebuild", disabled=not fill.strip()):
            rebuild(edited, fill)

    if st.button("Rebuild drafts from edited table"):
        rebuild(edited)

# ---------- review drafts ----------
if st.session_state.get("drafts"):
    st.divider()
    st.markdown('<div class="step-pill">Step 3</div><div class="step-title">Review, Edit & Export Supplier RFQs</div>', unsafe_allow_html=True)
    for w in st.session_state.get("warnings", []):
        st.warning(w)

    version = st.session_state.get("draft_version", 0)
    for i, draft in enumerate(st.session_state["drafts"]):
        draft_key = f"{draft.reference}_{i}"
        done = draft_key in st.session_state.get("exported", {})
        contact_label = draft.contact_name or draft.to_email
        contact_str = f" ({contact_label})" if contact_label else ""
        title = f"{'✅' if done else '✉️'} {draft.brand}{contact_str} · {draft.item_count} item(s) · {draft.reference}"
        with st.expander(title, expanded=not done):
            key = f"{i}_{version}"
            to_email = st.text_input("To", draft.to_email, key=f"to_{key}")
            if to_email.strip() and draft.brand != "Unassigned":
                brand_known = [s.email.lower() for s in suppliers.get(draft.brand, [])]
                if to_email.strip().lower() not in brand_known:
                    if st.button(f"💾 Save {to_email.strip()} as supplier for {draft.brand}", key=f"save_sup_{key}"):
                        ok, msg = add_supplier(draft.brand, draft.contact_name or "Sales Team", to_email.strip())
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
            subject = st.text_input("Subject", draft.subject, key=f"subj_{key}")
            body = st.text_area("Body", draft.body, height=360, key=f"body_{key}")

            attach = st.checkbox("Attach RFQ form (PDF)", True, key=f"att_{key}")
            pdf_bytes = None
            if attach:
                try:
                    pdf_bytes = build_rfq_pdf(draft, company_profile, banned, sender_name,
                                              international=form_style == "International")
                    st.download_button("Preview / download RFQ form (PDF)", pdf_bytes,
                                       file_name=f"{draft.reference}.pdf", mime="application/pdf", key=f"pdf_{key}")
                except BannedTermError as exc:
                    st.error(f"RFQ form blocked: {exc}")

            reviewed = st.checkbox(
                "I have reviewed this RFQ and confirmed all items, quantities, and terms",
                value=False,
                key=f"rev_{key}",
            )

            if st.button("Approve & export .eml", key=f"approve_{key}", disabled=done or not reviewed or (attach and pdf_bytes is None), type="primary"):
                try:
                    path = export_eml(draft, to_email, subject, body, banned, pdf_bytes=pdf_bytes)
                    st.session_state["exported"][draft_key] = {
                        "bytes": path.read_bytes(),
                        "name": path.name,
                        "pdf_bytes": pdf_bytes,
                        "pdf_name": f"{draft.reference}.pdf",
                    }
                    st.rerun()
                except BannedTermError as exc:
                    st.error(str(exc))

            if done:
                st.success("Approved and saved to outputs/approved/.")
                exported_data = st.session_state["exported"][draft_key]
                if isinstance(exported_data, dict):
                    dl_bytes = exported_data["bytes"]
                    dl_name = exported_data["name"]
                    pdf_dl_bytes = exported_data.get("pdf_bytes")
                    pdf_dl_name = exported_data.get("pdf_name", f"{draft.reference}.pdf")
                else:
                    dl_bytes = exported_data
                    dl_name = f"{draft.reference}.eml"
                    pdf_dl_bytes = None
                    pdf_dl_name = f"{draft.reference}.pdf"

                if not pdf_dl_bytes:
                    pdf_path = config.OUTPUT_DIR / "approved" / pdf_dl_name
                    if pdf_path.exists():
                        pdf_dl_bytes = pdf_path.read_bytes()

                c_eml, c_pdf, c_sync, c_webmail = st.columns([1, 1, 1.4, 1.2])
                with c_eml:
                    st.download_button(
                        "Download .eml 📧",
                        dl_bytes,
                        file_name=dl_name,
                        mime="message/rfc822",
                        key=f"dl_{key}",
                        help="Complete email file with PDF already attached (opens in Outlook/Apple Mail)",
                    )
                with c_pdf:
                    if pdf_dl_bytes:
                        st.download_button(
                            "Download PDF 📄",
                            pdf_dl_bytes,
                            file_name=pdf_dl_name,
                            mime="application/pdf",
                            key=f"dl_pdf_{key}",
                            help="Download the RFQ PDF to attach manually anywhere",
                        )
                    else:
                        st.caption("No PDF attached")
                with c_sync:
                    if imap_configured():
                        if st.button("Save to Webmail Drafts 📬", key=f"push_draft_{key}", help="Saves this draft directly to Roundcube Drafts folder WITH the PDF attached"):
                            with st.spinner("Saving draft to Roundcube..."):
                                ok_save, msg_save = save_draft_to_imap(dl_bytes)
                            if ok_save:
                                st.success("Saved to Webmail Drafts folder with PDF attached!")
                                st.caption("Open Roundcube -> Drafts to review and click Send.")
                            else:
                                st.error(msg_save)
                    else:
                        st.caption("IMAP not configured")
                with c_webmail:
                    import urllib.parse
                    rc_query = urllib.parse.urlencode({
                        "_task": "mail",
                        "_action": "compose",
                        "_to": to_email or "",
                        "_subject": subject,
                        "_body": body,
                    })
                    webmail_base = getattr(config, "WEBMAIL_URL", "https://rc.ds.network/").rstrip("/")
                    st.link_button(
                        "Open Compose Link 🌐",
                        f"{webmail_base}/?{rc_query}",
                        help="Opens Roundcube compose window in browser",
                    )
