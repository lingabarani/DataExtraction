"""
Enterprise Word (.docx) Documentation Generator
Converts DATA_EXTRACTION_B2B_INTELLIGENCE_PLATFORM_DOCUMENTATION.md into a high-end corporate .docx document.
"""

import os
import re
import sys
from pathlib import Path
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

# Paths
ROOT_DIR = Path(__file__).resolve().parents[2]
MD_PATH = ROOT_DIR / "docs" / "architecture" / "DATA_EXTRACTION_B2B_INTELLIGENCE_PLATFORM_DOCUMENTATION.md"
DOCX_PATH = ROOT_DIR / "docs" / "architecture" / "DATA_EXTRACTION_B2B_INTELLIGENCE_PLATFORM_DOCUMENTATION.docx"

# Color Palette Constants
COLOR_PRIMARY_NAVY = RGBColor(0, 51, 102)     # #003366
COLOR_SECONDARY_SLATE = RGBColor(43, 84, 126) # #2B547E
COLOR_TEAL_ACCENT = RGBColor(0, 128, 128)     # #008080
COLOR_BODY_TEXT = RGBColor(51, 51, 51)        # #333333
COLOR_MUTED_GRAY = RGBColor(119, 119, 119)    # #777777
HEX_HEADER_BG = "003366"
HEX_ROW_ALT_BG = "F4F7F9"
HEX_CODE_BG = "F5F6F8"
HEX_BORDER_GRAY = "D3D3D3"
HEX_PRIMARY_BORDER = "003366"


def set_cell_background(cell, hex_color: str):
    """Sets background shading color for a table cell."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tc_pr.append(shd)


def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Sets cell padding in twentieths of a point (dxa)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tc_pr.append(tc_mar)


def set_table_borders(table, hex_color=HEX_BORDER_GRAY):
    """Applies clean subtle borders to a table."""
    tbl_pr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{hex_color}"/>'
        f'<w:bottom w:val="single" w:sz="6" w:space="0" w:color="{HEX_PRIMARY_BORDER}"/>'
        f'<w:left w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{hex_color}"/>'
        f'<w:insideV w:val="none"/>'
        f'</w:tblBorders>'
    )
    tbl_pr.append(borders)


def add_callout_box(doc, text: str, title: str = "TECHNICAL SPECIFICATION"):
    """Creates an enterprise callout / code block container with a thick primary left border."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False

    cell = tbl.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, HEX_CODE_BG)
    set_cell_margins(cell, top=120, bottom=120, left=200, right=150)

    # Left border only
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="24" w:space="0" w:color="{HEX_PRIMARY_BORDER}"/>'
        f'<w:top w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'<w:bottom w:val="none"/>'
        f'</w:tcBorders>'
    )
    tc_pr.append(tc_borders)

    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.05

    run_title = p.add_run(f"[{title}]\n")
    run_title.font.name = "Segoe UI"
    run_title.font.size = Pt(8.5)
    run_title.font.bold = True
    run_title.font.color.rgb = COLOR_PRIMARY_NAVY

    run_body = p.add_run(text.strip())
    run_body.font.name = "Consolas"
    run_body.font.size = Pt(8.5)
    run_body.font.color.rgb = COLOR_BODY_TEXT

    # Spacer after callout
    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(0)
    p_after.paragraph_format.space_after = Pt(4)


