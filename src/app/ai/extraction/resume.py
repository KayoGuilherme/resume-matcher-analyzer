"""Extract a structured `Resume` from resume text, using any `LLMClient`.

Validation, the correction round and dropping unverifiable text are the same for every
provider. Nothing here logs resume text.
"""

import logging
import uuid
from datetime import datetime

from app.ai.extraction.experience import total_experience_months
from app.ai.extraction.models import (
    Experience,
    ExtractedResume,
    ExtractionResult,
    ExtractionWarning,
    Project,
    Resume,
)
from app.ai.extraction.verify import Item, drop_unverified, find_unverified
from app.ai.llm.base import LLMClient
from app.ai.prompts.loader import Prompt, load_prompt

logger = logging.getLogger(__name__)

PROMPT_NAME = "resume_extraction"


def _corrections_block(unverified: list[Item]) -> str:
    listed = "\n".join(f"- {item.text}" for item in unverified)
    return (
        "\nCorrection needed: these items from your previous answer are not in the resume text "
        "exactly as written. Answer again in full. Copy each of them exactly from the resume, or "
        f"leave it out:\n{listed}\n"
    )


def _with_ids(extracted: ExtractedResume) -> Resume:
    return Resume(
        summary=extracted.summary,
        skills=extracted.skills,
        experiences=[
            Experience(**experience.model_dump(), id=uuid.uuid4())
            for experience in extracted.experiences
        ],
        education=extracted.education,
        languages=extracted.languages,
        certifications=extracted.certifications,
        projects=[
            Project(**project.model_dump(), id=uuid.uuid4()) for project in extracted.projects
        ],
    )


async def extract_resume(
    llm: LLMClient, resume_text: str, now: datetime, prompt: Prompt | None = None
) -> ExtractionResult:
    """Ask the model, verify every bullet and skills line against `resume_text`, correct once,
    drop what is still not verbatim, assign ids and compute the experience total in code."""
    prompt = prompt or load_prompt(PROMPT_NAME)
    rendered = prompt.render(resume_text=resume_text, corrections="")
    extracted = await llm.generate_structured(
        rendered.user, ExtractedResume, system=rendered.system
    )

    unverified = find_unverified(extracted, resume_text)
    corrected = False
    if unverified:
        corrected = True
        rendered = prompt.render(
            resume_text=resume_text, corrections=_corrections_block(unverified)
        )
        extracted = await llm.generate_structured(
            rendered.user, ExtractedResume, system=rendered.system
        )
    extracted, dropped = drop_unverified(extracted, resume_text)

    total = total_experience_months(extracted.experiences, now.date())
    warnings: list[ExtractionWarning] = []
    if dropped:
        warnings.append(ExtractionWarning(code="dropped_unverified_items", count=dropped))
    if total.skipped:
        warnings.append(
            ExtractionWarning(code="experiences_without_valid_dates", count=total.skipped)
        )

    logger.info(
        "resume extracted",
        extra={
            "experience_count": len(extracted.experiences),
            "dropped_items": dropped,
            "correction_round": corrected,
            "warning_codes": [warning.code for warning in warnings],
        },
    )
    return ExtractionResult(
        resume=_with_ids(extracted),
        total_experience_months=total.months,
        total_experience_years=total.years,
        warnings=warnings,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        llm_provider=llm.provider,
        llm_model=llm.model,
        extracted_at=now,
    )
