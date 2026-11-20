import io
import zipfile

import pytest

from app.ai.parsing import detect
from app.ai.parsing.detect import detect_file_type, exceeds_uncompressed_limit
from app.ai.parsing.models import UnreadableDocumentError
from tests.fixtures import documents

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_a_real_pdf_is_detected() -> None:
    assert detect_file_type(documents.clean_pdf()) == "pdf"


def test_a_real_docx_is_detected() -> None:
    assert detect_file_type(documents.clean_docx()) == "docx"


def test_the_type_comes_from_the_bytes_not_from_a_name() -> None:
    # The function has no file name parameter: a PDF is a PDF whatever it is called.
    assert detect_file_type(documents.scanned_pdf()) == "pdf"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(documents.fake_pdf(), id="text-with-pdf-name"),
        pytest.param(documents.zip_not_docx(), id="zip-that-is-not-word"),
        pytest.param(PNG, id="png"),
        pytest.param(b"", id="empty"),
        pytest.param(b"PK\x03\x04 this is not a real zip archive", id="broken-zip"),
        pytest.param(b" %PDF-1.4", id="signature-not-at-start"),
    ],
)
def test_everything_else_is_unsupported(data: bytes) -> None:
    assert detect_file_type(data) is None


def test_normal_documents_are_under_the_uncompressed_limit() -> None:
    assert not exceeds_uncompressed_limit(documents.clean_docx())


def test_a_zip_that_expands_past_the_cap_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"0" * 5_000)
    monkeypatch.setattr(detect, "MAX_DOCX_UNCOMPRESSED_BYTES", 1_000)

    assert exceeds_uncompressed_limit(buffer.getvalue())


def test_non_zip_data_never_exceeds_the_limit() -> None:
    assert not exceeds_uncompressed_limit(b"%PDF-1.4")


def test_unreadable_document_error_message_is_generic() -> None:
    assert str(UnreadableDocumentError()) == "The document could not be read"
