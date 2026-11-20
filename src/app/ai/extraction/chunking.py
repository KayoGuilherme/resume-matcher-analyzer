"""Split a resume into chunks: one per experience bullet, project bullet and skills line."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.ai.extraction.models import Resume

ChunkSection = Literal["experience", "projects", "skills"]


class ChunkDraft(BaseModel):
    """A piece of the resume with its provenance. `text` is the resume's own wording."""

    model_config = ConfigDict(frozen=True)

    section: ChunkSection
    experience_id: uuid.UUID | None  # only experience bullets belong to an experience
    position: int
    text: str


def build_chunks(resume: Resume) -> list[ChunkDraft]:
    """Skills lines, then experience bullets, then project bullets, in resume order.

    Summary, education, languages and certifications are not chunked. Empty text is skipped.
    """
    sources: list[tuple[ChunkSection, uuid.UUID | None, str]] = [
        ("skills", None, line.text) for line in resume.skills
    ]
    for experience in resume.experiences:
        sources += [("experience", experience.id, bullet) for bullet in experience.bullets]
    for project in resume.projects:
        sources += [("projects", None, bullet) for bullet in project.bullets]

    chunks: list[ChunkDraft] = []
    for section, experience_id, text in sources:
        if text.strip():
            chunks.append(
                ChunkDraft(
                    section=section, experience_id=experience_id, position=len(chunks), text=text
                )
            )
    return chunks
