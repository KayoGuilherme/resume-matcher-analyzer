import uuid
from datetime import UTC, datetime

from app.ai.parsing.models import ParsingIssue
from app.resumes.schemas import ResumeDetail, ResumeMetadata, ResumeSummary


def _detail() -> ResumeDetail:
    return ResumeDetail(
        id=uuid.uuid4(),
        original_filename="resume.pdf",
        file_type="pdf",
        size_bytes=1234,
        sha256="a" * 64,
        page_count=None,
        metadata=ResumeMetadata(
            parser="pdfplumber 0.11", character_count=10, word_count=2, table_count=0, image_count=0
        ),
        issues=[ParsingIssue(code="tables", severity="warning", message="Tables found.")],
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
        text="hello world",
    )


def test_detail_has_every_field_of_the_spec() -> None:
    assert set(_detail().model_dump()) == {
        "id",
        "original_filename",
        "file_type",
        "size_bytes",
        "sha256",
        "page_count",
        "metadata",
        "issues",
        "created_at",
        "status",
        "error",
        "extraction",
        "text",
    }


def test_summary_has_no_text() -> None:
    assert "text" not in ResumeSummary.model_fields
    assert set(_detail().model_dump(exclude={"text", "extraction"})) == set(
        ResumeSummary.model_fields
    )


def test_a_new_resume_is_uploaded_without_error_or_extraction() -> None:
    detail = _detail()

    assert (detail.status, detail.error, detail.extraction) == ("uploaded", None, None)


def test_metadata_has_the_documented_fields() -> None:
    assert set(ResumeMetadata.model_fields) == {
        "parser",
        "character_count",
        "word_count",
        "table_count",
        "image_count",
    }


def test_issue_json_shape() -> None:
    issue = _detail().model_dump(mode="json")["issues"][0]

    assert issue == {"code": "tables", "severity": "warning", "message": "Tables found."}


def test_json_dump_uses_strings_for_ids_and_dates() -> None:
    data = _detail().model_dump(mode="json")

    assert isinstance(data["id"], str)
    assert data["created_at"].startswith("2026-11-20")
    assert data["page_count"] is None
