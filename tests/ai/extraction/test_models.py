import pytest
from pydantic import ValidationError

from app.ai.extraction.models import ExtractedExperience, ExtractedResume, Resume
from app.ai.llm.openai_client import pydantic_function_tool


def _experience(start: str | None) -> dict[str, object]:
    return {
        "title": "Dev",
        "company": None,
        "start": start,
        "end": None,
        "is_current": True,
        "bullets": [],
    }


@pytest.mark.parametrize("value", ["2020-01", "1999-12", None])
def test_valid_months_are_accepted(value: str | None) -> None:
    assert ExtractedExperience.model_validate(_experience(value)).start == value


@pytest.mark.parametrize("value", ["2020-13", "2020-1", "2020-00", "01/2020", "2020", "abcd-ef"])
def test_invalid_months_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        ExtractedExperience.model_validate(_experience(value))


def _field_names(model: type[ExtractedResume] | type[Resume]) -> set[str]:
    names: set[str] = set()
    pending: list[dict[str, object]] = [model.model_json_schema()]
    definitions = model.model_json_schema().get("$defs", {})
    seen = 0
    while pending and seen < 100:
        seen += 1
        schema = pending.pop()
        properties = schema.get("properties", {})
        assert isinstance(properties, dict)
        names |= set(properties)
        for value in properties.values():
            refs = [value.get("$ref"), (value.get("items") or {}).get("$ref")]
            refs += [option.get("$ref") for option in value.get("anyOf", [])]
            pending += [definitions[ref.split("/")[-1]] for ref in refs if ref]
    return names


@pytest.mark.parametrize("model", [ExtractedResume, Resume])
def test_there_is_no_field_for_contact_details_or_totals(model: type) -> None:
    names = _field_names(model)

    forbidden = {"name", "email", "e_mail", "phone", "address", "links", "url", "linkedin"}
    assert not any(token in field for field in names for token in forbidden - {"name"})
    assert not any("total" in field or "years_of_experience" in field for field in names)
    assert names >= {"summary", "skills", "experiences", "education", "languages", "projects"}


def test_the_llm_schema_has_no_ids_but_the_result_does() -> None:
    assert "id" not in _field_names(ExtractedResume)
    assert "id" in _field_names(Resume)


def test_the_llm_schema_works_with_strict_structured_output() -> None:
    schema = pydantic_function_tool(ExtractedResume)["function"].get("parameters", {})

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "summary",
        "skills",
        "experiences",
        "education",
        "languages",
        "certifications",
        "projects",
    }


def test_unknown_fields_in_an_answer_are_ignored() -> None:
    answer = {
        "summary": None,
        "skills": [],
        "experiences": [],
        "education": [],
        "languages": [],
        "certifications": [],
        "projects": [],
        "total_years": 12,
    }

    assert not hasattr(ExtractedResume.model_validate(answer), "total_years")
