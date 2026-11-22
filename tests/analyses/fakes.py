"""In-memory stand-ins and AI fakes for the analyses tests (no database, no network)."""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel

from app.ai.matching.models import AnalysisResult, JudgeAnswer, JudgeBatch
from app.ai.matching.report_models import ScreenerAnswer, StoredReport, SuggestionBatch
from app.analyses.schemas import AnalysisDetail
from app.core.processing import ProcessingError
from app.profile.schemas import ProfileOut


class FakeAnalysisRepository:
    """Keeps the rule of the database: one `processing` or `ready` analysis per cache key."""

    def __init__(self) -> None:
        self.by_id: dict[uuid.UUID, AnalysisDetail] = {}
        self.keys: dict[uuid.UUID, str] = {}
        self.reports: dict[uuid.UUID, StoredReport] = {}
        self.interrupted_message: str | None = None

    async def get(self, analysis_id: uuid.UUID) -> AnalysisDetail | None:
        return self.by_id.get(analysis_id)

    async def find_active(self, cache_key: str) -> AnalysisDetail | None:
        active = [
            a
            for a in self.by_id.values()
            if self.keys[a.id] == cache_key and a.status in ("processing", "ready")
        ]
        return active[0] if active else None

    async def create(self, analysis: AnalysisDetail, cache_key: str) -> tuple[AnalysisDetail, bool]:
        existing = await self.find_active(cache_key)
        if existing is not None:
            return existing, False
        self.by_id[analysis.id] = analysis
        self.keys[analysis.id] = cache_key
        return analysis, True

    async def get_report(self, analysis_id: uuid.UUID) -> StoredReport | None:
        return self.reports.get(analysis_id)

    async def save_result(
        self, analysis_id: uuid.UUID, result: AnalysisResult, report: StoredReport
    ) -> bool:
        analysis = self.by_id.get(analysis_id)
        if analysis is None:
            return False
        self.reports[analysis_id] = report
        self.by_id[analysis_id] = analysis.model_copy(
            update={"status": "ready", "result": result, "completed_at": datetime.now(UTC)}
        )
        return True

    async def set_failed(self, analysis_id: uuid.UUID, code: str, message: str) -> None:
        analysis = self.by_id.get(analysis_id)
        self.reports.pop(analysis_id, None)
        if analysis is not None:
            self.by_id[analysis_id] = analysis.model_copy(
                update={
                    "status": "failed",
                    "result": None,
                    "error": ProcessingError(code=code, message=message),
                    "completed_at": datetime.now(UTC),
                }
            )

    async def mark_interrupted(self, message: str) -> int:
        self.interrupted_message = message
        count = 0
        for analysis_id, analysis in list(self.by_id.items()):
            if analysis.status == "processing":
                error = ProcessingError(code="processing_interrupted", message=message)
                self.by_id[analysis_id] = analysis.model_copy(
                    update={"status": "failed", "error": error}
                )
                count += 1
        return count


class FakeProfileRepository:
    def __init__(self, profile: ProfileOut | None = None) -> None:
        self.profile = profile

    async def get(self) -> ProfileOut | None:
        return self.profile


class ConstantEmbeddingClient:
    """Every text gets the same vector, so every similarity is 1: whatever the deterministic
    checks do not settle goes to the judge."""

    def __init__(self, dimension: int = 8, model_name: str = "constant") -> None:
        self._dimension = dimension
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (self._dimension - 1) for _ in texts]


class AnswerAllLLM:
    """A judge that answers `missing` for every requirement it is asked about, a screener that
    answers `borderline` and a suggestion step that proposes nothing."""

    def __init__(self, provider: str = "fake", model: str = "fake-model") -> None:
        self._provider = provider
        self._model = model
        self.prompts: list[str] = []
        self.schemas: list[type[BaseModel]] = []

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def calls(self) -> int:
        return len(self.prompts)

    @property
    def judge_calls(self) -> int:
        return sum(1 for schema in self.schemas if schema is JudgeBatch)

    async def generate_structured[T: BaseModel](
        self, prompt: str, schema: type[T], *, system: str | None = None
    ) -> T:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        if schema is ScreenerAnswer:
            return schema.model_validate(
                ScreenerAnswer(decision="borderline", reasons=["Mixed."]).model_dump()
            )
        if schema is SuggestionBatch:
            return schema.model_validate(SuggestionBatch(suggestions=[]).model_dump())
        numbers = [int(n) for n in re.findall(r"\[R(\d+)\]", prompt)]
        answers = [
            JudgeAnswer(requirement=n, verdict="missing", quotes=[], explanation="Not shown.")
            for n in numbers
        ]
        return schema.model_validate(JudgeBatch(answers=answers).model_dump())
