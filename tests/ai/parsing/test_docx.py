import io
import zipfile

import pytest

from app.ai.parsing import detect, parse_document
from app.ai.parsing.docx import parse_docx
from app.ai.parsing.models import UnreadableDocumentError
from tests.fixtures import documents


def test_clean_docx_text_and_flags() -> None:
    document = parse_docx(documents.clean_docx())

    assert document.file_type == "docx"
    assert document.text.index("Experience") < document.text.index("Education")
    assert document.text.index("Education") < document.text.index("Skills")
    assert document.table_count == 0
    assert not document.multi_column
    assert not document.header_footer_text
    assert document.image_count == 0
    assert document.parser.startswith("python-docx ")


def test_paragraph_table_paragraph_keep_their_order() -> None:
    document = parse_docx(documents.docx_with_table())

    assert document.text.splitlines() == [
        "Before the table",
        "Language\tYears",
        "Python\t8",
        "After the table",
    ]
    assert document.table_count == 1


def test_header_text_is_flagged_and_not_part_of_the_text() -> None:
    document = parse_docx(documents.docx_with_header())

    assert document.header_footer_text
    assert "alex@example.com" not in document.text
    assert "Experience" in document.text


def test_two_column_section_is_flagged() -> None:
    assert parse_docx(documents.two_column_docx()).multi_column


def test_page_count_comes_from_the_document_properties() -> None:
    data = documents.with_page_count(documents.clean_docx(), 4)

    assert parse_docx(data).page_count == 4


def test_page_count_is_unknown_when_the_property_is_absent() -> None:
    assert parse_docx(documents.docx_without_page_count()).page_count is None


def test_a_zero_page_count_is_treated_as_unknown() -> None:
    assert parse_docx(documents.with_page_count(documents.clean_docx(), 0)).page_count is None


def _zip_with(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"PK\x03\x04 broken", id="broken-zip"),
        pytest.param(
            _zip_with({"[Content_Types].xml": b"<x/>", "word/document.xml": b"<not xml"}),
            id="invalid-xml",
        ),
        pytest.param(_zip_with({"hello.txt": b"x"}), id="not-a-word-package"),
    ],
)
def test_unreadable_docx_raises_a_typed_error(data: bytes) -> None:
    with pytest.raises(UnreadableDocumentError) as info:
        parse_docx(data)

    assert str(info.value) == "The document could not be read"


def test_a_docx_that_expands_too_much_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect, "MAX_DOCX_UNCOMPRESSED_BYTES", 100)

    with pytest.raises(UnreadableDocumentError):
        parse_docx(documents.clean_docx())


def test_parse_document_dispatches_by_type() -> None:
    assert parse_document(documents.clean_pdf(), "pdf").file_type == "pdf"
    assert parse_document(documents.clean_docx(), "docx").file_type == "docx"
