"""
IRIS Diagnostic Reporting Engine.
Generates comprehensive reports in HTML, PDF, and JPEG formats with plain-English guides
and engineering compliance tables.
"""

from reports.generator import (
    generate_html_report,
    generate_pdf_report,
    generate_jpeg_report,
    save_report_snapshot,
    list_saved_reports,
)

__all__ = [
    "generate_html_report",
    "generate_pdf_report",
    "generate_jpeg_report",
    "save_report_snapshot",
    "list_saved_reports",
]
