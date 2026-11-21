"""Decide must-have vs nice-to-have from the posting's own wording, in English and Portuguese.

Code decides, the model is only a fallback: small models misread wording, and rules can be tested
with exact expectations. Order: (1) cue phrases in the requirement's own text, (2) the heading of
the section it sits in, (3) the model's judgment, (4) `must_have` flagged as unclear. All matching
is on text folded with `fold_text` (lowercase, no accents, single spaces).
"""

import re
import unicodedata
from typing import Literal

from app.ai.extraction.job_models import Priority
from app.ai.extraction.verify import comparison_key, normalize
from app.core.normalization import fold_text

Cue = Literal["must", "nice", "both"]
ModelPriority = Literal["must_have", "nice_to_have", "unclear"]

# A must-cue that is negated means "optional": "not required", "não é obrigatório".
_NEGATED_MUST = re.compile(
    r"\b(?:not|isn't|isnt|aren't|arent|no longer|never)(?: strictly)?"
    r" (?:required|mandatory|essential|necessary)\b"
    r"|\bnao (?:e |sao |eh )?(?:obrigatori(?:o|a|os|as)|necessari(?:o|a|os|as)"
    r"|imprescindiv(?:el|eis)|indispensav(?:el|eis))\b"
)
_NICE = re.compile(
    r"\bnice[- ]to[- ]have\b|\ba plus\b|\bum plus\b|\bbonus\b|\bpreferred\b|\bdesirable\b"
    r"|\bideally\b|\bdiferenci(?:al|ais)\b|\bdesejav(?:el|eis)\b|\bpreferencialmente\b"
)
_MUST = re.compile(
    r"\brequired\b|\bmust\b|\bmandatory\b|\bessential\b|\bobrigatori(?:o|a|os|as)\b"
    r"|\bnecessari(?:o|a|os|as)\b|\bimprescindiv(?:el|eis)\b|\bindispensav(?:el|eis)\b"
)

# Section headings. Nice is checked first: "Preferred qualifications" is nice, not must.
_NICE_HEADING = re.compile(
    r"\b(?:nice[- ]to[- ]have|preferred|desirable|bonus|plus|diferenci(?:al|ais)"
    r"|desejav(?:el|eis))\b"
)
_MUST_HEADING = re.compile(
    r"\b(?:requirements?|requisitos?|qualifications?|qualificacoes|must[- ]haves?|required"
    r"|mandatory|essential|obrigatori(?:o|a|os|as)|necessari(?:o|a|os))\b"
)
# Headings that decide nothing, but end the search: a bullet under "Benefits" must not inherit
# an earlier "Requirements".
_NEUTRAL_HEADING = re.compile(
    r"\b(?:about|sobre|benefits|beneficios|responsibilities|responsabilidades|atividades"
    r"|offer|oferecemos|role|vaga|salary|salario|compensation|apply|candidatar|perks|team"
    r"|equipe|company|empresa|stack|technologies|tecnologias|description|descricao)\b"
)

_BULLET = re.compile(r"^(?:[•●○◦▪■□▸►‣⁃·\-–—]\s|\*\s|\d+[.)]\s)")
_COPULAS = frozenset({"is", "are", "will", "should", "é", "são", "será", "deve"})
MAX_HEADING_CHARS = 80
MAX_COLONLESS_HEADING_WORDS = 4
MAX_COLON_HEADING_WORDS = 4


def cue_priority(text: str) -> Cue | None:
    """Cue phrases in `text`: only must, only nice (negated must counts as nice), both, or none."""
    folded = fold_text(text)
    negated = bool(_NEGATED_MUST.search(folded))
    remaining = _NEGATED_MUST.sub(" ", folded)
    nice = negated or bool(_NICE.search(remaining))
    must = bool(_MUST.search(remaining))
    if nice and must:
        return "both"
    if nice:
        return "nice"
    if must:
        return "must"
    return None


def locate_in_posting(source_text: str, posting: str) -> int | None:
    """The index in `posting` where `source_text` starts, ignoring whitespace and bullet symbols
    like the verbatim check does. None when it is not there."""
    needle = comparison_key(source_text)
    if not needle:
        return None
    chunks: list[str] = []
    starts: list[int] = []
    for position, char in enumerate(posting):
        if unicodedata.combining(char) and chunks:
            chunks[-1] += char
            continue
        chunks.append(char)
        starts.append(position)
    characters: list[str] = []
    origins: list[int] = []
    for chunk, start in zip(chunks, starts, strict=True):
        for kept in normalize(chunk):
            characters.append(kept)
            origins.append(start)
    found = "".join(characters).find(needle)
    return origins[found] if found >= 0 else None


def _heading_kind(line: str) -> Literal["must", "nice", "neutral"] | None:
    """What a line is as a heading, or None when it is not a heading at all."""
    raw = line.strip()
    if not raw or _BULLET.match(raw):
        return None
    text = raw.strip("#*_ \t")
    if not text or len(text) > MAX_HEADING_CHARS or text.endswith("."):
        return None
    colon = text.endswith(":")
    body = text.rstrip(":").strip()
    folded = fold_text(body)
    words = folded.split()
    if _NICE_HEADING.search(folded):
        kind: Literal["must", "nice", "neutral"] | None = "nice"
    elif _MUST_HEADING.search(folded):
        kind = "must"
    elif _NEUTRAL_HEADING.search(folded):
        kind = "neutral"
    else:
        kind = None
    if colon:
        # "Diferenciais:" is a heading; "Candidates should have:" is an introduction, not one.
        if kind is None:
            return "neutral" if len(words) <= MAX_COLON_HEADING_WORDS else None
        return kind if len(words) <= MAX_COLON_HEADING_WORDS + 2 else None
    if kind is None or len(words) > MAX_COLONLESS_HEADING_WORDS:
        return None
    if _COPULAS & set(body.lower().split()):
        return None  # "Python is required" is a sentence, not a heading
    return kind


def heading_priority(source_text: str, posting: str) -> Literal["must", "nice"] | None:
    """The priority given by the closest heading above `source_text` in the posting."""
    start = locate_in_posting(source_text, posting)
    if start is None:
        return None
    lines_above = posting[:start].splitlines()
    if posting[:start] and not posting[:start].endswith("\n"):
        lines_above = lines_above[:-1]  # the part of the line the text starts in
    for line in reversed(lines_above):
        kind = _heading_kind(line)
        if kind is None:
            continue
        return None if kind == "neutral" else kind
    return None


def resolve_priority(
    source_text: str, posting: str, model_priority: ModelPriority
) -> tuple[Priority, bool]:
    """(priority, priority_unclear) for one requirement. See the module docstring for the order."""
    own = cue_priority(source_text)
    if own == "both":
        return "must_have", True
    if own is not None:
        return ("must_have" if own == "must" else "nice_to_have"), False
    heading = heading_priority(source_text, posting)
    if heading is not None:
        return ("must_have" if heading == "must" else "nice_to_have"), False
    if model_priority != "unclear":
        return model_priority, False
    return "must_have", True
