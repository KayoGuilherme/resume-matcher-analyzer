"""Check that extracted text really is in the resume. Rewritten text is never kept.

The comparison ignores all whitespace (PDF line wraps and hyphenation otherwise cause false
rejections), a leading bullet symbol and Unicode compatibility variants (ligatures). Words,
accents and case stay exact, so paraphrases and translations fail.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.ai.extraction.models import ExtractedResume

ItemKind = Literal["experience_bullet", "project_bullet", "skills_line"]

_LEADING_SYMBOLS = re.compile(r"^[\s•●○◦▪■□▸►‣⁃·*\-–—]+")
_WHITESPACE = re.compile(r"[\s​‌‍﻿]+")


@dataclass(frozen=True)
class Item:
    kind: ItemKind
    text: str


def normalize(text: str) -> str:
    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", text))


def comparison_key(item: str) -> str:
    """What `item` is compared as: no leading bullet symbol, no whitespace, NFKC."""
    return normalize(_LEADING_SYMBOLS.sub("", unicodedata.normalize("NFKC", item)))


def is_verbatim(item: str, normalized_resume_text: str) -> bool:
    """Whether `item` appears in the resume text (already passed through `normalize`)."""
    needle = comparison_key(item)
    return bool(needle) and needle in normalized_resume_text


def _items(extracted: ExtractedResume) -> list[Item]:
    items = [Item("skills_line", line.text) for line in extracted.skills]
    for experience in extracted.experiences:
        items += [Item("experience_bullet", bullet) for bullet in experience.bullets]
    for project in extracted.projects:
        items += [Item("project_bullet", bullet) for bullet in project.bullets]
    return items


def find_unverified(extracted: ExtractedResume, resume_text: str) -> list[Item]:
    """The bullets and skills lines that are not in the resume text."""
    normalized = normalize(resume_text)
    return [item for item in _items(extracted) if not is_verbatim(item.text, normalized)]


def drop_unverified(extracted: ExtractedResume, resume_text: str) -> tuple[ExtractedResume, int]:
    """A copy without the unverified items, and how many were removed."""
    normalized = normalize(resume_text)
    dropped = 0

    def keep(texts: list[str]) -> list[str]:
        nonlocal dropped
        kept = [text for text in texts if is_verbatim(text, normalized)]
        dropped += len(texts) - len(kept)
        return kept

    skills = [line for line in extracted.skills if keep([line.text])]
    experiences = [
        experience.model_copy(update={"bullets": keep(experience.bullets)})
        for experience in extracted.experiences
    ]
    projects = [
        project.model_copy(update={"bullets": keep(project.bullets)})
        for project in extracted.projects
    ]
    cleaned = extracted.model_copy(
        update={"skills": skills, "experiences": experiences, "projects": projects}
    )
    return cleaned, dropped
