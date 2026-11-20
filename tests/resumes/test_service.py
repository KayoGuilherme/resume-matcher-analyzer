import hashlib
import logging
import uuid

import pytest

from app.ai.parsing.models import ParsingIssue
from app.resumes.service import (
    EmptyFileError,
    FileTooLargeError,
    NoExtractableTextError,
    ResumeNotFoundError,
    ResumeService,
    UnreadableFileError,
    UnsupportedFileTypeError,
    format_size_limit,
)
from tests.fixtures import documents
from tests.resumes.fakes import FakeRepository, FakeStorage

MB = 1024 * 1024


def _service(
    max_bytes: int = 5 * MB,
) -> tuple[ResumeService, FakeRepository, FakeStorage]:
    repository, storage = FakeRepository(), FakeStorage()
    return ResumeService(repository, storage, max_bytes), repository, storage  # type: ignore[arg-type]


def _codes(issues: list[ParsingIssue]) -> list[str]:
    return [issue.code for issue in issues]


async def test_clean_pdf_is_accepted_with_no_issues() -> None:
    service, _, storage = _service()
    data = documents.clean_pdf()

    result = await service.upload("resume.pdf", data)

    assert result.created is True
    resume = result.resume
    assert resume.file_type == "pdf"
    assert resume.issues == []
    assert resume.page_count == 2
    assert resume.sha256 == hashlib.sha256(data).hexdigest()
    assert resume.size_bytes == len(data)
    assert "Experience" in resume.text
    assert resume.metadata.character_count == len(resume.text)
    assert resume.metadata.word_count == len(resume.text.split())
    assert storage.files == {f"{resume.sha256}.pdf": data}


async def test_two_column_pdf_is_accepted_with_a_multi_column_issue() -> None:
    service, _, _ = _service()

    result = await service.upload("two.pdf", documents.two_column_pdf())

    assert result.created
    assert "multi_column" in _codes(result.resume.issues)


async def test_docx_is_accepted() -> None:
    service, _, storage = _service()

    result = await service.upload("resume.docx", documents.clean_docx())

    assert result.resume.file_type == "docx"
    assert f"{result.resume.sha256}.docx" in storage.files


async def test_scanned_pdf_is_rejected_with_the_scanned_wording() -> None:
    service, repository, storage = _service()

    with pytest.raises(NoExtractableTextError) as info:
        await service.upload("scan.pdf", documents.scanned_pdf())

    assert info.value.status_code == 422
    assert info.value.code == "no_extractable_text"
    assert "looks scanned or image-only" in info.value.message
    assert "read as blank" in info.value.message
    assert repository.by_id == {} and storage.files == {}


async def test_blank_docx_is_rejected_without_the_scanned_wording() -> None:
    service, _, _ = _service()

    with pytest.raises(NoExtractableTextError) as info:
        await service.upload("blank.docx", documents.blank_docx())

    assert "scanned" not in info.value.message
    assert "read as blank" in info.value.message


async def test_fake_pdf_is_rejected_as_unsupported() -> None:
    service, repository, storage = _service()

    with pytest.raises(UnsupportedFileTypeError) as info:
        await service.upload("resume.pdf", documents.fake_pdf())

    assert (info.value.status_code, info.value.code) == (415, "unsupported_file_type")
    assert "PDF and DOCX" in info.value.message
    assert repository.by_id == {} and storage.files == {}


async def test_a_zip_that_is_not_word_is_unsupported() -> None:
    service, _, _ = _service()

    with pytest.raises(UnsupportedFileTypeError):
        await service.upload("resume.docx", documents.zip_not_docx())


async def test_the_type_comes_from_the_content_not_the_name() -> None:
    service, _, _ = _service()

    result = await service.upload("resume.txt", documents.clean_pdf())

    assert result.resume.file_type == "pdf"


async def test_empty_file_is_rejected() -> None:
    service, _, _ = _service()

    with pytest.raises(EmptyFileError) as info:
        await service.upload("empty.pdf", b"")

    assert (info.value.status_code, info.value.code) == (422, "empty_file")


async def test_corrupted_pdf_is_unreadable() -> None:
    service, repository, storage = _service()

    with pytest.raises(UnreadableFileError) as info:
        await service.upload("broken.pdf", documents.clean_pdf()[:200])

    assert (info.value.status_code, info.value.code) == (422, "unreadable_file")
    assert "ATS could not open it either" in info.value.message
    assert repository.by_id == {} and storage.files == {}


async def test_file_over_the_limit_is_rejected_and_the_limit_is_accepted() -> None:
    data = documents.clean_pdf()
    service, repository, storage = _service(max_bytes=len(data) - 1)

    with pytest.raises(FileTooLargeError) as info:
        await service.upload("big.pdf", data)

    assert (info.value.status_code, info.value.code) == (413, "file_too_large")
    assert repository.by_id == {} and storage.files == {}

    at_limit, _, _ = _service(max_bytes=len(data))
    assert (await at_limit.upload("ok.pdf", data)).created


