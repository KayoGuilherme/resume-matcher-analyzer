"""Generated resume documents for tests: PDFs from a tiny writer, DOCX from python-docx.

Nothing here is real personal data. PDFs use the standard Helvetica font (no embedding) so no
PDF-writing library is needed.
"""

import io
import re
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

PAGE_WIDTH = 612
PAGE_HEIGHT = 792


@dataclass(frozen=True)
class Text:
    x: float
    y: float  # baseline, measured from the bottom of the page (PDF coordinates)
    text: str
    size: float = 10


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class Page:
    items: tuple[Text | Line, ...] = ()
    image: bool = False  # a full-page image, as in a scanned document


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _content(page: Page) -> bytes:
    parts: list[bytes] = []
    if page.image:
        parts.append(b"q 612 0 0 792 0 0 cm /Im1 Do Q")
    for item in page.items:
        if isinstance(item, Text):
            parts.append(
                f"BT /F1 {item.size} Tf {item.x} {item.y} Td (".encode()
                + _escape(item.text)
                + b") Tj ET"
            )
        else:
            parts.append(f"0.5 w {item.x1} {item.y1} m {item.x2} {item.y2} l S".encode())
    return b"\n".join(parts)


def build_pdf(pages: Sequence[Page]) -> bytes:
    """Return a valid, minimal PDF with the given pages."""
    count = len(pages)
    kids = " ".join(f"{5 + 2 * index} 0 R" for index in range(count))
    gradient = bytes(range(0, 256, 4))  # 8 x 8 grayscale pixels
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray"
        b" /BitsPerComponent 8 /Length 64 >>\nstream\n" + gradient + b"\nendstream",
    ]
    for index, page in enumerate(pages):
        content = _content(page)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}]"
            f" /Resources << /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R >> >>"
            f" /Contents {6 + 2 * index} 0 R >>".encode()
        )
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def _column(x: float, top: float, lines: Sequence[str], step: float = 14) -> list[Text]:
    return [Text(x, top - index * step, line) for index, line in enumerate(lines)]


_EXPERIENCE_BULLETS = (
    "• Designed and built REST APIs in Python and FastAPI for a payments platform.",
    "• Reduced p95 latency from 800 ms to 200 ms by profiling queries and adding indexes.",
    "• Migrated a monolith to services, with PostgreSQL, Docker and a CI/CD pipeline.",
    "• Mentored four junior developers and led weekly code reviews for the whole team.",
    "• Wrote automated tests that raised coverage from 40% to 90% across the code base.",
)


def clean_pdf() -> bytes:
    """One column, standard headings, standard bullets, right-aligned dates, two pages."""
    page_one: list[Text | Line] = [
        Text(72, 720, "Alex Example", 16),
        Text(72, 702, "Backend Developer - alex@example.com - Sao Paulo"),
        Text(72, 670, "Experience", 13),
        Text(72, 650, "Senior Backend Developer, Acme Corp"),
        Text(470, 650, "2021 - 2024"),
        *_column(72, 634, _EXPERIENCE_BULLETS),
        Text(72, 550, "Backend Developer, Globex"),
        Text(470, 550, "2018 - 2021"),
        *_column(72, 534, _EXPERIENCE_BULLETS),
        Text(72, 450, "Junior Developer, Initech"),
        Text(470, 450, "2016 - 2018"),
        *_column(72, 434, _EXPERIENCE_BULLETS[:3]),
    ]
    page_two: list[Text | Line] = [
        Text(72, 720, "Education", 13),
        Text(72, 700, "BSc in Computer Science, State University"),
        Text(470, 700, "2012 - 2016"),
        Text(72, 684, "Graduated with honors; research on distributed systems and databases."),
        Text(72, 640, "Skills", 13),
        *_column(
            72,
            620,
            (
                "• Languages: Python, Go, SQL, TypeScript",
                "• Frameworks: FastAPI, Django, SQLAlchemy, Alembic, pytest",
                "• Infrastructure: PostgreSQL, Docker, GitHub Actions, Linux, AWS",
                "• Practices: code review, test-driven development, observability",
                "• Languages spoken: Portuguese (native), English (fluent)",
            ),
        ),
        *_column(
            72,
            540,
            (
                "I enjoy building reliable systems and explaining technical decisions clearly.",
                "My recent work focuses on data pipelines, API design and developer tooling.",
            ),
        ),
    ]
    return build_pdf([Page(tuple(page_one)), Page(tuple(page_two))])


_LEFT_COLUMN = (
    "Experience",
    "Senior Backend Developer",
    "Acme Corp, 2021 - 2024",
    "Built payment APIs with",
    "Python and FastAPI and",
    "reduced latency by 75%.",
    "Backend Developer",
    "Globex, 2018 - 2021",
    "Migrated a monolith to",
    "services on Docker.",
    "Junior Developer",
    "Initech, 2016 - 2018",
    "Wrote tests and tools",
    "for the platform team.",
)
_RIGHT_COLUMN = (
    "Skills",
    "Python, Go, SQL",
    "FastAPI, Django",
    "PostgreSQL, Docker",
    "GitHub Actions, AWS",
    "Linux, observability",
    "Education",
    "BSc Computer Science",
    "State University",
    "2012 - 2016",
    "Languages",
    "Portuguese (native)",
    "English (fluent)",
    "Open source work",
)


