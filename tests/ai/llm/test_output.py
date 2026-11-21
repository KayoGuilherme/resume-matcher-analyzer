import pytest
from pydantic import BaseModel

from app.ai.llm.output import OutputProblem, extract_json, parse_structured


class Person(BaseModel):
    name: str
    age: int


def test_plain_json_is_parsed() -> None:
    assert extract_json(' {"a": 1} ') == {"a": 1}


def test_json_in_a_markdown_fence_is_found() -> None:
    assert extract_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}


def test_json_after_a_sentence_is_found() -> None:
    assert extract_json('Sure! Here it is: {"a": {"b": 2}} Hope it helps.') == {"a": {"b": 2}}


def test_text_without_json_is_rejected() -> None:
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_a_valid_answer_becomes_an_instance() -> None:
    assert parse_structured('{"name": "Ana", "age": 30}', Person) == Person(name="Ana", age=30)


def test_problems_name_fields_and_never_echo_values() -> None:
    with pytest.raises(OutputProblem) as exc_info:
        parse_structured('{"name": "secret-value", "age": "old"}', Person)

    problems = exc_info.value.problems
    assert len(problems) == 1
    assert problems[0].startswith("age:")
    assert "secret-value" not in " ".join(problems)


def test_non_json_is_reported_as_such() -> None:
    with pytest.raises(OutputProblem) as exc_info:
        parse_structured("I cannot do that", Person)

    assert exc_info.value.problems == ["the answer is not valid JSON"]
