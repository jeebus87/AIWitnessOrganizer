"""Export service for generating PDF and Excel reports"""
import io
from datetime import datetime
from typing import List, Dict, Any, Optional

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, PageBreak
)

from app.db.models import Witness, Matter, Document


class ExportService:
    """Service for generating PDF and Excel witness reports"""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Set up custom paragraph styles for PDF"""
        self.styles.add(ParagraphStyle(
            name="WitnessName",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=colors.darkblue
        ))

        self.styles.add(ParagraphStyle(
            name="Observation",
            parent=self.styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.black
        ))

        self.styles.add(ParagraphStyle(
            name="CoverTitle",
            parent=self.styles["Title"],
            fontSize=24,
            spaceAfter=20
        ))

    def witnesses_to_dataframe(
        self,
        witnesses: List[Dict[str, Any]],
        include_document_info: bool = True
    ) -> pd.DataFrame:
        """Convert witness data to a pandas DataFrame"""
        rows = []
        for w in witnesses:
            row = {
                "Witness Name": w.get("full_name", "Unknown"),
                "Role": w.get("role", "").replace("_", " ").title(),
                "Importance": w.get("importance", "LOW"),
                "Observation": w.get("observation", ""),
                "Source Quote": w.get("source_quote", ""),
                "Email": w.get("email", ""),
                "Phone": w.get("phone", ""),
                "Confidence": f"{w.get('confidence_score', 0) * 100:.0f}%"
            }

            if include_document_info:
                row["Source Document"] = w.get("document_filename", "")
                row["Matter"] = w.get("matter_name", "")

            rows.append(row)

        return pd.DataFrame(rows)

    def generate_excel(
        self,
        witnesses: List[Dict[str, Any]],
        matter_name: Optional[str] = None,
        include_document_info: bool = True
    ) -> bytes:
        """
        Generate an Excel file with witness data.

        Returns:
            Excel file as bytes
        """
        df = self.witnesses_to_dataframe(witnesses, include_document_info)

        # Create Excel in memory
        output = io.BytesIO()

        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, sheet_name="Witnesses", index=False)

            workbook = writer.book
            worksheet = writer.sheets["Witnesses"]

            # Formats
            header_format = workbook.add_format({
                "bold": True,
                "bg_color": "#1E3A5F",
                "font_color": "white",
                "border": 1
            })

            high_format = workbook.add_format({
                "bg_color": "#FFE6E6",
                "border": 1
            })

            medium_format = workbook.add_format({
                "bg_color": "#FFF9E6",
                "border": 1
            })

            low_format = workbook.add_format({
                "bg_color": "#E6FFE6",
                "border": 1
            })

            # Apply header format
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)

            # Apply conditional formatting for importance column (only if data exists)
            if len(df) > 0 and "Importance" in df.columns:
                for row_num in range(1, len(df) + 1):
                    importance = df.iloc[row_num - 1]["Importance"]
                    if importance == "HIGH":
                        worksheet.set_row(row_num, None, high_format)
                    elif importance == "MEDIUM":
                        worksheet.set_row(row_num, None, medium_format)
                    else:
                        worksheet.set_row(row_num, None, low_format)

            # Auto-fit columns (only if data exists)
            if len(df) > 0:
                for idx, col in enumerate(df.columns):
                    max_len = max(
                        df[col].astype(str).map(len).max(),
                        len(col)
                    ) + 2
                    worksheet.set_column(idx, idx, min(max_len, 50))

                # Add auto-filter
                worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

        output.seek(0)
        return output.getvalue()

    def generate_pdf(
        self,
        witnesses: List[Dict[str, Any]],
        matter_name: Optional[str] = None,
        matter_number: Optional[str] = None,
        include_cover: bool = True
    ) -> bytes:
        """
        Generate a PDF report with witness data.

        Returns:
            PDF file as bytes
        """
        output = io.BytesIO()

        doc = SimpleDocTemplate(
            output,
            pagesize=landscape(LETTER),
            rightMargin=0.5 * inch,
            leftMargin=0.5 * inch,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch
        )

        elements = []

        # Cover page
        if include_cover:
            elements.extend(self._create_cover_page(matter_name, matter_number))
            elements.append(PageBreak())

        # Witness table
        elements.extend(self._create_witness_table(witnesses))

        doc.build(elements)
        output.seek(0)
        return output.getvalue()

    def _create_cover_page(
        self,
        matter_name: Optional[str],
        matter_number: Optional[str]
    ) -> List:
        """Create the cover page elements"""
        elements = []

        # Title
        elements.append(Spacer(1, 2 * inch))
        elements.append(Paragraph(
            "Witness Summary Report",
            self.styles["CoverTitle"]
        ))

        # Matter info
        if matter_name:
            elements.append(Spacer(1, 0.5 * inch))
            elements.append(Paragraph(
                f"<b>Matter:</b> {matter_name}",
                self.styles["Normal"]
            ))

        if matter_number:
            elements.append(Paragraph(
                f"<b>Matter Number:</b> {matter_number}",
                self.styles["Normal"]
            ))

        # Generated date
        elements.append(Spacer(1, 0.5 * inch))
        elements.append(Paragraph(
            f"<b>Generated:</b> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
            self.styles["Normal"]
        ))

        # Footer
        elements.append(Spacer(1, 2 * inch))
        elements.append(Paragraph(
            "Generated by AI Witness Finder",
            self.styles["Italic"]
        ))

        return elements

    def _create_witness_table(self, witnesses: List[Dict[str, Any]]) -> List:
        """Create the witness data table"""
        elements = []

        # Header
        elements.append(Paragraph(
            "Identified Witnesses",
            self.styles["Heading1"]
        ))
        elements.append(Spacer(1, 0.25 * inch))

        if not witnesses:
            elements.append(Paragraph(
                "No witnesses were identified in the analyzed documents.",
                self.styles["Normal"]
            ))
            return elements

        # Table data
        headers = ["Name", "Role", "Importance", "Observation", "Source", "Contact"]

        data = [headers]

        for w in witnesses:
            # Format observation to fit in cell
            observation = w.get("observation", "") or ""
            if len(observation) > 150:
                observation = observation[:147] + "..."

            # Format contact info
            contact_parts = []
            if w.get("email"):
                contact_parts.append(w["email"])
            if w.get("phone"):
                contact_parts.append(w["phone"])
            contact = "\n".join(contact_parts) if contact_parts else "-"

            row = [
                Paragraph(w.get("full_name", "Unknown"), self.styles["WitnessName"]),
                w.get("role", "").replace("_", " ").title(),
                w.get("importance", "LOW"),
                Paragraph(observation, self.styles["Observation"]),
                w.get("document_filename", "-")[:30],
                Paragraph(contact, self.styles["Normal"])
            ]
            data.append(row)

        # Create table
        col_widths = [1.5 * inch, 1 * inch, 0.8 * inch, 4 * inch, 1.5 * inch, 1.5 * inch]

        table = Table(data, colWidths=col_widths, repeatRows=1)

        # Style the table
        style = TableStyle([
            # Header
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),

            # Body
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ALIGN", (2, 1), (2, -1), "CENTER"),  # Importance centered

            # Grid
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("LINEBELOW", (0, 0), (-1, 0), 2, colors.HexColor("#1E3A5F")),

            # Padding
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ])

        # Add row colors based on importance
        for i, w in enumerate(witnesses, start=1):
            importance = w.get("importance", "LOW")
            if importance == "HIGH":
                style.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FFE6E6"))
            elif importance == "MEDIUM":
                style.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FFF9E6"))
            else:
                style.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#E6FFE6"))

        table.setStyle(style)
        elements.append(table)

        return elements
