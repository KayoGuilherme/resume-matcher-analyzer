import pytest
from pydantic import ValidationError

from app.jobs.schemas import JobDetail, JobIn, JobSummary


def _body(**override: object) -> dict[str, object]:
    values: dict[str, object] = {"title": "Backend", "description": "Build APIs"}
    values.update(override)
    return values


def test_only_the_required_fields_are_enough() -> None:
    job = JobIn.model_validate(_body())

    assert (job.company, job.requirements_text) == (None, None)


def test_text_is_stripped_and_blank_optionals_become_none() -> None:
    job = JobIn.model_validate(
        _body(title="  Backend  ", description="\n text \n", company="  ", requirements_text="")
    )

    assert (job.title, job.description) == ("Backend", "text")
    assert (job.company, job.requirements_text) == (None, None)


@pytest.mark.parametrize(
    ("field", "limit"),
    [("title", 200), ("company", 200), ("description", 50_000), ("requirements_text", 50_000)],
)
def test_the_limit_is_accepted_and_one_over_is_rejected(field: str, limit: int) -> None:
    assert getattr(JobIn.model_validate(_body(**{field: "x" * limit})), field) == "x" * limit

    with pytest.raises(ValidationError) as exc_info:
        JobIn.model_validate(_body(**{field: "x" * (limit + 1)}))
    assert field in str(exc_info.value)


@pytest.mark.parametrize("field", ["title", "description"])
@pytest.mark.parametrize("value", ["", "   ", "\n\t"])
def test_blank_required_fields_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        JobIn.model_validate(_body(**{field: value}))

    assert field in str(exc_info.value)


@pytest.mark.parametrize("field", ["title", "description"])
def test_missing_required_fields_are_rejected(field: str) -> None:
    body = _body()
    del body[field]

    with pytest.raises(ValidationError):
        JobIn.model_validate(body)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        JobIn.model_validate(_body(salary=1000))

    assert "salary" in str(exc_info.value)


def test_a_summary_has_no_texts_and_a_detail_has() -> None:
    assert {"description", "requirements_text", "extraction"}.isdisjoint(JobSummary.model_fields)
    assert {"description", "requirements_text", "extraction"} <= set(JobDetail.model_fields)
