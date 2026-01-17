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

    def _format_witness_info(self, w: Dict[str, Any]) -> str:
        """Format witness info combining name, role, and contact"""
        name = w.get("full_name", "Unknown")
        role = w.get("role", "").replace("_", " ").title()

        # Format contact info
        contact_parts = []
        if w.get("address"):
            contact_parts.append(w["address"])
        if w.get("phone"):
            contact_parts.append(w["phone"])
        if w.get("email"):
            contact_parts.append(w["email"])

        if contact_parts:
            contact_str = ", ".join(contact_parts)
        else:
            contact_str = "Contact info unknown at this time"

        return f"{name}, {role}, {contact_str}"

    def _format_source_document(self, w: Dict[str, Any]) -> str:
        """Format source document with page number if available"""
        source_doc = w.get("document_filename", "") or ""
        source_page = w.get("source_page")
        if source_page:
            source_doc = f"{source_doc} (Page {source_page})"
        return source_doc

    def witnesses_to_dataframe(
        self,
        witnesses: List[Dict[str, Any]],
        include_document_info: bool = True
    ) -> pd.DataFrame:
        """
        Convert witness data to a pandas DataFrame.
        Structure matches PDF: Witness Info, Importance, Confidence, Observation, Source Summary, Source Document
        """
        # Sort witnesses by importance: HIGH first, then MEDIUM, then LOW
        importance_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        sorted_witnesses = sorted(
            witnesses,
            key=lambda w: importance_order.get(w.get("importance", "LOW").upper(), 3)
        )

        # Group witnesses by name to handle multiple observations
        from collections import OrderedDict
        witness_groups = OrderedDict()
        for w in sorted_witnesses:
            name = w.get("full_name", "Unknown")
            if name not in witness_groups:
                witness_groups[name] = []
            witness_groups[name].append(w)

        rows = []
        for witness_name, observations in witness_groups.items():
            first_obs = observations[0]

            if len(observations) == 1:
                # Single observation - show everything in one row
                w = observations[0]
                row = {
                    "Witness Info": self._format_witness_info(w),
                    "Importance": w.get("importance", "LOW"),
                    "Confidence": f"{w.get('confidence_score', 0) * 100:.0f}%",
                    "Observation": w.get("observation", "") or "",
                    "Source Summary": w.get("source_quote", "") or "",
                    "Source Document": self._format_source_document(w)
                }
                rows.append(row)
            else:
                # Multiple observations - first row is summary
                all_observations = [w.get("observation", "") or "" for w in observations]
                summary_observation = "Multiple observations: " + "; ".join(
                    [obs[:100] + "..." if len(obs) > 100 else obs for obs in all_observations if obs]
                )

                summary_row = {
                    "Witness Info": self._format_witness_info(first_obs),
                    "Importance": first_obs.get("importance", "LOW"),
                    "Confidence": f"{first_obs.get('confidence_score', 0) * 100:.0f}%",
                    "Observation": summary_observation,
                    "Source Summary": "See Below",
                    "Source Document": "See Below"
                }
                rows.append(summary_row)

                # Subsequent rows - individual observations
                for w in observations:
                    row = {
                        "Witness Info": "",  # Blank for continuation rows
                        "Importance": "",
                        "Confidence": "",
                        "Observation": w.get("observation", "") or "",
                        "Source Summary": w.get("source_quote", "") or "",
                        "Source Document": self._format_source_document(w)
                    }
                    rows.append(row)

        return pd.DataFrame(rows)

    def generate_excel(
        self,
        witnesses: List[Dict[str, Any]],
        matter_name: Optional[str] = None,
        matter_number: Optional[str] = None,
        firm_name: Optional[str] = None,
        generated_by: Optional[str] = None,
        include_document_info: bool = True
    ) -> bytes:
        """
        Generate an Excel file with witness data.
        Structure matches PDF: Witness Info, Importance, Confidence, Observation, Source Summary, Source Document

        Returns:
            Excel file as bytes
        """
        df = self.witnesses_to_dataframe(witnesses, include_document_info)

        # Create Excel in memory
        output = io.BytesIO()

        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            # Start data at row 6 to leave room for header info
            header_row_start = 6
            df.to_excel(writer, sheet_name="Witnesses", index=False, startrow=header_row_start)

            workbook = writer.book
            worksheet = writer.sheets["Witnesses"]

            # Formats
            title_format = workbook.add_format({
                "bold": True,
                "font_size": 18,
                "font_color": "#1E3A5F"
            })

            info_format = workbook.add_format({
                "bold": True,
                "font_size": 11
            })

            info_value_format = workbook.add_format({
                "font_size": 11
            })

            header_format = workbook.add_format({
                "bold": True,
                "bg_color": "#1E3A5F",
                "font_color": "white",
                "border": 1,
                "text_wrap": True,
                "valign": "vcenter"
            })

            high_format = workbook.add_format({
                "bg_color": "#FFE6E6",
                "border": 1,
                "text_wrap": True,
                "valign": "top"
            })

            medium_format = workbook.add_format({
                "bg_color": "#FFF9E6",
                "border": 1,
                "text_wrap": True,
                "valign": "top"
            })

            low_format = workbook.add_format({
                "bg_color": "#E6FFE6",
                "border": 1,
                "text_wrap": True,
                "valign": "top"
            })

            continuation_format = workbook.add_format({
                "bg_color": "#F5F5F5",
                "border": 1,
                "text_wrap": True,
                "valign": "top"
            })

            # Write header information
            worksheet.write(0, 0, "Witness Summary Report", title_format)

            row = 1
            if firm_name:
                worksheet.write(row, 0, f"Firm: {firm_name}", info_format)
                row += 1

            if matter_name:
                matter_display = matter_name
                if matter_number and matter_number != matter_name:
                    matter_display = f"{matter_number} - {matter_name}"
                worksheet.write(row, 0, f"Matter: {matter_display}", info_format)
                row += 1

            if generated_by:
                worksheet.write(row, 0, f"Generated by: {generated_by}", info_format)
                row += 1

            worksheet.write(row, 0, f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", info_format)

            # Apply header format to column headers
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(header_row_start, col_num, value, header_format)

            # Track importance for row coloring
            # We need to track which witness each row belongs to for proper coloring
            if len(df) > 0:
                current_importance = None
                for row_num in range(len(df)):
                    excel_row = header_row_start + 1 + row_num
                    importance = df.iloc[row_num]["Importance"]
                    witness_info = df.iloc[row_num]["Witness Info"]

                    # If this is a new witness row (has witness info), update importance
                    if witness_info:
                        current_importance = importance

                    # Apply formatting based on importance
                    if current_importance == "HIGH":
                        row_format = high_format
                    elif current_importance == "MEDIUM":
                        row_format = medium_format
                    elif current_importance == "LOW":
                        row_format = low_format
                    else:
                        row_format = continuation_format

                    # Write each cell with the appropriate format
                    for col_num, col_name in enumerate(df.columns):
                        value = df.iloc[row_num][col_name]
                        worksheet.write(excel_row, col_num, value, row_format)

            # Set column widths - matching PDF proportions
            # Witness Info, Importance, Confidence, Observation, Source Summary, Source Document
            col_widths = [35, 12, 12, 45, 35, 30]
            for idx, width in enumerate(col_widths):
                if idx < len(df.columns):
                    worksheet.set_column(idx, idx, width)

            # Set row height for data rows to accommodate text wrapping
            # Calculate row height based on content length (estimate ~15 chars per line at font size 10)
            if len(df) > 0:
                for row_num in range(len(df)):
                    # Get the max text length in wrappable columns (Observation, Source Summary)
                    obs_text = str(df.iloc[row_num].get("Observation", "") or "")
                    summary_text = str(df.iloc[row_num].get("Source Summary", "") or "")

                    # Estimate lines needed (col width ~40 chars for observation, ~30 for summary)
                    obs_lines = max(1, len(obs_text) // 50 + 1)
                    summary_lines = max(1, len(summary_text) // 40 + 1)
                    max_lines = max(obs_lines, summary_lines)

                    # Set row height: 15 points per line, minimum 30, maximum 200
                    row_height = min(200, max(30, max_lines * 15))
                    worksheet.set_row(header_row_start + 1 + row_num, row_height)

            # Add auto-filter
            if len(df) > 0:
                worksheet.autofilter(header_row_start, 0, header_row_start + len(df), len(df.columns) - 1)

            # Freeze panes - freeze header row
            worksheet.freeze_panes(header_row_start + 1, 0)

        output.seek(0)
        return output.getvalue()

    def generate_pdf(
        self,
        witnesses: List[Dict[str, Any]],
        matter_name: Optional[str] = None,
        matter_number: Optional[str] = None,
        firm_name: Optional[str] = None,
        generated_by: Optional[str] = None,
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
            elements.extend(self._create_cover_page(
                matter_name, matter_number, firm_name, generated_by
            ))
            elements.append(PageBreak())

        # Witness table
        elements.extend(self._create_witness_table(witnesses))

        doc.build(elements)
        output.seek(0)
        return output.getvalue()

    def _create_cover_page(
        self,
        matter_name: Optional[str],
        matter_number: Optional[str],
        firm_name: Optional[str] = None,
        generated_by: Optional[str] = None
    ) -> List:
        """Create the cover page elements"""
        elements = []

        # Firm name at top if provided
        if firm_name:
            elements.append(Spacer(1, 0.5 * inch))
            elements.append(Paragraph(
                firm_name,
                self.styles["Heading2"]
            ))
            elements.append(Spacer(1, 1 * inch))
        else:
            elements.append(Spacer(1, 2 * inch))

        # Title
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

        # Generated by and date
        elements.append(Spacer(1, 0.5 * inch))
        if generated_by:
            elements.append(Paragraph(
                f"<b>Generated by:</b> {generated_by}",
                self.styles["Normal"]
            ))
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

        # Sort witnesses by importance: HIGH first, then MEDIUM, then LOW
        importance_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        sorted_witnesses = sorted(
            witnesses,
            key=lambda w: importance_order.get(w.get("importance", "LOW").upper(), 3)
        )

        # Group witnesses by name to handle multiple observations
        from collections import OrderedDict
        witness_groups = OrderedDict()
        for w in sorted_witnesses:
            name = w.get("full_name", "Unknown")
            if name not in witness_groups:
                witness_groups[name] = []
            witness_groups[name].append(w)

        # Table headers - new structure
        headers = ["Witness Info", "Importance", "Confidence", "Observation", "Source Summary", "Source Document"]

        data = [headers]

        for witness_name, observations in witness_groups.items():
            first_obs = observations[0]

            # Build witness info: Name, Role, Contact
            name = first_obs.get("full_name", "Unknown")
            role = first_obs.get("role", "").replace("_", " ").title()

            # Format contact info
            contact_parts = []
            if first_obs.get("address"):
                contact_parts.append(first_obs["address"])
            if first_obs.get("phone"):
                contact_parts.append(first_obs["phone"])
            if first_obs.get("email"):
                contact_parts.append(first_obs["email"])

            if contact_parts:
                contact_str = ", ".join(contact_parts)
            else:
                contact_str = "Contact info unknown at this time"

            # Combined witness info
            witness_info = f"{name}, {role}, {contact_str}"

            # Handle single vs multiple observations differently
            if len(observations) == 1:
                # Single observation - show everything in one row
                w = observations[0]
                observation = w.get("observation", "") or ""
                source_summary = w.get("source_quote", "") or ""

                source_doc = w.get("document_filename", "") or ""
                source_page = w.get("source_page")
                if source_page:
                    source_doc = f"{source_doc} (Page {source_page})"

                confidence = f"{w.get('confidence_score', 0) * 100:.0f}%"

                row = [
                    Paragraph(witness_info, self.styles["Observation"]),
                    w.get("importance", "LOW"),
                    confidence,
                    Paragraph(observation, self.styles["Observation"]),
                    Paragraph(source_summary, self.styles["Observation"]),
                    Paragraph(source_doc, self.styles["Observation"])
                ]
                data.append(row)
            else:
                # Multiple observations
                # First row: summary of all observations with "See Below"
                all_observations = [w.get("observation", "") or "" for w in observations]
                summary_observation = "Multiple observations: " + "; ".join(
                    [obs[:100] + "..." if len(obs) > 100 else obs for obs in all_observations if obs]
                )

                first_w = observations[0]
                confidence = f"{first_w.get('confidence_score', 0) * 100:.0f}%"

                summary_row = [
                    Paragraph(witness_info, self.styles["Observation"]),
                    first_w.get("importance", "LOW"),
                    confidence,
                    Paragraph(summary_observation, self.styles["Observation"]),
                    "See Below",
                    "See Below"
                ]
                data.append(summary_row)

                # Subsequent rows - individual observations
                for w in observations:
                    observation = w.get("observation", "") or ""
                    source_summary = w.get("source_quote", "") or ""

                    source_doc = w.get("document_filename", "") or ""
                    source_page = w.get("source_page")
                    if source_page:
                        source_doc = f"{source_doc} (Page {source_page})"

                    row = [
                        "",  # Witness Info
                        "",  # Importance
                        "",  # Confidence
                        Paragraph(observation, self.styles["Observation"]),
                        Paragraph(source_summary, self.styles["Observation"]),
                        Paragraph(source_doc, self.styles["Observation"])
                    ]
                    data.append(row)

        # Create table - adjusted column widths for 6 columns
        # Landscape LETTER = 11" wide, minus 1" margins = 10" available
        # Balance widths to prevent squished columns
        col_widths = [2.0 * inch, 0.85 * inch, 0.85 * inch, 2.5 * inch, 2.0 * inch, 1.8 * inch]

        table = Table(data, colWidths=col_widths, repeatRows=1, splitByRow=True)

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
            ("ALIGN", (1, 1), (1, -1), "CENTER"),  # Importance centered (column 1)
            ("ALIGN", (2, 1), (2, -1), "CENTER"),  # Confidence centered (column 2)

            # Grid
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("LINEBELOW", (0, 0), (-1, 0), 2, colors.HexColor("#1E3A5F")),

            # Padding
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ])

        # Add row colors based on importance - track which rows belong to which witness
        row_num = 1
        for witness_name, observations in witness_groups.items():
            importance = observations[0].get("importance", "LOW").upper()
            # Calculate number of rows for this witness
            if len(observations) == 1:
                num_rows = 1
            else:
                num_rows = 1 + len(observations)  # Summary row + individual rows

            for _ in range(num_rows):
                if importance == "HIGH":
                    style.add("BACKGROUND", (0, row_num), (-1, row_num), colors.HexColor("#FFE6E6"))
                elif importance == "MEDIUM":
                    style.add("BACKGROUND", (0, row_num), (-1, row_num), colors.HexColor("#FFF9E6"))
                else:
                    style.add("BACKGROUND", (0, row_num), (-1, row_num), colors.HexColor("#E6FFE6"))
                row_num += 1

        table.setStyle(style)
        elements.append(table)

        return elements
