"""Streamlit page: compare saved supplier quotes line by line, see which RFQs wait for reply, and find new suppliers."""
from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from compare import build_comparison, pending_rfqs, rfq_groups, supplier_scorecard  # noqa: E402
from config import load_banned_terms  # noqa: E402
from exporter import build_reminder_eml  # noqa: E402
from quote_store import load_quotes, load_rfq_log  # noqa: E402
from rfq_drafter import find_banned  # noqa: E402
from ui_theme import apply_theme, render_header  # noqa: E402
from utils import sanitize_csv_cell  # noqa: E402
from imap_checker import check_supplier_replies, imap_configured, poll_supplier_replies  # noqa: E402
from suppliers import load_suppliers  # noqa: E402

st.set_page_config(page_title="Compare Quotes", page_icon="📊", layout="wide")
apply_theme()
render_header("Compare Quotes", "Line-by-line price comparison across suppliers, best-price marking & supplier performance scorecard", page_tag="Sprint 3 & 3.1")

# ---------- sidebar: supplier reply notifications ----------
with st.sidebar:
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
            _log_path = config.OUTPUT_DIR / "rfq_log.csv"
            import pandas as _pd
            if _log_path.exists():
                _log_df = _pd.read_csv(_log_path)
                _known_refs = _log_df["reference"].dropna().tolist() if "reference" in _log_df.columns else []
        except Exception:  # noqa: BLE001
            pass

        @st.cache_data(ttl=120, show_spinner="Checking inbox…")
        def _cached_poll_cq(refs: tuple[str, ...], emails: tuple[str, ...]):
            return poll_supplier_replies(refs, emails)

        _ok, _status, _replies = _cached_poll_cq(tuple(_known_refs), _supplier_emails)
        if not _ok:
            st.warning(f"⚠️ {_status}")
            st.caption("Check your IMAP settings in `.env`.")
        elif _replies:
            st.error(f"🔔 **{len(_replies)} new supplier reply(ies)** in your inbox!")
            for _r in _replies:
                st.markdown(
                    f"- **{_r['from']}** · _{_r['subject'][:60]}_  \n"
                    f"  Ref: `{_r['matched_ref']}` · {_r['date']}"
                )
        else:
            st.success(f"📭 {_status} — no new supplier replies.")
        st.link_button("Open Webmail 📬", config.WEBMAIL_URL)
        if st.button("🔄 Refresh inbox", key="cq_refresh_imap"):
            _cached_poll_cq.clear()
            st.rerun()
    else:
        st.caption("💡 Add `IMAP_HOST / IMAP_USER / IMAP_PASSWORD` to `.env` to enable notifications.")

quotes = load_quotes()
log = load_rfq_log()

tab1, tab2, tab3, tab4 = st.tabs(["📊 Quote Comparison", "🏆 Supplier Scorecard", "⏳ Pending RFQs & Reminders", "🔍 Find Suppliers"])

# ---------- tab 1: comparison ----------
with tab1:
    groups = rfq_groups(quotes)
    if not groups:
        st.info("No saved quotes yet. Parse a supplier reply on the Quote Parser page and click Save.")
    else:
        group = st.selectbox("Client RFQ", groups)
        cmp = build_comparison(quotes, group)
        suppliers = [s["supplier"] for s in cmp["suppliers"]]

        rows = []
        for it in cmp["items"]:
            row = {"Item": it["label"], "Qty": it["quantity"]}
            for name in suppliers:
                offer = it["offers"].get(name)
                price = offer.get("unit_price") if offer else ""
                cur = (offer.get("currency") or "") if offer else ""
                mark = " ✅" if it["best"] == name else ""
                row[name] = f"{cur} {price}{mark}".strip() if price != "" else "-"
            rows.append(row)
        st.markdown("**Unit price per item** (✅ = lowest, only when all offers share a currency)")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        summary = pd.DataFrame([{
            "Supplier": s["supplier"], "Currency": s["currency"], "Total": s["total"], "Lead time": s["lead_time"],
            "Validity": s["validity"], "Delivery": s["delivery_terms"], "Payment": s["payment_terms"],
            "Tax included": s["prices_include_tax"], "Alternatives": s["alternatives"],
        } for s in cmp["suppliers"]])
        st.markdown("**Supplier summary**")
        st.dataframe(summary, width="stretch", hide_index=True)

        for flag in cmp["flags"]:
            st.warning(flag)
        safe_rows_csv = pd.DataFrame(rows).map(sanitize_csv_cell).to_csv(index=False)
        st.download_button("Download comparison (CSV)", safe_rows_csv, f"comparison_{group}.csv", "text/csv")

