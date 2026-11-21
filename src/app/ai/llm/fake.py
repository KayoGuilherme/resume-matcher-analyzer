"""A scripted `LLMClient` for tests. Never touches the network."""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from app.ai.llm.base import LLMInvalidOutputError
from app.ai.llm.output import OutputProblem, parse_structured


@dataclass(frozen=True)
class FakeCall:
    prompt: str
    system: str | None
    schema: type[BaseModel]


class FakeLLMClient:
    """Answers with the scripted items in order.

    An item is a model instance (returned as the schema instance), a string (parsed and
    validated like a real answer; invalid text raises `LLMInvalidOutputError`) or an exception
    (raised). The same item list is reused from the start only if `repeat` is set.
    """

    def __init__(
        self,
        responses: Sequence[BaseModel | str | Exception] = (),
        *,
        provider: str = "fake",
        model: str = "fake-model",
        repeat: bool = False,
    ) -> None:
        self._responses = list(responses)
        self._position = 0
        self._repeat = repeat
        self._provider = provider
        self._model = model
        self.calls: list[FakeCall] = []

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    async def generate_structured[T: BaseModel](
        self, prompt: str, schema: type[T], *, system: str | None = None
    ) -> T:
        self.calls.append(FakeCall(prompt, system, schema))
        if self._position >= len(self._responses):
            if not (self._repeat and self._responses):
                raise AssertionError("FakeLLMClient has no scripted response left")
            self._position = 0
        item = self._responses[self._position]
        self._position += 1
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            try:
                return parse_structured(item, schema)
            except OutputProblem:
                raise LLMInvalidOutputError("The scripted answer is not valid") from None
        if isinstance(item, schema):
            return item
        try:
            return schema.model_validate(item.model_dump())
        except ValueError:
            raise LLMInvalidOutputError("The scripted answer is not valid") from None
