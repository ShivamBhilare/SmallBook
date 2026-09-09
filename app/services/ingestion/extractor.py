import pymupdf4llm

def pdf_extractor(pdf_path: str) -> str:
    """Extract text from a PDF file in markdown format."""
    md_text = pymupdf4llm.to_markdown(pdf_path, show_progress=False)
    return md_text

# Backward-compatibility alias
pdf_extracter = pdf_extractor