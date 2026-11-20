import pytest

from app.ai.parsing.models import UnreadableDocumentError
from app.ai.parsing.pdf import parse_pdf
from tests.fixtures import documents


def test_clean_pdf_text_is_in_order_and_has_no_layout_flags() -> None:
    document = parse_pdf(documents.clean_pdf())

    assert document.file_type == "pdf"
    assert document.page_count == 2
    assert document.text.index("Experience") < document.text.index("Education")
    assert document.text.index("Education") < document.text.index("Skills")
    assert "\n" in document.text
    assert document.image_count == 0
    assert document.table_count == 0
    assert not document.multi_column
    assert not document.header_footer_text
    assert document.parser.startswith("pdfplumber ")


def test_right_aligned_dates_are_not_mistaken_for_columns() -> None:
    assert not parse_pdf(documents.clean_pdf()).multi_column


def test_two_column_pdf_is_flagged_and_read_line_by_line_across_columns() -> None:
    document = parse_pdf(documents.two_column_pdf())

    assert document.multi_column
    lines = document.text.splitlines()
    # What an ATS gets: the left and right column text of one visual line are joined.
    assert any("Experience" in line and "Skills" in line for line in lines)


def test_table_pdf_counts_the_table() -> None:
    document = parse_pdf(documents.table_pdf())

    assert document.table_count == 1
    assert not document.multi_column


def test_header_footer_pdf_is_flagged() -> None:
    assert parse_pdf(documents.header_footer_pdf()).header_footer_text


def test_scanned_pdf_has_images_and_no_text() -> None:
    document = parse_pdf(documents.scanned_pdf())

    assert document.text.strip() == ""
    assert document.image_count == 2
    assert document.page_count == 2


@pytest.mark.parametrize("count", [1, 4])
def test_page_count_matches(count: int) -> None:
    assert parse_pdf(documents.many_pages_pdf(count)).page_count == count


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(documents.clean_pdf()[:200], id="truncated-early"),
        pytest.param(documents.clean_pdf()[: len(documents.clean_pdf()) // 2], id="truncated-half"),
        pytest.param(b"%PDF-1.4\n" + bytes(range(256)) * 4, id="garbage-after-signature"),
        pytest.param(b"%PDF-1.4\n", id="signature-only"),
    ],
)
def test_unreadable_pdfs_raise_a_typed_error_without_content(data: bytes) -> None:
    with pytest.raises(UnreadableDocumentError) as info:
        parse_pdf(data)

    assert str(info.value) == "The document could not be read"
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__
