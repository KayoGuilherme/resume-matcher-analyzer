"""A scripted `Transport` for testing the shared wrapper without any provider."""

from collections.abc import Sequence

from app.ai.llm.base import CompletionRequest, RawCompletion, TokenUsage


class ScriptedTransport:
    """Returns the scripted items in order: text (an answer) or an exception (raised)."""

    def __init__(self, script: Sequence[str | Exception], usage: TokenUsage | None = None) -> None:
        self._script = list(script)
        self._usage = usage
        self.requests: list[CompletionRequest] = []

    @property
    def provider(self) -> str:
        return "scripted"

    @property
    def model(self) -> str:
        return "scripted-model"

    async def complete(self, request: CompletionRequest) -> RawCompletion:
        self.requests.append(request)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return RawCompletion(text=item, usage=self._usage)
