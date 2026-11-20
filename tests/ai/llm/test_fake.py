import pytest
from pydantic import BaseModel

from app.ai.llm.base import LLMInvalidOutputError, LLMTimeoutError
from app.ai.llm.fake import FakeLLMClient


class Person(BaseModel):
    name: str


async def test_a_scripted_instance_is_returned_and_the_call_recorded() -> None:
    fake = FakeLLMClient([Person(name="Ana")])

    result = await fake.generate_structured("Who?", Person, system="Be brief")

    assert result == Person(name="Ana")
    (call,) = fake.calls
    assert (call.prompt, call.system, call.schema) == ("Who?", "Be brief", Person)


async def test_a_scripted_text_is_validated_like_a_real_answer() -> None:
    fake = FakeLLMClient(['{"name": "Ana"}', '{"nome": "Ana"}'])

    assert (await fake.generate_structured("a", Person)).name == "Ana"
    with pytest.raises(LLMInvalidOutputError):
        await fake.generate_structured("b", Person)


async def test_a_scripted_error_is_raised() -> None:
    fake = FakeLLMClient([LLMTimeoutError("timed out")])

    with pytest.raises(LLMTimeoutError):
        await fake.generate_structured("a", Person)


async def test_an_instance_of_another_model_is_revalidated_against_the_schema() -> None:
    class Other(BaseModel):
        name: str

    fake = FakeLLMClient([Other(name="Ana")])

    assert await fake.generate_structured("a", Person) == Person(name="Ana")


async def test_running_out_of_answers_is_a_test_error_unless_repeating() -> None:
    with pytest.raises(AssertionError):
        await FakeLLMClient().generate_structured("a", Person)

    repeating = FakeLLMClient([Person(name="Ana")], repeat=True)
    for _ in range(3):
        assert (await repeating.generate_structured("a", Person)).name == "Ana"
    assert len(repeating.calls) == 3
