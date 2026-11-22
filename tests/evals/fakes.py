"""A fake LLM and embeddings for the runner tests: no network, deterministic answers."""

import re

from pydantic import BaseModel

from app.ai.extraction.job_models import ExtractedJob
from app.ai.extraction.models import ExtractedResume
from app.ai.llm.base import LLMTransientError
from app.ai.matching.models import JudgeAnswer, JudgeBatch
from app.ai.matching.report_models import ScreenerAnswer, SuggestionBatch
from tests.ai.extraction.builders import experience, extracted
from tests.fixtures.job_postings import ENGLISH

BULLET = "Reduced p95 latency by 40%"


class RoutedLLM:
    """Answers each kind of request: the extractions, the judge (`missing`), the screener
    (`reject`) and the suggestions (none)."""

    provider = "fake"
    model = "fake-model"

    def __init__(self, *, fail_on: type[BaseModel] | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[type[BaseModel]] = []
        self._job_answers = list(ENGLISH.answers)

    async def generate_structured[T: BaseModel](
        self, prompt: str, schema: type[T], *, system: str | None = None
    ) -> T:
        self.calls.append(schema)
        if schema is self.fail_on:
            raise LLMTransientError("scripted failure")
        if schema is ExtractedResume:
            resume = extracted(experiences=[experience(BULLET)], skills=["Python, SQL"])
            return schema.model_validate(resume.model_dump())
        if schema is ExtractedJob:
            answer = (
                self._job_answers.pop(0) if len(self._job_answers) > 1 else self._job_answers[0]
            )
            return schema.model_validate(answer.model_dump())
        if schema is ScreenerAnswer:
            return schema.model_validate(
                ScreenerAnswer(decision="reject", reasons=["Shows little."]).model_dump()
            )
        if schema is SuggestionBatch:
            return schema.model_validate(SuggestionBatch(suggestions=[]).model_dump())
        numbers = [int(n) for n in re.findall(r"\[R(\d+)\]", prompt)]
        answers = [
            JudgeAnswer(requirement=n, verdict="missing", quotes=[], explanation="Not shown.")
            for n in numbers
        ]
        return schema.model_validate(JudgeBatch(answers=answers).model_dump())
