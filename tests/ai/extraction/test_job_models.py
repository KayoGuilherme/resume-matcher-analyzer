import pytest
from pydantic import ValidationError

from app.ai.extraction.job_models import ExtractedJob, ExtractedRequirement, Job
from app.ai.llm.openai_client import pydantic_function_tool


def _requirement(**override: object) -> dict[str, object]:
    values: dict[str, object] = {
        "text": "Python",
        "category": "skill",
        "priority": "must_have",
        "min_years": None,
        "keywords": [{"name": "Python", "synonyms": []}],
        "source_text": "Python is required",
    }
    values.update(override)
    return values


def _job(**override: object) -> dict[str, object]:
    values: dict[str, object] = {
        "seniority": None,
        "language": "en",
        "responsibilities": [],
        "ats_keywords": [],
        "requirements": [],
    }
    values.update(override)
    return values


@pytest.mark.parametrize("category", ["skill", "years", "language", "education", "domain", "soft"])
def test_every_category_is_accepted(category: str) -> None:
    assert ExtractedRequirement.model_validate(_requirement(category=category)).category == category


@pytest.mark.parametrize("override", [{"category": "hobby"}, {"priority": "maybe"}])
def test_unknown_categories_and_priorities_are_rejected(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExtractedRequirement.model_validate(_requirement(**override))


@pytest.mark.parametrize("priority", ["must_have", "nice_to_have", "unclear"])
def test_the_model_may_answer_unclear(priority: str) -> None:
    assert ExtractedRequirement.model_validate(_requirement(priority=priority)).priority == priority


@pytest.mark.parametrize("years", [-1, 99, 60.5, float("nan")])
def test_min_years_out_of_range_is_rejected(years: float) -> None:
    with pytest.raises(ValidationError):
        ExtractedRequirement.model_validate(_requirement(min_years=years))


@pytest.mark.parametrize("years", [0, 3, 2.5, 60, None])
def test_min_years_in_range_is_accepted(years: float | None) -> None:
    assert ExtractedRequirement.model_validate(_requirement(min_years=years)).min_years == years


@pytest.mark.parametrize("language", ["en", "pt", "other"])
def test_languages(language: str) -> None:
    assert ExtractedJob.model_validate(_job(language=language)).language == language


@pytest.mark.parametrize("override", [{"language": "fr"}, {"seniority": "lead"}])
def test_unknown_languages_and_seniorities_are_rejected(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExtractedJob.model_validate(_job(**override))


def test_unknown_fields_in_an_answer_are_ignored() -> None:
    job = ExtractedJob.model_validate(_job(total_years=12))

    assert not hasattr(job, "total_years")


def _field_names(model: type[ExtractedJob] | type[Job]) -> set[str]:
    schema = model.model_json_schema()
    definitions = schema.get("$defs", {})
    names: set[str] = set()
    pending = [schema]
    seen = 0
    while pending and seen < 100:
        seen += 1
        current = pending.pop()
        properties = current.get("properties", {})
        names |= set(properties)
        for value in properties.values():
            refs = [value.get("$ref"), (value.get("items") or {}).get("$ref")]
            refs += [option.get("$ref") for option in value.get("anyOf", [])]
            pending += [definitions[ref.split("/")[-1]] for ref in refs if ref]
    return names


def test_the_llm_schema_has_no_ids_or_flags_and_the_result_has_them() -> None:
    asked = _field_names(ExtractedJob)
    result = _field_names(Job)

    assert "id" not in asked and "priority_unclear" not in asked and "normalized" not in asked
    assert {"id", "priority_unclear", "normalized"} <= result
    assert not any("email" in n or "phone" in n or "contact" in n for n in asked | result)


def test_the_llm_schema_works_with_strict_structured_output() -> None:
    schema = pydantic_function_tool(ExtractedJob)["function"].get("parameters", {})

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "seniority",
        "language",
        "responsibilities",
        "ats_keywords",
        "requirements",
    }
