"""Language levels on the scale A1 < A2 < B1 < B2 < C1 < C2 < native, read from English and
Portuguese words and CEFR codes. Pure functions.
"""

import re
from typing import get_args

from app.ai.matching.models import LanguageLevel
from app.core.normalization import fold_text

SCALE: tuple[LanguageLevel, ...] = get_args(LanguageLevel)

# Folded (lowercase, accent-free) phrases. The longest phrase wins over the words inside it.
_PHRASES: dict[str, LanguageLevel] = {
    "beginner": "A1",
    "iniciante": "A1",
    "basic": "A2",
    "elementary": "A2",
    "basico": "A2",
    "elementar": "A2",
    "intermediate": "B1",
    "intermediario": "B1",
    "upper-intermediate": "B2",
    "upper intermediate": "B2",
    "intermediario avancado": "B2",
    "advanced": "C1",
    "avancado": "C1",
    "fluent": "C1",
    "fluente": "C1",
    "proficient": "C1",
    "proficiente": "C1",
    "bilingual": "C2",
    "bilingue": "C2",
    "native": "native",
    "nativo": "native",
    "nativa": "native",
    **{code.lower(): code for code in ("A1", "A2", "B1", "B2", "C1", "C2")},
}
_ORDERED = sorted(_PHRASES, key=len, reverse=True)
_PATTERNS = {
    phrase: re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])") for phrase in _ORDERED
}


def rank(level: LanguageLevel) -> int:
    return SCALE.index(level)


def parse_level(text: str) -> LanguageLevel | None:
    """The highest level named in `text`, or None when it names none."""
    remaining = fold_text(text)
    best: LanguageLevel | None = None
    for phrase in _ORDERED:
        pattern = _PATTERNS[phrase]
        if pattern.search(remaining):
            level = _PHRASES[phrase]
            if best is None or rank(level) > rank(best):
                best = level
            remaining = pattern.sub(" ", remaining)  # its words are not read again
    return best


def meets(have: LanguageLevel | None, need: LanguageLevel | None) -> bool:
    """Whether a candidate's level reaches the asked one (no level asked: any level counts, but
    a level that is unknown never proves a level that is asked)."""
    if need is None:
        return True
    return have is not None and rank(have) >= rank(need)