def add_formatted_text(paragraph, text: str):
    """Parses inline bold, italic, code, and links in markdown text."""
    # Pattern to match bold, italic, code, or math
    tokens = re.split(r'(\*\*.*?\*\*|\*.*?\*|`.*?`|\$\$.*?\$\$|\$.*?\$)', text)
    for token in tokens:
        if not token:
            continue
        if token.startswith('**') and token.endswith('**') and len(token) >= 4:
            run = paragraph.add_run(token[2:-2])
            run.font.bold = True
            run.font.name = "Calibri"
            run.font.color.rgb = COLOR_BODY_TEXT
        elif token.startswith('*') and token.endswith('*') and len(token) >= 2:
            run = paragraph.add_run(token[1:-1])
            run.font.italic = True
            run.font.name = "Calibri"
            run.font.color.rgb = COLOR_BODY_TEXT
        elif token.startswith('`') and token.endswith('`') and len(token) >= 2:
            run = paragraph.add_run(token[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
            run.font.color.rgb = COLOR_PRIMARY_NAVY
        elif (token.startswith('$$') and token.endswith('$$')) or (token.startswith('$') and token.endswith('$')):
            math_content = token.strip('$')
            run = paragraph.add_run(f" {math_content} ")
            run.font.italic = True
            run.font.name = "Cambria Math"
            run.font.color.rgb = COLOR_PRIMARY_NAVY
        else:
            run = paragraph.add_run(token)
            run.font.name = "Calibri"
            run.font.color.rgb = COLOR_BODY_TEXT


def render_markdown_table(doc, table_lines: list):
    """Renders a parsed markdown table into a styled python-docx table."""
    if not table_lines or len(table_lines) < 2:
        return

    # Parse header
    header_raw = [c.strip() for c in table_lines[0].strip().strip('|').split('|')]
    # Skip separator line (line 1)
    rows_data = []
    for line in table_lines[2:]:
        if not line.strip() or not '|' in line:
            continue
        row = [c.strip() for c in line.strip().strip('|').split('|')]
        # Ensure row length matches header
        while len(row) < len(header_raw):
            row.append("")
        rows_data.append(row[:len(header_raw)])

    table = doc.add_table(rows=len(rows_data) + 1, cols=len(header_raw))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    set_table_borders(table)

    # Style Header Row
    header_row = table.rows[0]
    # Set cantSplit and tblHeader
    tr_pr = header_row._tr.get_or_add_trPr()
    tr_pr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
    tr_pr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))

    for i, col_title in enumerate(header_raw):
        cell = header_row.cells[i]
        set_cell_background(cell, HEX_HEADER_BG)
        set_cell_margins(cell, top=140, bottom=140, left=150, right=150)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(col_title)
        run.font.name = "Segoe UI"
        run.font.bold = True
        run.font.size = Pt(9.5)
        run.font.color.rgb = RGBColor(255, 255, 255)

    # Style Data Rows
    for r_idx, row_items in enumerate(rows_data):
        row = table.rows[r_idx + 1]
        tr_pr = row._tr.get_or_add_trPr()
        tr_pr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
        is_alt = (r_idx % 2 == 1)
        bg_color = HEX_ROW_ALT_BG if is_alt else "FFFFFF"

        for c_idx, cell_value in enumerate(row_items):
            cell = row.cells[c_idx]
            set_cell_background(cell, bg_color)
            set_cell_margins(cell, top=100, bottom=100, left=150, right=150)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.line_spacing = 1.1
            add_formatted_text(p, cell_value)

    # Spacing after table
    p_spacer = doc.add_paragraph()
    p_spacer.paragraph_format.space_before = Pt(0)
    p_spacer.paragraph_format.space_after = Pt(6)