# ---------- tab 2: scorecard (Sprint 3.1) ----------
with tab2:
    scorecard = supplier_scorecard(quotes, log)
    if not scorecard:
        st.info("No supplier history available yet. Ingest and save quotes on the Quote Parser page to generate supplier scorecards.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Suppliers Tracked", len(scorecard))
        m2.metric("Total Items Quoted", sum(s["Items Quoted"] for s in scorecard))
        top_supplier = scorecard[0]["Supplier"] if scorecard else "N/A"
        m3.metric("Top Competitor", top_supplier)

        st.markdown("**Supplier Performance & Historical Track Record**")
        st.caption("Tracks price competitiveness (win rate), average turnaround response time, typical lead times, and alternative offer rates.")
        safe_score_csv = pd.DataFrame(scorecard).map(sanitize_csv_cell).to_csv(index=False)
        st.dataframe(pd.DataFrame(scorecard), width="stretch", hide_index=True)
        st.download_button("Download Supplier Scorecard (CSV)", safe_score_csv, "supplier_scorecard.csv", "text/csv")

# ---------- tab 3: reminders ----------
with tab3:
    st.markdown("**Overdue Follow-up Reminders**")
    days = st.number_input("Remind me after (days without quote)", min_value=1, max_value=30, value=3)
    waiting = pending_rfqs(log, quotes, int(days))
    if not waiting:
        st.success("No RFQs are currently overdue." if log else "No RFQs exported yet.")
    else:
        st.dataframe(pd.DataFrame(waiting), width="stretch", hide_index=True)
        st.markdown("---")
        st.markdown("**Generate a reminder email** for any overdue supplier:")

        banned = load_banned_terms()

        for row in waiting:
            ref        = row["reference"]
            brand      = row["brand"]
            to_email   = row["to_email"]
            sent_date  = row["sent"]
            days_wait  = row["days_waiting"]

            with st.expander(f"📧 {ref}  —  {brand}  —  {days_wait} day(s) overdue", expanded=False):
                col_info, col_btn = st.columns([3, 1])
                with col_info:
                    st.caption(f"Supplier e-mail: **{to_email or '(not recorded)'}**")
                    contact = st.text_input(
                        "Contact name (for salutation)",
                        value="Sales Team",
                        key=f"contact_{ref}",
                    )
                    items_text = st.text_area(
                        "Items (one per line — paste from original RFQ or type)",
                        height=100,
                        key=f"items_{ref}",
                        placeholder="e.g.\nSiemens 3RT2026-1BB40  x2\nEaton DILM9-10  x4",
                    )

                with col_btn:
                    st.write("")  # vertical spacer
                    st.write("")
                    generate = st.button("Generate .eml", key=f"gen_{ref}", type="primary")

                if generate:
                    item_list = [ln.strip() for ln in items_text.splitlines() if ln.strip()]
                    try:
                        eml_bytes, eml_path = build_reminder_eml(
                            draft_ref=ref,
                            brand=brand,
                            to_email=to_email,
                            contact_name=contact,
                            original_items=item_list,
                            sent_date=sent_date,
                            banned=banned,
                        )
                        st.success(f"Reminder .eml saved → `{eml_path.name}`")
                        c_r_dl, c_r_rc, c_r_gm = st.columns([1, 1.2, 1])
                        with c_r_dl:
                            st.download_button(
                                label="⬇️ Download .eml",
                                data=eml_bytes,
                                file_name=eml_path.name,
                                mime="message/rfc822",
                                key=f"dl_{ref}",
                            )
                        with c_r_rc:
                            rc_rem_query = urllib.parse.urlencode({
                                "_task": "mail",
                                "_action": "compose",
                                "_to": to_email or "",
                                "_subject": f"Reminder: RFQ – {brand} – {ref}",
                                "_body": f"Following up on RFQ {ref} sent {sent_date}.",
                            })
                            webmail_base = getattr(config, "WEBMAIL_URL", "https://rc.ds.network/").rstrip("/")
                            st.link_button(
                                "Draft in Webmail 🌐",
                                f"{webmail_base}/?{rc_rem_query}",
                                type="primary",
                                help="Open pre-filled draft directly in Abdullah Traders Webmail",
                            )
                        with c_r_gm:
                            subject_enc = urllib.parse.quote(f"Reminder: RFQ – {brand} – {ref}")
                            body_preview = f"Following up on RFQ {ref} sent {sent_date}."
                            body_enc = urllib.parse.quote(body_preview)
                            to_enc = urllib.parse.quote(to_email or "")
                            gmail_url = (
                                f"https://mail.google.com/mail/?view=cm"
                                f"&to={to_enc}&su={subject_enc}&body={body_enc}"
                            )
                            st.link_button("Draft in Gmail ✉️", gmail_url)
                    except ValueError as exc:
                        st.error(f"⛔ Blocked term detected: {exc}")

