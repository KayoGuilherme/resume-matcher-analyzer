"""Resume text and file names must never reach the application's logs or error messages.

Library loggers (pdfminer prints document content at DEBUG) are capped in `configure_logging`
and tested in tests/core/test_logging.py and the router tests.
"""

import logging

import pytest

from app.core.errors import DomainError
from app.resumes.service import ResumeService
from tests.fixtures import documents
from tests.resumes.fakes import FakeRepository, FakeStorage

FILE_NAME = "Alex_Example_PRIVATE_CV.pdf"
RESUME_TEXT_SNIPPETS = ("Alex Example", "alex@example.com", "Acme Corp", "payments platform")


def _service() -> ResumeService:
    return ResumeService(FakeRepository(), FakeStorage(), 5 * 1024 * 1024)  # type: ignore[arg-type]


def _everything_logged(caplog: pytest.LogCaptureFixture) -> str:
    return " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)


def _assert_private(text: str) -> None:
    assert FILE_NAME not in text
    assert "PRIVATE" not in text
    for snippet in RESUME_TEXT_SNIPPETS:
        assert snippet not in text


async def test_upload_duplicate_and_delete_do_not_log_names_or_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _service()
    data = documents.clean_pdf()

    with caplog.at_level(logging.DEBUG, logger="app"):
        resume = (await service.upload(FILE_NAME, data)).resume
        await service.upload(FILE_NAME, data)
        await service.get(resume.id)
        await service.list_all()
        await service.delete(resume.id)

    logged = _everything_logged(caplog)
    _assert_private(logged)
    assert str(resume.id) in logged
    assert "resume uploaded" in logged and "resume deleted" in logged


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "empty_file"),
        (documents.fake_pdf(), "unsupported_file_type"),
        (documents.scanned_pdf(), "no_extractable_text"),
        (documents.clean_pdf()[:200], "unreadable_file"),
        (b"%PDF-" + b"0" * (6 * 1024 * 1024), "file_too_large"),
    ],
)
async def test_rejections_log_only_the_reason(
    caplog: pytest.LogCaptureFixture, data: bytes, reason: str
) -> None:
    service = _service()

    with caplog.at_level(logging.DEBUG, logger="app"), pytest.raises(DomainError) as info:
        await service.upload(FILE_NAME, data)

    logged = _everything_logged(caplog)
    _assert_private(logged)
    assert reason in logged
    _assert_private(info.value.message)


async def test_error_messages_hold_neither_file_name_nor_resume_text() -> None:
    service = _service()
    blank = documents.blank_docx()

    with pytest.raises(DomainError) as info:
        await service.upload(FILE_NAME, blank)

    _assert_private(info.value.message)