def two_column_pdf() -> bytes:
    """A left column and a right column of text side by side."""
    items = [
        Text(72, 720, "Alex Example", 16),
        *_column(72, 690, _LEFT_COLUMN),
        *_column(340, 690, _RIGHT_COLUMN),
    ]
    return build_pdf([Page(tuple(items))])


def table_pdf() -> bytes:
    """Resume text plus a ruled 3 x 3 table."""
    items: list[Text | Line] = [
        Text(72, 720, "Experience", 13),
        Text(72, 700, "Senior Backend Developer, Acme Corp (2021 - 2024)"),
        Text(72, 660, "Skills", 13),
    ]
    left, right, top, step = 72, 372, 640, 30
    for row in range(4):
        items.append(Line(left, top - row * step, right, top - row * step))
    for col in range(4):
        x = left + col * 100
        items.append(Line(x, top, x, top - 3 * step))
    for row, cells in enumerate((("Language", "Years", "Level"), ("Python", "8", "Expert"))):
        for col, cell in enumerate(cells):
            items.append(Text(left + col * 100 + 6, top - row * step - 20, cell))
    items.append(Text(72, 520, "Education: BSc in Computer Science, State University"))
    return build_pdf([Page(tuple(items))])


def header_footer_pdf() -> bytes:
    """Contact details in the top margin and a page number in the bottom margin."""
    items = [
        Text(72, 775, "alex@example.com | +55 11 99999-0000"),
        Text(72, 740, "Experience", 13),
        Text(72, 720, "Senior Backend Developer, Acme Corp (2021 - 2024)"),
        Text(72, 20, "Page 1 of 1"),
    ]
    return build_pdf([Page(tuple(items))])


def scanned_pdf() -> bytes:
    """Every page is a single image: there is no text layer."""
    return build_pdf([Page(image=True), Page(image=True)])


def many_pages_pdf(count: int) -> bytes:
    """`count` pages with a few lines of text each."""
    pages = [
        Page((Text(72, 700, f"Experience section, page {number}"),))
        for number in range(1, count + 1)
    ]
    return build_pdf(pages)


def fake_pdf() -> bytes:
    """Plain text that would be uploaded with a `.pdf` name."""
    return b"This is not a PDF. It is only a text file with the wrong extension.\n"


def _rewrite_member(data: bytes, name: str, transform: Callable[[str], str]) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == name:
                content = transform(content.decode()).encode()
            target.writestr(item, content)
    return out.getvalue()


def _save(document: "docx.document.Document") -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def with_page_count(data: bytes, pages: int) -> bytes:
    """Set the page count stored in the DOCX properties."""
    return _rewrite_member(
        data,
        "docProps/app.xml",
        lambda xml: re.sub(r"<Pages>\d+</Pages>", f"<Pages>{pages}</Pages>", xml),
    )


def docx_without_page_count() -> bytes:
    """A DOCX whose properties carry no page count."""
    return _rewrite_member(
        clean_docx(), "docProps/app.xml", lambda xml: re.sub(r"<Pages>\d+</Pages>", "", xml)
    )


def clean_docx() -> bytes:
    """Plain paragraphs: standard headings and bullets, no table, header or columns."""
    document = docx.Document()
    document.add_paragraph("Alex Example")
    document.add_paragraph("Experience")
    document.add_paragraph("Senior Backend Developer, Acme Corp, 2021 - 2024")
    for bullet in _EXPERIENCE_BULLETS:
        document.add_paragraph(bullet)
    document.add_paragraph("Education")
    document.add_paragraph("BSc in Computer Science, State University, 2016")
    document.add_paragraph("Skills")
    document.add_paragraph("Python, Go, SQL, FastAPI, PostgreSQL, Docker")
    return _save(document)


def docx_with_table() -> bytes:
    """Paragraph, a 2 x 2 table, then another paragraph."""
    document = docx.Document()
    document.add_paragraph("Before the table")
    table = document.add_table(rows=2, cols=2)
    for row, cells in enumerate((("Language", "Years"), ("Python", "8"))):
        for col, value in enumerate(cells):
            table.cell(row, col).text = value
    document.add_paragraph("After the table")
    return _save(document)


def docx_with_header() -> bytes:
    """Contact details live in the page header."""
    document = docx.Document()
    document.sections[0].header.paragraphs[0].text = "alex@example.com | +55 11 99999-0000"
    document.add_paragraph("Experience")
    document.add_paragraph("Senior Backend Developer, Acme Corp")
    return _save(document)


def two_column_docx() -> bytes:
    """The section is set to two text columns."""
    document = docx.Document()
    columns = OxmlElement("w:cols")
    columns.set(qn("w:num"), "2")
    document.sections[0]._sectPr.append(columns)
    document.add_paragraph("Experience")
    document.add_paragraph("Senior Backend Developer, Acme Corp")
    return _save(document)


def zip_not_docx() -> bytes:
    """A ZIP archive that is not a Word document."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "not a word document")
    return buffer.getvalue()


def blank_docx() -> bytes:
    """A valid DOCX with no text at all."""
    return _save(docx.Document())