# ---------- tab 4: supplier search ----------
with tab4:
    st.markdown("**Generate direct supplier search links** for Alibaba, Made-in-China, and ThomasNet:")
    col_sb, col_dummy = st.columns([2, 2])
    with col_sb:
        search_brand = st.text_input("Brand (e.g. Siemens, Emerson, Eaton)", value="", key="search_brand")
    search_items = st.text_area(
        "Item description or part numbers (one per line)",
        height=120,
        key="search_items",
        placeholder="e.g.\nSiemens 3RT2026-1BB40 contactor\nEaton DILM9-10\nXRNP3A-12kV fuse",
    )

    if st.button("Generate Supplier Search Links 🔍", key="gen_urls", type="primary"):
        lines = [ln.strip() for ln in search_items.splitlines() if ln.strip()]
        if not lines and not search_brand:
            st.warning("Please enter a brand or at least one item description.")
        else:
            raw_query = f"{search_brand} " + " ".join(lines) if search_brand else " ".join(lines)
            banned = load_banned_terms()
            found_banned = find_banned(raw_query, banned)
            if found_banned:
                st.error(
                    f"⛔ Blocked: Search query contains restricted end-client/project term(s): {', '.join(found_banned)}. "
                    "End-client names and site details must never reach external search engines."
                )
            else:
                query = raw_query
                encoded = urllib.parse.quote_plus(query)
                brand_enc = urllib.parse.quote_plus(search_brand) if search_brand else encoded

                alibaba_url = f"https://www.alibaba.com/trade/search?SearchText={encoded}"
                madeinchina_url = f"https://www.made-in-china.com/multi-search/{brand_enc}/F3/{encoded}/" if search_brand else f"https://www.made-in-china.com/multi-search/{encoded}/F1/"
                thomasnet_url = f"https://www.thomasnet.com/search/?searchterm={encoded}"
                google_url = f"https://www.google.com/search?q={encoded}+distributor+supplier"

                st.markdown(f"**Search query:** `{query}`")
            st.markdown("---")

            c1, c2 = st.columns(2)
            with c1:
                st.link_button("🌐 Search on Alibaba", alibaba_url, use_container_width=True)
                st.caption("Best for Asian / international OEM & replacement suppliers.")
                st.write("")
                st.link_button("🏭 Search on Made-in-China", madeinchina_url, use_container_width=True)
                st.caption("Direct Chinese manufacturing & factory sources.")
            with c2:
                st.link_button("🇺🇸 Search on ThomasNet", thomasnet_url, use_container_width=True)
                st.caption("North American certified industrial distributors & suppliers.")
                st.write("")
                st.link_button("🔎 Google Supplier Search", google_url, use_container_width=True)
                st.caption("Broad search for authorized global distributors.")
