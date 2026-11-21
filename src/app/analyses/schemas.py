"""Request and response models for gap analyses."""

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.ai.matching.models import AnalysisResult
from app.core.processing import ProcessingError

AnalysisStatus = Literal["processing", "ready", "failed"]


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: uuid.UUID
    job_id: uuid.UUID


class AnalysisDetail(BaseModel):
    """An analysis: `error` only when `failed`, `result` only when `ready`."""

    id: uuid.UUID
    resume_id: uuid.UUID
    job_id: uuid.UUID
    status: AnalysisStatus
    error: ProcessingError | None = None
    created_at: datetime
    completed_at: datetime | None = None
    result: AnalysisResult | None = None

    @model_validator(mode="after")
    def _error_and_result_follow_the_status(self) -> Self:
        if (self.error is not None) != (self.status == "failed"):
            raise ValueError("an error is present exactly when the status is failed")
        if (self.result is not None) != (self.status == "ready"):
            raise ValueError("a result is present exactly when the status is ready")
        return self