def build_cover_page(doc):
    """Builds a formal executive title cover page."""
    # Top spacing
    p_top = doc.add_paragraph()
    p_top.paragraph_format.space_before = Pt(40)
    p_top.paragraph_format.space_after = Pt(10)

    # Super-title / Org Badge
    p_badge = doc.add_paragraph()
    run_badge = p_badge.add_run("ENTERPRISE SOLUTION ARCHITECTURE SPECIFICATION")
    run_badge.font.name = "Segoe UI"
    run_badge.font.size = Pt(11)
    run_badge.font.bold = True
    run_badge.font.color.rgb = COLOR_TEAL_ACCENT
    p_badge.paragraph_format.space_after = Pt(16)

    # Main Document Title
    p_title = doc.add_paragraph()
    run_title = p_title.add_run("Data Extraction B2B\nIntelligence Platform")
    run_title.font.name = "Segoe UI"
    run_title.font.size = Pt(30)
    run_title.font.bold = True
    run_title.font.color.rgb = COLOR_PRIMARY_NAVY
    p_title.paragraph_format.space_after = Pt(12)
    p_title.paragraph_format.line_spacing = 1.05

    # Subtitle
    p_sub = doc.add_paragraph()
    run_sub = p_sub.add_run(
        "Complete Enterprise Architectural Specification, System Design, "
        "Multi-Agent Orchestration & Client Handover Documentation"
    )
    run_sub.font.name = "Segoe UI"
    run_sub.font.size = Pt(13)
    run_sub.font.color.rgb = COLOR_SECONDARY_SLATE
    p_sub.paragraph_format.space_after = Pt(40)

    # Horizontal Divider Line (Table)
    div_table = doc.add_table(rows=1, cols=1)
    div_cell = div_table.cell(0, 0)
    div_cell.width = Inches(6.5)
    set_cell_background(div_cell, HEX_PRIMARY_BORDER)
    div_cell.paragraphs[0].paragraph_format.space_before = Pt(1)
    div_cell.paragraphs[0].paragraph_format.space_after = Pt(1)
    p_div_spacer = doc.add_paragraph()
    p_div_spacer.paragraph_format.space_after = Pt(30)

    # Metadata Summary Table
    meta_table = doc.add_table(rows=6, cols=2)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_table.autofit = False
    set_table_borders(meta_table)

    meta_items = [
        ("Document Reference:", "DEX-ARCH-DOC-2026-V5.0"),
        ("Classification:", "Enterprise Confidential / Client Technical Architecture"),
        ("System Target:", "OneReach B2B Intelligence Integration Platform"),
        ("Architectural Authority:", "Principal Solution Architect & Staff Platform Engineer"),
        ("Production Certification:", "V5.0.0 — Certified Complete (329/329 Tests Passing)"),
        ("Publication Date:", "October 2026"),
    ]

    for idx, (label, val) in enumerate(meta_items):
        row = meta_table.rows[idx]
        cell_lbl = row.cells[0]
        cell_val = row.cells[1]
        cell_lbl.width = Inches(2.2)
        cell_val.width = Inches(4.3)

        set_cell_background(cell_lbl, HEX_ROW_ALT_BG)
        set_cell_background(cell_val, "FFFFFF")
        set_cell_margins(cell_lbl, top=80, bottom=80, left=120, right=100)
        set_cell_margins(cell_val, top=80, bottom=80, left=120, right=100)

        p_lbl = cell_lbl.paragraphs[0]
        p_lbl.paragraph_format.space_before = Pt(1)
        p_lbl.paragraph_format.space_after = Pt(1)
        run_l = p_lbl.add_run(label)
        run_l.font.name = "Segoe UI"
        run_l.font.bold = True
        run_l.font.size = Pt(9.5)
        run_l.font.color.rgb = COLOR_PRIMARY_NAVY

        p_val = cell_val.paragraphs[0]
        p_val.paragraph_format.space_before = Pt(1)
        p_val.paragraph_format.space_after = Pt(1)
        run_v = p_val.add_run(val)
        run_v.font.name = "Calibri"
        run_v.font.size = Pt(9.5)
        run_v.font.color.rgb = COLOR_BODY_TEXT

    # Page Break after Cover Page
    doc.add_page_break()


