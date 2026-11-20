import io
import zipfile

import docx
import pdfplumber
import pytest

from tests.fixtures import documents


def _pdf(data: bytes) -> pdfplumber.PDF:
    return pdfplumber.open(io.BytesIO(data))


def test_clean_pdf_has_two_pages_of_ordered_text() -> None:
    with _pdf(documents.clean_pdf()) as pdf:
        assert len(pdf.pages) == 2
        text = "\n".join(page.extract_text() for page in pdf.pages)
        assert text.index("Experience") < text.index("Education") < text.index("Skills")
        assert "• Designed and built REST APIs" in text
        assert not any(page.images for page in pdf.pages)


def test_clean_pdf_has_enough_text_per_page() -> None:
    with _pdf(documents.clean_pdf()) as pdf:
        assert all(len(page.extract_text()) > 500 for page in pdf.pages)


def test_two_column_pdf_has_text_on_both_sides() -> None:
    with _pdf(documents.two_column_pdf()) as pdf:
        words = pdf.pages[0].extract_words()
        assert any(word["x1"] < 300 for word in words)
        assert any(word["x0"] > 330 for word in words)
        assert not any(word["x0"] < 300 < word["x1"] for word in words)


def test_table_pdf_has_a_ruled_table() -> None:
    with _pdf(documents.table_pdf()) as pdf:
        assert len(pdf.pages[0].find_tables()) == 1


def test_header_footer_pdf_has_text_in_both_margin_bands() -> None:
    with _pdf(documents.header_footer_pdf()) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        assert any(word["top"] < page.height * 0.07 for word in words)
        assert any(word["bottom"] > page.height * 0.93 for word in words)


def test_scanned_pdf_has_images_and_no_text() -> None:
    with _pdf(documents.scanned_pdf()) as pdf:
        assert len(pdf.pages) == 2
        assert all(page.images for page in pdf.pages)
        assert all(not page.extract_text() for page in pdf.pages)


@pytest.mark.parametrize("count", [1, 3, 4])
def test_many_pages_pdf_has_the_requested_number_of_pages(count: int) -> None:
    with _pdf(documents.many_pages_pdf(count)) as pdf:
        assert len(pdf.pages) == count


def test_fake_pdf_is_not_a_pdf() -> None:
    assert not documents.fake_pdf().startswith(b"%PDF-")


def test_special_characters_are_escaped_in_pdf_text() -> None:
    page = documents.Page((documents.Text(72, 700, "Review (draft) \\ done"),))

    with _pdf(documents.build_pdf([page])) as pdf:
        assert pdf.pages[0].extract_text() == "Review (draft) \\ done"


def _docx(data: bytes) -> docx.document.Document:
    return docx.Document(io.BytesIO(data))


def test_clean_docx_has_headings_and_no_table_header_or_columns() -> None:
    document = _docx(documents.clean_docx())

    assert [p.text for p in document.paragraphs[:2]] == ["Alex Example", "Experience"]
    assert document.tables == []
    assert not document.sections[0].header.paragraphs[0].text


def test_docx_with_table_has_a_table() -> None:
    assert len(_docx(documents.docx_with_table()).tables) == 1


def test_docx_with_header_has_header_text() -> None:
    header = _docx(documents.docx_with_header()).sections[0].header

    assert header.paragraphs[0].text.startswith("alex@example.com")


def test_two_column_docx_has_two_columns() -> None:
    section = _docx(documents.two_column_docx()).sections[0]

    assert section._sectPr.xpath("./w:cols/@w:num") == ["2"]


def test_page_count_property_can_be_set_and_removed() -> None:
    def pages(data: bytes) -> str:
        return zipfile.ZipFile(io.BytesIO(data)).read("docProps/app.xml").decode()

    assert "<Pages>4</Pages>" in pages(documents.with_page_count(documents.clean_docx(), 4))
    assert "<Pages>" not in pages(documents.docx_without_page_count())
    assert _docx(documents.docx_without_page_count()).paragraphs


def test_zip_not_docx_is_a_zip_without_word_parts() -> None:
    names = zipfile.ZipFile(io.BytesIO(documents.zip_not_docx())).namelist()

    assert "word/document.xml" not in names
