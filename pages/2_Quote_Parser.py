"""Streamlit page: paste/upload a supplier reply -> review parsed quote -> approve & save to quotes.csv."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from extractor import MissingApiKeyError, RateLimitExhausted, get_llm  # noqa: E402
from quote_parser import find_reference, parse_quote, validate_quote  # noqa: E402
from quote_store import (  # noqa: E402
    delete_quotes,
    delete_quotes_by_batch,
    known_references,
    load_quotes,
    save_all_quotes,
    save_quote,
)
from schemas import QuoteLine, QuoteResult, to_number  # noqa: E402
from ui_theme import apply_theme, render_header  # noqa: E402
from utils import read_input  # noqa: E402

st.set_page_config(page_title="Quote Parser", page_icon="🧾", layout="wide")
apply_theme()
render_header("Quote Parser", "Read supplier quotations (.pdf, .eml, text) → Extract prices, lead times & terms → Save to database", page_tag="Sprint 2")

COLS = ["part_number", "description", "quantity", "unit_price", "total_price", "lead_time", "moq",
        "country_of_origin", "alternative_offered", "notes"]
SAMPLE = config.DATA_DIR / "sample_quote.txt"


def get_api_key() -> str:
    try:
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"]
    except Exception:  # noqa: BLE001
        pass
    return config.GROQ_API_KEY


def lines_to_df(lines: list[QuoteLine]) -> pd.DataFrame:
    df = pd.DataFrame([l.model_dump() for l in lines], columns=COLS)
    for col in ("quantity", "unit_price", "total_price"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["alternative_offered"] = df["alternative_offered"].fillna(False).astype(bool)
    return df


def df_to_lines(df: pd.DataFrame) -> list[QuoteLine]:
    lines = []
    for row in df.astype(object).where(df.notna(), None).to_dict("records"):
        if not any(row.get(c) not in (None, "") for c in ("part_number", "description", "unit_price")):
            continue
        lines.append(
            QuoteLine(
                part_number=row.get("part_number") or None,
                description=row.get("description") or None,
                quantity=to_number(row.get("quantity")),
                unit_price=to_number(row.get("unit_price")),
                total_price=to_number(row.get("total_price")),
                lead_time=row.get("lead_time") or None,
                moq=(str(row["moq"]) if row.get("moq") not in (None, "") else None),
                country_of_origin=row.get("country_of_origin") or None,
                alternative_offered=bool(row.get("alternative_offered")),
                notes=row.get("notes") or None,
            )
        )
    return lines


def load_sample() -> None:
    if SAMPLE.exists():
        st.session_state["q_text"] = SAMPLE.read_text(encoding="utf-8")


with st.sidebar:
    st.markdown("**API key:** " + ("✅ found" if get_api_key() else "❌ missing"))
    st.markdown(f"**Model:** `{config.GROQ_MODEL}`")
    st.markdown(f"**RFQs logged:** {len(known_references())}")

# ---------- input ----------
st.subheader("1. Supplier reply")
up = st.file_uploader("Upload a reply (.txt, .pdf, .eml)", type=["txt", "md", "pdf", "eml"])
if up is not None and st.session_state.get("q_upload_name") != up.name:
    st.session_state["q_text"] = read_input(up.name, up.getvalue())
    st.session_state["q_upload_name"] = up.name
    st.session_state["q_source"] = up.name
    if not st.session_state["q_text"].strip():
        st.warning("No text found in that file (scanned PDF?). Paste the text instead.")

st.button("Load sample quote", on_click=load_sample)
text = st.text_area("Paste the supplier's reply here", key="q_text", height=240)

if st.button("Parse quote", type="primary", disabled=not text.strip()):
    try:
        with st.spinner("Reading the quote..."):
            started = datetime.now()
            result = parse_quote(text, llm=get_llm(get_api_key()))
        refs = known_references()
        match = find_reference(text, refs, result.quote_ref)
        st.session_state.update(
            q_result=result,
            q_match=match,
            q_refs=refs,
            q_seconds=(datetime.now() - started).total_seconds(),
            q_version=st.session_state.get("q_version", 0) + 1,
        )
    except MissingApiKeyError as exc:
        st.error(str(exc))
    except RateLimitExhausted as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Something went wrong: {exc}")

# ---------- review ----------
if "q_result" in st.session_state:
    result: QuoteResult = st.session_state["q_result"]
    ver = st.session_state.get("q_version", 0)
    st.divider()
    st.subheader("2. Review the parsed quote")

    m1, m2, m3 = st.columns(3)
    m1.metric("Lines", len(result.lines))
    m2.metric("Currency", result.currency or "?")
    m3.metric("Time", f"{st.session_state.get('q_seconds', 0):.1f}s")

    h1, h2, h3 = st.columns(3)
    supplier = h1.text_input("Supplier", result.supplier_name or "", key=f"q_sup_{ver}")
    currency = h2.text_input("Currency", result.currency or "", key=f"q_cur_{ver}")
    validity = h3.text_input("Validity", result.validity or "", key=f"q_val_{ver}")
    h4, h5, h6 = st.columns(3)
    payment = h4.text_input("Payment terms", result.payment_terms or "", key=f"q_pay_{ver}")
    delivery = h5.text_input("Delivery terms", result.delivery_terms or "", key=f"q_del_{ver}")
    qdate = h6.text_input("Quote date", result.quote_date or "", key=f"q_date_{ver}")

    refs = st.session_state.get("q_refs", [])
    match = st.session_state.get("q_match")
    options = ["(not linked)"] + refs
    index = options.index(match) if match in options else 0
    rfq_ref = st.selectbox("Linked RFQ", options, index=index, key=f"q_ref_{ver}")
    if match:
        st.success(f"Matched to your RFQ {match}.")
    elif result.quote_ref:
        st.info(f"The reply quotes reference '{result.quote_ref}', which is not in your RFQ log. Pick one manually or leave unlinked.")
    else:
        st.info("No RFQ reference found in the reply. Pick one manually or leave unlinked.")

    edited = st.data_editor(lines_to_df(result.lines), num_rows="dynamic", width="stretch", key=f"q_editor_{ver}")

    current = QuoteResult(
        supplier_name=supplier.strip() or None,
        currency=currency.strip().upper()[:3] or None,
        validity=validity.strip() or None,
        payment_terms=payment.strip() or None,
        delivery_terms=delivery.strip() or None,
        quote_date=qdate.strip() or None,
        prices_include_tax=result.prices_include_tax,
        declined=result.declined,
        notes=result.notes,
        lines=df_to_lines(edited),
    )
    issues = validate_quote(current)
    if issues:
        with st.expander(f"⚠️ {len(issues)} thing(s) to check", expanded=True):
            for issue in issues:
                st.write("• " + issue)
    if result.notes:
        st.info(f"Notes from the quote: {result.notes}")
    if result.prices_include_tax is not None:
        st.caption("Prices include sales tax." if result.prices_include_tax else "Prices exclude sales tax.")

    c_approve, c_discard = st.columns([2, 1])
    with c_approve:
        if st.button("Approve & save to quotes.csv", type="primary", disabled=not current.lines):
            n = save_quote(
                current,
                rfq_ref="" if rfq_ref == "(not linked)" else rfq_ref,
                source=st.session_state.get("q_source", "pasted text"),
            )
            st.success(f"Saved {n} line(s) to outputs/quotes.csv.")
            st.session_state.pop("q_result", None)
            st.rerun()

    with c_discard:
        if st.button("Discard quote ❌"):
            st.session_state.pop("q_result", None)
            st.info("Parsed quote discarded.")
            st.rerun()

# ---------- history / edit / delete ----------
history = load_quotes()
if history:
    st.divider()
    st.subheader("Saved quotes database (Edit / Delete)")
    st.caption("You can edit prices, part numbers, terms, or delete rows directly in the table below, then click **Save Table Changes**.")

    df_hist = pd.DataFrame(history)
    edited_hist = st.data_editor(
        df_hist,
        num_rows="dynamic",
        width="stretch",
        key="quotes_history_editor",
    )

    col_save_chg, col_del_batch = st.columns([1, 2])
    with col_save_chg:
        if st.button("💾 Save Table Changes", type="primary"):
            records = edited_hist.astype(object).where(edited_hist.notna(), "").to_dict("records")
            save_all_quotes(records)
            st.success(f"Updated {len(records)} quotes in database!")
            st.rerun()

    with col_del_batch:
        # Build list of distinct quote batches
        batches = []
        for r in history:
            b_key = (r.get("timestamp", ""), r.get("rfq_ref", "") or "(unlinked)", r.get("supplier", "") or "Unknown")
            if b_key not in batches:
                batches.append(b_key)

        batch_options = [f"{ts} | {ref} | {sup}" for ts, ref, sup in batches]
        sel_batch = st.selectbox("Quick-delete entire quote batch:", ["(select a quote)"] + batch_options)
        if sel_batch != "(select a quote)":
            if st.button("🗑️ Delete This Quote Batch", type="secondary"):
                b_idx = batch_options.index(sel_batch)
                b_ts, b_ref, b_sup = batches[b_idx]
                actual_ref = "" if b_ref == "(unlinked)" else b_ref
                deleted_count = delete_quotes_by_batch(rfq_ref=actual_ref, supplier=b_sup, timestamp=b_ts)
                st.warning(f"Deleted {deleted_count} line item(s) from quotes database.")
                st.rerun()

