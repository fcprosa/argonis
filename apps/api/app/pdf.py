"""
PDF generation for narrative export.

Produces an A4 document with:
  - ARGONIS letterhead + CONFIDENTIAL watermark in header/footer
  - Case + narrative metadata table
  - Full narrative sections with per-section approval status
  - Screening results table (if any)
  - Audit trail (last 20 entries on the case)
  - Page numbers
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.enums import TA_CENTER, TA_LEFT  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore[import-untyped]
from reportlab.lib.units import cm  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas as pdfgen_canvas  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

C_BLACK  = colors.HexColor("#111111")
C_DARK   = colors.HexColor("#1F2937")
C_MID    = colors.HexColor("#6B7280")
C_LIGHT  = colors.HexColor("#9CA3AF")
C_BORDER = colors.HexColor("#E5E7EB")
C_BG     = colors.HexColor("#F9FAFB")
C_GREEN  = colors.HexColor("#15803D")
C_RED    = colors.HexColor("#DC2626")
C_AMBER  = colors.HexColor("#D97706")
C_BLUE   = colors.HexColor("#1D4ED8")

PAGE_W, PAGE_H = A4
MARGIN = 2.0 * cm


# ---------------------------------------------------------------------------
# Numbered canvas — provides "Page N of M" in footer
# ---------------------------------------------------------------------------

class _NumberedCanvas(pdfgen_canvas.Canvas):
    """Two-pass canvas that stamps page N of M after all pages are known."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_pages: list[dict[str, Any]] = []
        self._export_ts = ""

    def showPage(self) -> None:
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()  # type: ignore[attr-defined]

    def save(self) -> None:
        total = len(self._saved_pages)
        for i, state in enumerate(self._saved_pages, start=1):
            self.__dict__.update(state)
            self._draw_chrome(i, total)
            pdfgen_canvas.Canvas.showPage(self)
        pdfgen_canvas.Canvas.save(self)

    def _draw_chrome(self, page_num: int, total: int) -> None:
        self.saveState()

        # ── Header ─────────────────────────────────────────────────────────
        self.setFont("Helvetica-Bold", 9)
        self.setFillColor(C_BLACK)
        self.drawString(MARGIN, PAGE_H - 1.3 * cm, "ARGONIS")

        self.setFont("Helvetica", 8)
        self.setFillColor(C_RED)
        self.drawRightString(PAGE_W - MARGIN, PAGE_H - 1.3 * cm, "CONFIDENTIAL")

        self.setStrokeColor(C_BORDER)
        self.setLineWidth(0.5)
        self.line(MARGIN, PAGE_H - 1.55 * cm, PAGE_W - MARGIN, PAGE_H - 1.55 * cm)

        # ── Footer ─────────────────────────────────────────────────────────
        self.line(MARGIN, 1.5 * cm, PAGE_W - MARGIN, 1.5 * cm)

        self.setFont("Helvetica", 7)
        self.setFillColor(C_LIGHT)
        self.drawString(MARGIN, 1.1 * cm, self._export_ts)
        self.drawCentredString(
            PAGE_W / 2, 1.1 * cm, f"Page {page_num} of {total}"
        )
        self.drawRightString(
            PAGE_W - MARGIN, 1.1 * cm, "ARGONIS — CONFIDENTIAL"
        )

        self.restoreState()


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    normal = base["Normal"]

    return {
        "doc_title": ParagraphStyle(
            "doc_title",
            parent=normal,
            fontSize=16,
            fontName="Helvetica-Bold",
            textColor=C_BLACK,
            spaceAfter=4,
        ),
        "doc_subtitle": ParagraphStyle(
            "doc_subtitle",
            parent=normal,
            fontSize=9,
            fontName="Helvetica",
            textColor=C_MID,
            spaceAfter=12,
        ),
        "section_title": ParagraphStyle(
            "section_title",
            parent=normal,
            fontSize=10,
            fontName="Helvetica-Bold",
            textColor=C_DARK,
            spaceBefore=14,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            parent=normal,
            fontSize=9,
            fontName="Helvetica",
            textColor=C_DARK,
            leading=14,
            spaceAfter=6,
        ),
        "label": ParagraphStyle(
            "label",
            parent=normal,
            fontSize=7,
            fontName="Helvetica-Bold",
            textColor=C_LIGHT,
            spaceBefore=10,
            spaceAfter=3,
        ),
        "caption": ParagraphStyle(
            "caption",
            parent=normal,
            fontSize=8,
            fontName="Helvetica",
            textColor=C_MID,
        ),
        "table_header": ParagraphStyle(
            "table_header",
            parent=normal,
            fontSize=8,
            fontName="Helvetica-Bold",
            textColor=C_MID,
            alignment=TA_LEFT,
        ),
        "table_cell": ParagraphStyle(
            "table_cell",
            parent=normal,
            fontSize=8,
            fontName="Helvetica",
            textColor=C_DARK,
            leading=11,
        ),
        "center": ParagraphStyle(
            "center",
            parent=normal,
            fontSize=9,
            alignment=TA_CENTER,
            textColor=C_MID,
        ),
    }


