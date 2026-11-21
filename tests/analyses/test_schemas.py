import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.analyses.schemas import AnalysisDetail, AnalysisRequest
from app.core.processing import ProcessingError
from tests.analyses.results import a_result

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _detail(status: str, **overrides: object) -> AnalysisDetail:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "resume_id": uuid.uuid4(),
        "job_id": uuid.uuid4(),
        "status": status,
        "created_at": NOW,
    }
    values.update(overrides)
    return AnalysisDetail.model_validate(values)


def test_both_ids_are_required_uuids() -> None:
    request = AnalysisRequest.model_validate(
        {"resume_id": str(uuid.uuid4()), "job_id": str(uuid.uuid4())}
    )

    assert isinstance(request.resume_id, uuid.UUID)
    with pytest.raises(ValidationError, match="job_id"):
        AnalysisRequest.model_validate({"resume_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError, match="resume_id"):
        AnalysisRequest.model_validate({"resume_id": "nope", "job_id": str(uuid.uuid4())})


def test_an_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="force"):
        AnalysisRequest.model_validate(
            {"resume_id": str(uuid.uuid4()), "job_id": str(uuid.uuid4()), "force": True}
        )


def test_a_processing_analysis_has_neither_error_nor_result() -> None:
    detail = _detail("processing")

    assert detail.error is None and detail.result is None and detail.completed_at is None


def test_a_ready_analysis_has_a_result_and_no_error() -> None:
    detail = _detail("ready", result=a_result(), completed_at=NOW)

    assert detail.result is not None and detail.error is None


def test_a_failed_analysis_has_an_error_and_no_result() -> None:
    detail = _detail("failed", error=ProcessingError(code="llm_timeout", message="m"))

    assert detail.error is not None and detail.result is None


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "processing", "result": a_result()},
        {"status": "processing", "error": ProcessingError(code="x", message="m")},
        {"status": "ready"},
        {"status": "ready", "result": a_result(), "error": ProcessingError(code="x", message="m")},
        {"status": "failed"},
        {"status": "failed", "error": ProcessingError(code="x", message="m"), "result": a_result()},
    ],
)
def test_error_and_result_must_follow_the_status(bad: dict[str, object]) -> None:
    status = str(bad.pop("status"))

    with pytest.raises(ValidationError):
        _detail(status, **bad)


def test_an_unknown_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _detail("uploaded")
