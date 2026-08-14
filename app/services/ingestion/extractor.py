import pymupdf4llm

def pdf_extracter(pdf_path: str) -> str:
    """Extract text from a PDF file in markdown format."""
    md_text = pymupdf4llm.to_markdown(pdf_path, show_progress=False)
    return md_text