def _hr() -> HRFlowable:
    return HRFlowable(
        width="100%", thickness=0.5, color=C_BORDER, spaceAfter=10, spaceBefore=6
    )


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _parse_title(title: str) -> tuple[str, str]:
    """'Investigation: Structuring — Ahmad Al-Rashid' → ('Structuring', 'Ahmad Al-Rashid')"""
    m = re.match(r"Investigation:\s*(.+?)\s*[—–-]+\s*(.+)$", title)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return title, ""


def _parse_ext_ref(description: str | None) -> str:
    """'[AML-2026-00201] | score 0.92' → 'AML-2026-00201'"""
    if not description:
        return "—"
    m = re.match(r"\[([^\]]+)\]", description)
    return m.group(1) if m else "—"


def _approval_label(approval_status: str) -> str:
    return {
        "approved": "✓ Approved",
        "rejected": "✗ Rejected",
        "pending":  "● Pending",
    }.get(approval_status, approval_status)


def _approval_color(approval_status: str) -> Any:
    return {
        "approved": C_GREEN,
        "rejected": C_RED,
        "pending":  C_AMBER,
    }.get(approval_status, C_MID)


def _fmt_iso(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y, %H:%M UTC")
    except ValueError:
        return iso


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_narrative_pdf(
    narrative: dict[str, Any],
    sections: list[dict[str, Any]],
    case: dict[str, Any],
    screening: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
) -> bytes:
    buf = io.BytesIO()
    S = _styles()
    export_ts = datetime.now(timezone.utc).strftime("%-d %b %Y %H:%M UTC")

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=2.2 * cm,
        bottomMargin=2.2 * cm,
        title=narrative.get("title", "Narrative Export"),
        author="Argonis",
        subject="AML Investigation Narrative",
    )

    alert_type, customer_name = _parse_title(case.get("title", ""))
    ext_ref = _parse_ext_ref(case.get("description"))
    story = []

    # ── Document header ────────────────────────────────────────────────────
    story.append(Paragraph(narrative.get("title", "Narrative"), S["doc_title"]))
    story.append(Paragraph(
        f"AML Investigation Narrative &nbsp;·&nbsp; Version {narrative.get('version', 1)}",
        S["doc_subtitle"],
    ))

    # Info table
    nar_status = narrative.get("status", "—").replace("_", " ").title()
    case_status = case.get("status", "—").replace("_", " ").title()

    info_data = [
        [
            Paragraph("CASE REF", S["table_header"]),
            Paragraph("CUSTOMER", S["table_header"]),
            Paragraph("ALERT TYPE", S["table_header"]),
            Paragraph("NARRATIVE STATUS", S["table_header"]),
            Paragraph("CASE STATUS", S["table_header"]),
        ],
        [
            Paragraph(ext_ref, S["table_cell"]),
            Paragraph(customer_name or "—", S["table_cell"]),
            Paragraph(alert_type or "—", S["table_cell"]),
            Paragraph(nar_status, S["table_cell"]),
            Paragraph(case_status, S["table_cell"]),
        ],
        [
            Paragraph("CREATED", S["table_header"]),
            Paragraph("UPDATED", S["table_header"]),
            Paragraph("EXPORTED", S["table_header"]),
            Paragraph("", S["table_header"]),
            Paragraph("", S["table_header"]),
        ],
        [
            Paragraph(_fmt_iso(narrative.get("created_at")), S["table_cell"]),
            Paragraph(_fmt_iso(narrative.get("updated_at")), S["table_cell"]),
            Paragraph(export_ts, S["table_cell"]),
            Paragraph("", S["table_cell"]),
            Paragraph("", S["table_cell"]),
        ],
    ]

    col_w = (PAGE_W - 2 * MARGIN) / 5
    info_table = Table(info_data, colWidths=[col_w] * 5, hAlign="LEFT")
    info_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), C_BG),
        ("BACKGROUND",   (0, 2), (-1, 2), C_BG),
        ("ROWBACKGROUNDS", (0, 1), (-1, 1), [colors.white]),
        ("ROWBACKGROUNDS", (0, 3), (-1, 3), [colors.white]),
        ("BOX",          (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",    (0, 0), (-1, -1), 0.25, C_BORDER),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(info_table)

    # ── Narrative sections ─────────────────────────────────────────────────
    story.append(Spacer(1, 10))
    story.append(_hr())
    story.append(Paragraph("NARRATIVE SECTIONS", S["label"]))

    for sec in sections:
        appr = sec.get("approval_status", "pending")
        appr_label = _approval_label(appr)
        appr_color = _approval_color(appr)

        # Section title row
        title_data = [[
            Paragraph(sec.get("title", ""), S["section_title"]),
            Paragraph(
                appr_label,
                ParagraphStyle(
                    "appr_inline",
                    parent=S["caption"],
                    textColor=appr_color,
                    fontName="Helvetica-Bold",
                    fontSize=8,
                    alignment=1,  # TA_RIGHT
                ),
            ),
        ]]
        title_table = Table(
            title_data,
            colWidths=[PAGE_W - 2 * MARGIN - 80, 80],
            hAlign="LEFT",
        )
        title_table.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "BOTTOM"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ]))
        story.append(title_table)

        # Content — strip inline citation tags like [EVID-001] for cleaner read
        content = sec.get("content", "").replace("\n", "<br/>")
        story.append(Paragraph(content, S["body"]))

        if sec.get("approved_by"):
            approved_at = _fmt_iso(sec.get("approved_at"))
            story.append(Paragraph(
                f"Reviewed by {sec['approved_by']} · {approved_at}",
                S["caption"],
            ))

        story.append(Spacer(1, 6))

    # ── Screening results ──────────────────────────────────────────────────
    story.append(_hr())
    story.append(Paragraph("SCREENING RESULTS", S["label"]))

    if screening:
        scr_data = [[
            Paragraph("ENTITY", S["table_header"]),
            Paragraph("LIST", S["table_header"]),
            Paragraph("CONFIDENCE", S["table_header"]),
            Paragraph("MATCH TYPE", S["table_header"]),
            Paragraph("STATUS", S["table_header"]),
        ]]
        for r in screening:
            match_data = r.get("match_data") or {}
            conf = r.get("match_confidence", 0)
            conf_pct = f"{conf * 100:.0f}%"
            scr_data.append([
                Paragraph(r.get("entity_name", "—"), S["table_cell"]),
                Paragraph(match_data.get("list_name", "—"), S["table_cell"]),
                Paragraph(conf_pct, S["table_cell"]),
                Paragraph(match_data.get("match_type", "—"), S["table_cell"]),
                Paragraph(r.get("status", "—"), S["table_cell"]),
            ])

        cw = (PAGE_W - 2 * MARGIN) / 5
        scr_table = Table(scr_data, colWidths=[cw * 1.4, cw * 1.2, cw * 0.6, cw * 0.9, cw * 0.9], hAlign="LEFT")
        scr_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), C_BG),
            ("BOX",          (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID",    (0, 0), (-1, -1), 0.25, C_BORDER),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_BG]),
        ]))
        story.append(scr_table)
    else:
        story.append(Paragraph("No screening results recorded.", S["caption"]))

    # ── Audit trail ────────────────────────────────────────────────────────
    story.append(_hr())
    story.append(Paragraph("AUDIT TRAIL", S["label"]))

    if audit_entries:
        aud_data = [[
            Paragraph("ACTION", S["table_header"]),
            Paragraph("TABLE", S["table_header"]),
            Paragraph("TIMESTAMP", S["table_header"]),
        ]]
        for entry in audit_entries:
            aud_data.append([
                Paragraph(entry.get("action", "—"), S["table_cell"]),
                Paragraph(entry.get("table_name", "—"), S["table_cell"]),
                Paragraph(_fmt_iso(entry.get("created_at")), S["table_cell"]),
            ])

        aud_cw = (PAGE_W - 2 * MARGIN) / 3
        aud_table = Table(aud_data, colWidths=[aud_cw * 0.5, aud_cw * 0.8, aud_cw * 1.7], hAlign="LEFT")
        aud_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), C_BG),
            ("BOX",          (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID",    (0, 0), (-1, -1), 0.25, C_BORDER),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_BG]),
        ]))
        story.append(aud_table)
    else:
        story.append(Paragraph("No audit entries found.", S["caption"]))

    story.append(Spacer(1, 20))
    story.append(Paragraph(
        f"This document was generated by Argonis on {export_ts} and is classified CONFIDENTIAL.",
        S["center"],
    ))

    # ── Build ──────────────────────────────────────────────────────────────
    def make_canvas(*args: Any, **kwargs: Any) -> _NumberedCanvas:
        c = _NumberedCanvas(*args, **kwargs)
        c._export_ts = f"Generated {export_ts}"
        return c

    doc.build(story, canvasmaker=make_canvas)
    return buf.getvalue()