async def test_the_configured_limit_is_named_in_the_message() -> None:
    service, _, _ = _service(max_bytes=1 * MB)

    with pytest.raises(FileTooLargeError) as info:
        await service.upload("big.pdf", b"%PDF-" + b"0" * (2 * MB))

    assert "1 MB" in info.value.message


@pytest.mark.parametrize(
    ("limit", "text"), [(5 * MB, "5 MB"), (1 * MB, "1 MB"), (1500, "1500 bytes")]
)
def test_size_limit_formatting(limit: int, text: str) -> None:
    assert format_size_limit(limit) == text


async def test_the_same_file_twice_returns_the_existing_resume_without_work() -> None:
    service, repository, storage = _service()
    data = documents.clean_pdf()
    first = await service.upload("a.pdf", data)
    stored_before = dict(storage.files)

    second = await service.upload("other-name.pdf", data)

    assert (first.created, second.created) == (True, False)
    assert second.resume.id == first.resume.id
    assert repository.add_calls == 1
    assert storage.files == stored_before
    assert len(repository.by_id) == 1


async def test_a_lost_race_returns_the_winner_and_keeps_the_stored_file() -> None:
    service, repository, storage = _service()
    data = documents.clean_pdf()
    winner = (await _service()[0].upload("w.pdf", data)).resume
    repository.lose_race_to = winner

    result = await service.upload("a.pdf", data)

    assert result.created is False
    assert result.resume.id == winner.id
    assert f"{winner.sha256}.pdf" in storage.files


async def test_a_lost_race_with_a_vanished_winner_is_an_error() -> None:
    service, repository, _ = _service()

    async def vanish(_: object) -> bool:
        return False

    repository.add = vanish  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await service.upload("a.pdf", documents.clean_pdf())


async def test_storage_failure_leaves_no_record() -> None:
    service, repository, storage = _service()
    storage.fail_on_save = OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        await service.upload("a.pdf", documents.clean_pdf())

    assert repository.by_id == {}
    assert repository.add_calls == 0


async def test_repository_failure_removes_the_file_that_was_just_stored() -> None:
    service, repository, storage = _service()
    repository.fail_on_add = RuntimeError("db down")

    with pytest.raises(RuntimeError, match="db down"):
        await service.upload("a.pdf", documents.clean_pdf())

    assert storage.files == {}


async def test_repository_failure_keeps_a_file_that_was_already_there() -> None:
    service, repository, storage = _service()
    data = documents.clean_pdf()
    key = f"{hashlib.sha256(data).hexdigest()}.pdf"
    storage.files[key] = data
    repository.fail_on_add = RuntimeError("db down")

    with pytest.raises(RuntimeError):
        await service.upload("a.pdf", data)

    assert key in storage.files


@pytest.mark.parametrize(
    ("given", "shown"),
    [
        ("cv.pdf", "cv.pdf"),
        ("../../etc/cv.pdf", "cv.pdf"),
        ("C:\\Users\\me\\cv.pdf", "cv.pdf"),
        (None, "resume"),
        ("", "resume"),
        ("a" * 300 + ".pdf", ("a" * 300 + ".pdf")[:255]),
    ],
)
async def test_the_display_name_has_no_directories_and_is_bounded(
    given: str | None, shown: str
) -> None:
    service, _, storage = _service()

    result = await service.upload(given, documents.clean_pdf())

    assert result.resume.original_filename == shown
    assert all(shown not in key for key in storage.files)


async def test_list_and_get_after_upload() -> None:
    service, _, _ = _service()
    uploaded = (await service.upload("a.pdf", documents.clean_pdf())).resume

    assert await service.get(uploaded.id) == uploaded
    assert [s.id for s in await service.list_all()] == [uploaded.id]


async def test_get_of_an_unknown_id_is_not_found() -> None:
    service, _, _ = _service()

    with pytest.raises(ResumeNotFoundError) as info:
        await service.get(uuid.uuid4())

    assert (info.value.status_code, info.value.code) == (404, "resume_not_found")


async def test_delete_removes_the_record_and_then_the_file() -> None:
    service, repository, storage = _service()
    resume = (await service.upload("a.pdf", documents.clean_pdf())).resume

    await service.delete(resume.id)

    assert repository.by_id == {}
    assert storage.files == {}
    with pytest.raises(ResumeNotFoundError):
        await service.delete(resume.id)


async def test_delete_succeeds_even_if_the_file_cannot_be_removed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, repository, storage = _service()
    resume = (await service.upload("a.pdf", documents.clean_pdf())).resume
    storage.fail_on_delete = OSError("read-only")

    with caplog.at_level(logging.WARNING):
        await service.delete(resume.id)

    assert repository.by_id == {}
    assert any("could not be removed" in r.getMessage() for r in caplog.records)


async def test_delete_of_an_unknown_id_is_not_found() -> None:
    service, _, _ = _service()

    with pytest.raises(ResumeNotFoundError):
        await service.delete(uuid.uuid4())


async def test_the_same_file_can_be_uploaded_again_after_deleting() -> None:
    service, _, _ = _service()
    data = documents.clean_pdf()
    first = (await service.upload("a.pdf", data)).resume
    await service.delete(first.id)

    again = await service.upload("a.pdf", data)

    assert again.created is True
    assert again.resume.id != first.id
