"""The identity of an analysis: what has to be equal for an earlier result to be reused.

The key holds the resume and the job, the judge prompt version, the LLM and the analysis settings
(as the brief asks), the screener and suggestion prompts with their versions and the report
settings (screener runs, suggestions cap), and a fingerprint of the stored processing results and
the profile, so a profile that was edited or a resume or job that was processed again is never
answered with an older result. The `SCORE_*` settings are not part of it: the score is computed
when the report is read. Pure functions.
"""

import hashlib
import json
import uuid
from typing import Any

from app.ai.matching.models import AnalysisSettings
from app.ai.matching.report_models import ReportSettings


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def inputs_fingerprint(
    *,
    resume_extraction: Any,
    resume_embedding_model: str,
    job_extraction: Any,
    job_embedding_model: str,
    profile: Any,
) -> str:
    """A hash of what the analysis reads: the extractions (JSON-compatible data), the embedding
    models and the profile."""
    return _digest(
        {
            "resume": resume_extraction,
            "resume_model": resume_embedding_model,
            "job": job_extraction,
            "job_model": job_embedding_model,
            "profile": profile,
        }
    )


def cache_key(
    *,
    resume_id: uuid.UUID,
    job_id: uuid.UUID,
    prompt_name: str,
    prompt_version: int,
    llm_provider: str,
    llm_model: str,
    settings: AnalysisSettings,
    screener_prompt: str,
    suggestions_prompt: str,
    report_settings: ReportSettings,
    fingerprint: str,
) -> str:
    return _digest(
        {
            "resume_id": str(resume_id),
            "job_id": str(job_id),
            "prompt": f"{prompt_name}:{prompt_version}",
            "llm": f"{llm_provider}/{llm_model}",
            "settings": settings.model_dump(),
            "report": {
                "screener_prompt": screener_prompt,
                "suggestions_prompt": suggestions_prompt,
                "settings": report_settings.model_dump(),
            },
            "inputs": fingerprint,
        }
    )
