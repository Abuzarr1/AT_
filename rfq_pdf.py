"""RFQ form PDF in the Abdullah Traders house style (local and international wording).

Every string that goes onto the form has already been redacted by rfq_drafter. As a last guard the
finished PDF's text is extracted and checked against the restricted terms before it is returned.
"""
from __future__ import annotations

import io
import re
from datetime import date
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from rfq_drafter import assert_clean
from schemas import LineItem, RFQDraft

PAGE_W, PAGE_H = A4
LEFT = RIGHT = 14 * mm
HEADER_BOTTOM = 130  # points from top of page 1 where the story starts


def _fmt_date(d: Optional[date]) -> str:
    return (d or date.today()).strftime("%d-%b-%Y")


def _unit(unit: Optional[str]) -> str:
    u = (unit or "pcs").strip().lower()
    return "EACH" if u in {"pcs", "pc", "each", "ea", "piece", "pieces"} else u.upper()


def _qty(q: Optional[int]) -> str:
    return f"{q:.2f}" if q else "TBC"


def _styles(accent: colors.Color) -> dict:
    base = dict(fontName="Times-Roman", fontSize=8.6, leading=11)
    return {
        "body": ParagraphStyle("body", **base),
        "right": ParagraphStyle("right", alignment=2, **base),
        "right_b": ParagraphStyle("right_b", alignment=2, **{**base, "fontName": "Times-Bold"}),
        "bold": ParagraphStyle("bold", **{**base, "fontName": "Times-Bold"}),
        "cell": ParagraphStyle("cell", fontName="Times-Roman", fontSize=7.8, leading=10),
        "head": ParagraphStyle("head", fontName="Times-Roman", fontSize=8.2, leading=10),
        "note": ParagraphStyle("note", fontName="Times-Roman", fontSize=7, leading=9),
    }


