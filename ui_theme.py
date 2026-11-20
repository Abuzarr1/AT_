"""Shared UI theme and styling matching the Abdullah Traders RFQ house style (#EA7424 accent)."""
from __future__ import annotations

import streamlit as st
import config


def apply_theme() -> dict:
    """Inject company-branded styles matching the RFQ PDF."""
    company = config.load_company()
    accent = company.get("accent", "#EA7424")
    name = company.get("name", "Abdullah Traders")
    logo = company.get("logo_text", "AT")

    st.markdown(
        f"""
        <style>
        :root {{
            --rfq-accent: {accent};
            --rfq-accent-hover: #d35f15;
            --rfq-accent-light: rgba(234, 116, 36, 0.08);
            --rfq-border: #e2e8f0;
        }}

        /* Clean container layout */
        .block-container {{
            padding-top: 1.6rem !important;
            padding-bottom: 3.5rem !important;
            max-width: 1280px !important;
        }}

        /* Branded header banner */
        .rfq-header-box {{
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 16px 22px;
            background: linear-gradient(135deg, rgba(234, 116, 36, 0.08) 0%, #ffffff 100%);
            border: 1.5px solid rgba(234, 116, 36, 0.22);
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
        }}
        .rfq-logo {{
            background: {accent};
            color: #ffffff !important;
            font-weight: 800;
            font-size: 22px;
            letter-spacing: 1.5px;
            width: 48px;
            height: 48px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 3px 8px rgba(234, 116, 36, 0.35);
            flex-shrink: 0;
        }}
        .rfq-header-text h1 {{
            font-size: 22px !important;
            font-weight: 700 !important;
            color: #0f172a !important;
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1.25 !important;
        }}
        .rfq-header-text p {{
            font-size: 13px !important;
            color: #64748b !important;
            margin: 4px 0 0 0 !important;
            padding: 0 !important;
        }}

        /* Step badges */
        .step-pill {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: {accent};
            color: white !important;
            font-weight: 700;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            padding: 4px 10px;
            border-radius: 6px;
            margin-bottom: 6px;
        }}
        .step-title {{
            font-size: 18px;
            font-weight: 700;
            color: #1e293b;
            margin-top: 2px;
            margin-bottom: 12px;
        }}

        /* Card / Expander styling */
        div[data-testid="stExpander"] {{
            border: 1px solid #e2e8f0 !important;
            border-radius: 10px !important;
            background-color: #ffffff !important;
            margin-bottom: 14px !important;
            transition: all 0.2s ease !important;
        }}
        div[data-testid="stExpander"]:hover {{
            border-color: rgba(234, 116, 36, 0.45) !important;
            box-shadow: 0 4px 12px rgba(234, 116, 36, 0.06) !important;
        }}

        /* Metric cards */
        div[data-testid="stMetric"] {{
            background: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-left: 4px solid {accent} !important;
            border-radius: 10px !important;
            padding: 12px 16px !important;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03) !important;
        }}
        div[data-testid="stMetricLabel"] p {{
            color: #64748b !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.5px !important;
        }}
        div[data-testid="stMetricValue"] {{
            color: #0f172a !important;
            font-weight: 700 !important;
        }}

        /* Buttons */
        div.stButton > button[kind="primary"] {{
            background: linear-gradient(135deg, {accent} 0%, #db6518 100%) !important;
            border: none !important;
            color: #ffffff !important;
            font-weight: 600 !important;
            border-radius: 8px !important;
            padding: 0.5rem 1.25rem !important;
            box-shadow: 0 2px 6px rgba(234, 116, 36, 0.3) !important;
            transition: all 0.2s ease !important;
        }}
        div.stButton > button[kind="primary"]:hover {{
            box-shadow: 0 4px 12px rgba(234, 116, 36, 0.45) !important;
            transform: translateY(-1px) !important;
        }}
        div.stButton > button[kind="secondary"] {{
            border-radius: 8px !important;
            border: 1px solid #cbd5e1 !important;
            font-weight: 500 !important;
            transition: all 0.15s ease !important;
        }}
        div.stButton > button[kind="secondary"]:hover {{
            border-color: {accent} !important;
            color: {accent} !important;
        }}

        /* Download buttons */
        div.stDownloadButton > button {{
            border-radius: 8px !important;
            font-weight: 600 !important;
            border: 1px solid rgba(234, 116, 36, 0.4) !important;
            background-color: rgba(234, 116, 36, 0.05) !important;
            color: {accent} !important;
            transition: all 0.15s ease !important;
        }}
        div.stDownloadButton > button:hover {{
            background-color: {accent} !important;
            color: #ffffff !important;
            border-color: {accent} !important;
        }}

        /* Sidebar styling */
        section[data-testid="stSidebar"] {{
            background-color: #fbfbfc !important;
            border-right: 1px solid #e2e8f0 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    return company


def render_header(title: str, subtitle: str, page_tag: str = "") -> None:
    """Render the signature Abdullah Traders branded header banner."""
    company = config.load_company()
    logo = company.get("logo_text", "AT")
    name = company.get("name", "Abdullah Traders")
    tag_html = f"<span style='background: #e2e8f0; color: #475569; font-size: 11px; padding: 2px 7px; border-radius: 4px; margin-left: 8px; font-weight: 600;'>{page_tag}</span>" if page_tag else ""

    st.markdown(
        f"""
        <div class="rfq-header-box">
            <div class="rfq-logo">{logo}</div>
            <div class="rfq-header-text">
                <h1>{name} · {title} {tag_html}</h1>
                <p>{subtitle}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
