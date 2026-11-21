"""Database access for analyses. No business rules."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.matching.models import AnalysisResult
from app.analyses.models import Analysis
from app.analyses.schemas import AnalysisDetail
from app.core.processing import ProcessingError

ACTIVE = ("processing", "ready")
_ACTIVE_PREDICATE = text("status IN ('processing', 'ready')")
_CREATE_ATTEMPTS = 3


def _to_detail(row: Analysis) -> AnalysisDetail:
    return AnalysisDetail(
        id=row.id,
        resume_id=row.resume_id,
        job_id=row.job_id,
        status=row.status,  # type: ignore[arg-type]
        error=(
            ProcessingError(code=row.error_code, message=row.error_message or "")
            if row.error_code
            else None
        ),
        created_at=row.created_at,
        completed_at=row.completed_at,
        result=AnalysisResult.model_validate(row.result) if row.result is not None else None,
    )


class AnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, analysis_id: uuid.UUID) -> AnalysisDetail | None:
        row = await self._session.get(Analysis, analysis_id)
        return None if row is None else _to_detail(row)

    async def find_active(self, cache_key: str) -> AnalysisDetail | None:
        """The `processing` or `ready` analysis with this key (the database allows one)."""
        statement = (
            select(Analysis)
            .where(Analysis.cache_key == cache_key, Analysis.status.in_(ACTIVE))
            .order_by(Analysis.created_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return None if row is None else _to_detail(row)

    async def create(self, analysis: AnalysisDetail, cache_key: str) -> tuple[AnalysisDetail, bool]:
        """Store a new `processing` analysis unless one is already active for `cache_key`.

        One statement (`ON CONFLICT DO NOTHING` on the partial unique index), so two simultaneous
        requests cannot both win. Returns the analysis to use and whether this call created it.
        """
        for _ in range(_CREATE_ATTEMPTS):
            statement = (
                insert(Analysis)
                .values(
                    id=analysis.id,
                    resume_id=analysis.resume_id,
                    job_id=analysis.job_id,
                    status=analysis.status,
                    cache_key=cache_key,
                    created_at=analysis.created_at,
                )
                .on_conflict_do_nothing(index_elements=["cache_key"], index_where=_ACTIVE_PREDICATE)
                .returning(Analysis.id)
            )
            created = (await self._session.execute(statement)).scalar_one_or_none() is not None
            await self._session.commit()
            if created:
                return analysis, True
            winner = await self.find_active(cache_key)
            if winner is not None:
                return winner, False
            # the winner failed between the two statements: try to take its place
        raise RuntimeError("Could not create the analysis")

    async def save_result(self, analysis_id: uuid.UUID, result: AnalysisResult) -> bool:
        """Store the result and set `ready`; False (nothing written) if it was deleted meanwhile."""
        statement = (
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(
                status="ready",
                error_code=None,
                error_message=None,
                result=result.model_dump(mode="json"),
                completed_at=datetime.now(UTC),
            )
            .returning(Analysis.id)
        )
        saved = (await self._session.execute(statement)).scalar_one_or_none() is not None
        await self._session.commit()
        return saved

    async def set_failed(self, analysis_id: uuid.UUID, code: str, message: str) -> None:
        await self._session.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(
                status="failed",
                error_code=code,
                error_message=message,
                result=None,
                completed_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

    async def mark_interrupted(self, message: str) -> int:
        """Fail every analysis still `processing` (its background work died with the process)."""
        result = await self._session.execute(
            update(Analysis)
            .where(Analysis.status == "processing")
            .values(
                status="failed",
                error_code="processing_interrupted",
                error_message=message,
                completed_at=datetime.now(UTC),
            )
            .returning(Analysis.id)
        )
        count = len(result.all())
        await self._session.commit()
        return count