def _header(canvas: Canvas, doc, company: dict, accent: colors.Color, international: bool) -> None:
    canvas.saveState()
    if doc.page == 1:
        top = PAGE_H - 15
        box_h = 98
        canvas.setLineWidth(0.8)
        canvas.setStrokeColor(colors.black)
        canvas.rect(14, top - box_h, PAGE_W - 28, box_h)

        x = 52
        canvas.setFillColor(accent)
        canvas.setFont("Times-Bold", 19)
        canvas.drawString(x, top - 33, company["name"].upper())
        canvas.setFillColor(colors.black)
        canvas.setFont("Times-Roman", 8.6)
        canvas.drawString(x, top - 46, company["address"])
        line3 = []
        if not international:
            if company.get("ntn"):
                line3.append(f"NTN {company['ntn']}")
            if company.get("strn"):
                line3.append(f"STRN {company['strn']}")
        if company.get("phone"):
            line3.append(f"Ph: {company['phone']}")
        if international and company.get("email"):
            line3.append(company["email"])
        canvas.drawString(x, top - 58, "  |  ".join(line3))

        canvas.setStrokeColor(accent)
        canvas.setLineWidth(1.6)
        canvas.line(x, top - 68, 447, top - 68)

        canvas.setFillColor(colors.black)
        canvas.setFont("Times-Bold", 10.5)
        canvas.drawString(x, top - 92, "REQUEST FOR QUOTATION")

        canvas.setFillColor(accent)
        canvas.roundRect(455, top - 77, 52, 52, 8, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 24 if len(company["logo_text"]) <= 2 else 16)
        canvas.drawCentredString(481, top - 58, company["logo_text"])
    else:
        canvas.setFont("Times-Bold", 9)
        canvas.setFillColor(accent)
        canvas.drawString(LEFT, PAGE_H - 22, company["name"].upper())
        canvas.setFillColor(colors.black)
        canvas.setFont("Times-Roman", 8)
        canvas.drawRightString(PAGE_W - RIGHT, PAGE_H - 22, f"Request for Quotation - page {doc.page}")
    canvas.setFont("Times-Roman", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawCentredString(PAGE_W / 2, 14, f"Page {doc.page}")
    canvas.restoreState()


def _description(item: LineItem) -> str:
    first = escape(item.description or "")
    if item.part_number:
        first += f" -- Part No: {escape(item.part_number)}"
    lines = [first]
    if item.specs:
        spec_parts = [s.strip() for s in re.split(r"[;\n]+", item.specs) if s.strip()]
        for s in spec_parts:
            lines.append(escape(s))
    if item.brand:
        lines.append(f"MAKE : {escape(item.brand.upper())}")
    return "<br/>".join(lines)


def build_rfq_pdf(
    draft: RFQDraft,
    company: dict,
    banned: list[str],
    sender_name: str,
    international: bool = False,
    issue_date: Optional[date] = None,
) -> bytes:
    """Return the RFQ form for one supplier draft as PDF bytes."""
    accent = colors.HexColor(company.get("accent", "#EA7424"))
    st = _styles(accent)
    meta = draft.meta
    name = escape(company["name"])
    story: list = []

    story.append(Spacer(1, HEADER_BOTTOM - 28))

    story.append(Paragraph(f"<b>{escape(company['name'])}</b>", st["right"]))
    if company.get("address"):
        story.append(Paragraph(escape(company["address"]), st["right"]))
    story.append(Paragraph(f"Attn: {escape(sender_name)}", st["right"]))
    if international and draft.contact_name:
        story.append(Paragraph(f"Vendor Attn: {escape(draft.contact_name)}", st["right"]))
    story.append(Spacer(1, 10))

    if international:
        intro = (f"{name} invites you to quote for the following items in the quantities stated. "
                 "Please state your price, currency and Incoterm, and the lead time for delivery to our facility in "
                 "Pakistan.")
    else:
        intro = (f"{name} invites you to tender for the following items in the quantities stated. Your price(s) must be "
                 "fully inclusive of all delivery charges, taxes, octroi and other costs necessary to deliver the goods "
                 "to our Lahore facility.")
    story.append(Paragraph(intro, st["body"]))
    story.append(Spacer(1, 3))
    if company.get("ship_to"):
        story.append(Paragraph(f"Intended Ship to Address: {escape(company['ship_to'])}", st["body"]))
    story.append(Spacer(1, 10))

    info = Table(
        [[Paragraph(f"<b>RFQ No:</b> {escape(draft.reference)}", st["body"]),
          Paragraph(f"<b>Opening Date:</b> {_fmt_date(issue_date)}", st["body"])],
         [Paragraph(f"{escape(draft.brand)} - {draft.item_count} item(s)" if draft.brand != "Unassigned" else "", st["body"]),
          Paragraph(f"<b>Closing Date:</b> {escape(meta.closing_date or 'To be advised')}", st["body"])]],
        colWidths=[(PAGE_W - 2 * LEFT) * 0.55, (PAGE_W - 2 * LEFT) * 0.45],
    )
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                              ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story.append(info)
    story.append(Spacer(1, 8))

    width = PAGE_W - 2 * LEFT
    rows = [[Paragraph("Sr.#", st["head"]), Paragraph("Description", st["head"]),
             Paragraph("Qty", st["head"]), Paragraph("Unit", st["head"])]]
    for n, item in enumerate(draft.items, start=1):
        rows.append([Paragraph(str(n), st["cell"]), Paragraph(_description(item), st["cell"]),
                     Paragraph(_qty(item.quantity), st["cell"]), Paragraph(_unit(item.unit), st["cell"])])
    table = Table(rows, colWidths=[width * 0.08, width * 0.62, width * 0.15, width * 0.15], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.93, 0.93, 0.93)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))

    if international:
        d_raw = (meta.delivery_terms or "").strip()
        has_site_word = any(w in d_raw.lower() for w in ["haveli", "bahadur", "jhang", "ccpp", "plant", "site", "station", "complex", "project"])
        valid_incoterms = ["CPT", "FCA", "FOB", "CIF", "CFR", "EXW", "DAP"]
        matched_inc = [inc for inc in valid_incoterms if inc in d_raw.upper()]
        if d_raw and matched_inc and not has_site_word:
            deliv = d_raw
        else:
            deliv = "CPT Lahore Airport / FCA (Incoterms 2020)"
        pay_term = "to be stated by supplier"
    else:
        deliv = "Delivered to our Lahore facility (inclusive of all carriage, octroi & local taxes)"
        pay_term = "to be stated by supplier"

    story.append(Paragraph(f"<b>Payment Terms:</b> {escape(pay_term)}", st["body"]))
    story.append(Paragraph(f"<b>Delivery Terms:</b> {escape(deliv)}", st["body"]))
    story.append(Spacer(1, 10))

    notes = []
    if international:
        notes.append("Please quote unit price and total price in USD / EUR.")
        notes.append(f"Delivery Terms: {escape(deliv)}.")
        notes.append("Please state the country of origin (COO) and HS Tariff Code for each item.")
        notes.append("Please provide estimated gross shipping weight and dimensions (CBM) for freight calculation.")
        notes.append("Please include lead time, minimum order quantity and offer validity (minimum 30 days).")
        notes.append(f"Any resultant order will be made in accordance with {name}' terms and conditions as stated in the purchase order.")
    else:
        if meta.require_country_of_origin:
            notes.append("Note: Please illustrate country of origin in your quotation.")
        notes.append("Scope of work is attached in case of service.")
        notes.append(f"Any resultant order will be made in accordance with {name}' terms and conditions as mentioned in the PO.")
        if meta.sales_tax_separate:
            notes.append("Please be advised that if you are a sales-tax registered individual/company/firm, you should "
                         "indicate the Sales Tax amount separately on the taxable supplies in your quote.")
        notes.append("Your quotation must be complete for all commercial and technical terms, addressed to the "
                     "undersigned, and received at the above address not later than the date mentioned above.")
        notes.append(f"Any resultant purchase order will be made in accordance with {name}' terms and conditions and the scope of work/supply described in this enquiry.")
    if international and meta.sales_tax_separate:
        notes.append("If sales tax or VAT applies, please show it separately.")
    for note in notes:
        story.append(Paragraph(note, st["note"]))
    story.append(Spacer(1, 16))

    sig = [Paragraph(f"<b>{escape(sender_name.upper())}</b>", st["body"])]
    if company.get("phone"):
        sig.append(Paragraph(escape(company["phone"]), st["body"]))
    sig.append(Paragraph(f"Procurement, {name}", st["body"]))
    email = company.get("email") or "sales@abdullah-traders.com.pk"
    sig.append(Paragraph(f"Mail: {escape(email)}", st["body"]))
    story.extend(sig)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT, topMargin=34, bottomMargin=28,
                            title=f"RFQ {draft.reference}", author=company["name"])
    draw = lambda c, d: _header(c, d, company, accent, international)  # noqa: E731
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    data = buf.getvalue()

    # Final guard: no restricted term may appear anywhere in the finished document.
    from pypdf import PdfReader

    text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    assert_clean(text, banned)
    return data
