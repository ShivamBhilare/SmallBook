"""
PDF Text & Markdown Extraction Service

Converts binary PDF documents into structured Markdown text representations
using PyMuPDF4LLM, preserving headings, tables, bullet points, and code blocks.
"""

import pymupdf4llm


def pdf_extractor(pdf_path: str) -> str:
    """
    Extracts text and layout from a PDF file as Markdown.

    Args:
        pdf_path: Filesystem path to the target PDF file.

    Returns:
        str: Extracted document content formatted as Markdown.
    """
    md_text = pymupdf4llm.to_markdown(pdf_path, show_progress=False)
    return md_text


# Backward-compatibility alias for existing caller imports
pdf_extracter = pdf_extractor