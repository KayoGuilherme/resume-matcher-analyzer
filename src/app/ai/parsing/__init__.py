"""Turn uploaded PDF/DOCX bytes into text, document facts and a quality report."""

from app.ai.parsing.docx import parse_docx
from app.ai.parsing.models import FileType, ParsedDocument
from app.ai.parsing.pdf import parse_pdf


def parse_document(data: bytes, file_type: FileType) -> ParsedDocument:
    """Parse with the extractor for this type (CPU-bound: call it from a threadpool)."""
    if file_type == "pdf":
        return parse_pdf(data)
    return parse_docx(data)