def convert_markdown_to_docx():
    print(f"[1/4] Reading Markdown: {MD_PATH}")
    if not MD_PATH.exists():
        print(f"ERROR: File not found at {MD_PATH}")
        sys.exit(1)

    content = MD_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    print("[2/4] Initializing Word Document with Corporate Styling...")
    doc = Document()

    # Configure Margins: 1 inch (72pt)
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

        # Header Setup
        header = section.header
        p_head = header.paragraphs[0]
        p_head.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_head = p_head.add_run("Data Extraction B2B Intelligence Platform — Architecture & Handover")
        r_head.font.name = "Segoe UI"
        r_head.font.size = Pt(8.5)
        r_head.font.color.rgb = COLOR_MUTED_GRAY

        # Footer Setup
        footer = section.footer
        p_foot = footer.paragraphs[0]
        p_foot.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_foot = p_foot.add_run("Confidential — Enterprise Platform Architecture | DEX-V5.0")
        r_foot.font.name = "Segoe UI"
        r_foot.font.size = Pt(8.5)
        r_foot.font.color.rgb = COLOR_MUTED_GRAY

    # Build Cover Page
    build_cover_page(doc)

    print("[3/4] Parsing & Transforming Content...")
    in_code_block = False
    code_block_lang = ""
    code_block_lines = []

    in_table = False
    table_lines = []

    line_idx = 0
    total_lines = len(lines)

    # Skip initial title line from MD as it was generated in cover page
    start_parsing = False

    while line_idx < total_lines:
        line = lines[line_idx]
        stripped = line.strip()

        # Start parsing when first Heading 1 appears
        if stripped.startswith("# 1. Executive Summary") or stripped.startswith("# Table of Contents"):
            start_parsing = True

        if not start_parsing:
            line_idx += 1
            continue

        # Check for Fenced Code Block delimiters
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_block_lang = stripped[3:].strip()
                code_block_lines = []
            else:
                in_code_block = False
                title_label = f"CODE / DIAGRAM: {code_block_lang.upper()}" if code_block_lang else "TECHNICAL SPECIFICATION"
                add_callout_box(doc, "\n".join(code_block_lines), title=title_label)
                code_block_lines = []
            line_idx += 1
            continue

        if in_code_block:
            code_block_lines.append(line)
            line_idx += 1
            continue

        # Check for Markdown Table Rows
        if stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                in_table = True
                table_lines = [stripped]
            else:
                table_lines.append(stripped)
            line_idx += 1
            continue
        else:
            if in_table:
                in_table = False
                render_markdown_table(doc, table_lines)
                table_lines = []

        # Empty line
        if not stripped:
            line_idx += 1
            continue

        # Headings
        if stripped.startswith("# "):
            heading_text = stripped[2:].strip()
            # Add Page Break before each major chapter (except TOC)
            if not heading_text.startswith("Table of Contents"):
                doc.add_page_break()

            h1 = doc.add_paragraph()
            h1.paragraph_format.space_before = Pt(18)
            h1.paragraph_format.space_after = Pt(8)
            h1.paragraph_format.keep_with_next = True
            r1 = h1.add_run(heading_text)
            r1.font.name = "Segoe UI"
            r1.font.size = Pt(18)
            r1.font.bold = True
            r1.font.color.rgb = COLOR_PRIMARY_NAVY

        elif stripped.startswith("## "):
            heading_text = stripped[3:].strip()
            h2 = doc.add_paragraph()
            h2.paragraph_format.space_before = Pt(14)
            h2.paragraph_format.space_after = Pt(6)
            h2.paragraph_format.keep_with_next = True
            r2 = h2.add_run(heading_text)
            r2.font.name = "Segoe UI"
            r2.font.size = Pt(14)
            r2.font.bold = True
            r2.font.color.rgb = COLOR_SECONDARY_SLATE

        elif stripped.startswith("### "):
            heading_text = stripped[4:].strip()
            h3 = doc.add_paragraph()
            h3.paragraph_format.space_before = Pt(10)
            h3.paragraph_format.space_after = Pt(4)
            h3.paragraph_format.keep_with_next = True
            r3 = h3.add_run(heading_text)
            r3.font.name = "Segoe UI"
            r3.font.size = Pt(11.5)
            r3.font.bold = True
            r3.font.color.rgb = COLOR_TEAL_ACCENT

        elif stripped.startswith("#### "):
            heading_text = stripped[5:].strip()
            h4 = doc.add_paragraph()
            h4.paragraph_format.space_before = Pt(8)
            h4.paragraph_format.space_after = Pt(3)
            h4.paragraph_format.keep_with_next = True
            r4 = h4.add_run(heading_text)
            r4.font.name = "Segoe UI"
            r4.font.size = Pt(10.5)
            r4.font.bold = True
            r4.font.color.rgb = COLOR_BODY_TEXT

        # Bullet List Item
        elif stripped.startswith("- ") or stripped.startswith("* "):
            p_bullet = doc.add_paragraph(style='List Bullet')
            p_bullet.paragraph_format.space_before = Pt(1)
            p_bullet.paragraph_format.space_after = Pt(2)
            p_bullet.paragraph_format.line_spacing = 1.15
            add_formatted_text(p_bullet, stripped[2:])

        # Numbered List Item
        elif re.match(r'^\d+\.\s', stripped):
            item_text = re.sub(r'^\d+\.\s', '', stripped)
            p_num = doc.add_paragraph(style='List Number')
            p_num.paragraph_format.space_before = Pt(1)
            p_num.paragraph_format.space_after = Pt(2)
            p_num.paragraph_format.line_spacing = 1.15
            add_formatted_text(p_num, item_text)

        # Standard Paragraph
        else:
            p_body = doc.add_paragraph()
            p_body.paragraph_format.space_before = Pt(2)
            p_body.paragraph_format.space_after = Pt(5)
            p_body.paragraph_format.line_spacing = 1.15
            add_formatted_text(p_body, stripped)

        line_idx += 1

    # Close any trailing table
    if in_table and table_lines:
        render_markdown_table(doc, table_lines)

    print(f"[4/4] Saving output Word document: {DOCX_PATH}")
    doc.save(str(DOCX_PATH))
    size_bytes = DOCX_PATH.stat().st_size
    print(f"SUCCESS: Document created ({size_bytes:,} bytes, {size_bytes / 1024:.1f} KB)")


if __name__ == "__main__":
    convert_markdown_to_docx()

