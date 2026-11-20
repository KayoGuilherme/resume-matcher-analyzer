"""DOCX to text: body paragraphs and table cells in document order."""

import io
import re
import zipfile
from importlib.metadata import version

import docx
from docx.document import Document
from docx.oxml.ns import qn
from docx.section import Section
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ai.parsing.detect import exceeds_uncompressed_limit
from app.ai.parsing.models import ParsedDocument, UnreadableDocumentError

_PAGES = re.compile(rb"<Pages>\s*(\d+)\s*</Pages>")
_APP_PROPERTIES_READ_LIMIT = 64 * 1024  # no XML parser on untrusted input: a bounded regex


def _body(document: Document) -> tuple[list[str], int]:
    """Return the body text parts in order and the number of tables."""
    parts: list[str] = []
    tables = 0
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            parts.append(Paragraph(child, document).text)
        elif child.tag == qn("w:tbl"):
            tables += 1
            table = Table(child, document)
            parts.extend("\t".join(cell.text for cell in row.cells) for row in table.rows)
    return parts, tables


def _has_header_footer_text(sections: list[Section]) -> bool:
    for section in sections:
        parts = (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        )
        for part in parts:
            # Linked parts inherit from a previous section (already inspected).
            if not part.is_linked_to_previous and any(p.text.strip() for p in part.paragraphs):
                return True
    return False


def _has_columns(sections: list[Section]) -> bool:
    for section in sections:
        for count in section._sectPr.xpath("./w:cols/@w:num"):
            if int(count) > 1:
                return True
    return False


def _page_count(data: bytes) -> int | None:
    """Pages as stored in the document properties (None when absent)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if "docProps/app.xml" not in archive.namelist():
            return None
        with archive.open("docProps/app.xml") as properties:
            match = _PAGES.search(properties.read(_APP_PROPERTIES_READ_LIMIT))
    pages = int(match.group(1)) if match else 0
    return pages or None


def parse_docx(data: bytes) -> ParsedDocument:
    """Extract text and layout facts. Any library failure becomes `UnreadableDocumentError`."""
    if exceeds_uncompressed_limit(data):
        raise UnreadableDocumentError()
    try:
        document = docx.Document(io.BytesIO(data))
        parts, tables = _body(document)
        sections = list(document.sections)
        header_footer = _has_header_footer_text(sections)
        multi_column = _has_columns(sections)
        pages = _page_count(data)
    except Exception:
        # `from None`: library messages can quote document content.
        raise UnreadableDocumentError() from None
    return ParsedDocument(
        file_type="docx",
        text="\n".join(parts),
        page_count=pages,
        parser=f"python-docx {version('python-docx')}",
        table_count=tables,
        multi_column=multi_column,
        header_footer_text=header_footer,
    )
