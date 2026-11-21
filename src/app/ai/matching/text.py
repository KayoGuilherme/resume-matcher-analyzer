"""Literal matching of keywords in resume text, and the passages that show a match.

A keyword is found when one of its forms (the name, its synonyms and the known aliases of each)
appears as a whole term, ignoring case and accents. "Whole term" means the characters before and
after are not letters, digits, `+` or `#`: `java` is not in `javascript`, `c` is not in `c++` or
`c#`, while `node.js`, `c++` and `.net` are matched with their symbols. The search runs on a folded
copy of the text and every hit is mapped back to the original wording, because quotes must be the
resume's own words.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from app.ai.extraction.job_models import Keyword
from app.ai.extraction.models import Experience
from app.ai.extraction.verify import normalize
from app.ai.matching.models import ChunkInput, ResumeInput
from app.core.normalization import aliases_of

AMBIGUOUS_MAX_LENGTH = 2  # forms this short (`go`, `c`, `r`) never settle a requirement alone
MAX_QUOTE_CHARS = 400
_CONTEXT_BEFORE = 150


@dataclass(frozen=True)
class Match:
    start: int  # in the original text
    end: int
    text: str  # as written in the original text
    form: str

    @property
    def ambiguous(self) -> bool:
        return len(self.form) <= AMBIGUOUS_MAX_LENGTH


def fold(text: str) -> str:
    """Lowercase, accent-free text with single spaces (the form that is searched)."""
    return _fold_with_map(text)[0].strip()


def _fold_with_map(text: str) -> tuple[str, list[int]]:
    """The folded text and, for each folded character, the index of its original character."""
    folded: list[str] = []
    origin: list[int] = []
    in_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if not in_space:
                folded.append(" ")
                origin.append(index)
                in_space = True
            continue
        in_space = False
        for part in unicodedata.normalize("NFKD", char):
            for lowered in part.lower():
                if not unicodedata.combining(lowered):
                    folded.append(lowered)
                    origin.append(index)
    return "".join(folded), origin


@lru_cache(maxsize=2048)
def _pattern(form: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w+#]){re.escape(form)}(?![\w+#])")


class SearchableText:
    """A text folded once, searchable for many keywords."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._folded, self._origin = _fold_with_map(text)

    def find(self, forms: Sequence[str]) -> list[Match]:
        """Every whole-term occurrence of any of the (folded) forms, in text order, one per span."""
        found: dict[tuple[int, int], Match] = {}
        for form in forms:
            if not form:
                continue
            for hit in _pattern(form).finditer(self._folded):
                start = self._origin[hit.start()]
                end = self._origin[hit.end() - 1] + 1
                found.setdefault((start, end), Match(start, end, self.text[start:end], form))
        return [found[span] for span in sorted(found)]


def _unique(forms: list[str]) -> list[str]:
    result: list[str] = []
    for form in forms:
        folded = fold(form)
        if folded and folded not in result:
            result.append(folded)
    return result


def keyword_forms(keyword: Keyword, *, language: bool = False) -> list[str]:
    """Folded forms of a requirement keyword: name, synonyms and the aliases of each."""
    names = [keyword.normalized, *keyword.synonyms]
    forms: list[str] = []
    for name in names:
        forms += [name, *aliases_of(name, language=language)]
    return _unique(forms)


def ats_forms(name: str) -> list[str]:
    """Folded forms of an ATS keyword: the name and its known aliases."""
    return _unique([name, *aliases_of(name)])


def usable(matches: Sequence[Match]) -> list[Match]:
    """The matches that may settle a requirement: the ambiguous short ones are left out."""
    return [match for match in matches if not match.ambiguous]


def _window(text: str, start: int, end: int, limit: int = MAX_QUOTE_CHARS) -> str:
    """`text` if it is short, else a stretch of at most `limit` characters that holds the match.

    Any stretch of the text is still verbatim, so it is a valid quote."""
    if len(text) <= limit:
        return text.strip()
    begin = max(0, min(start - _CONTEXT_BEFORE, len(text) - limit))
    return text[begin : begin + limit].strip()


def _line_around(text: str, start: int, end: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return line_start, len(text) if line_end == -1 else line_end


class ResumeIndex:
    """The resume text and its chunks folded once, for the keyword matches of every requirement."""

    def __init__(self, resume: ResumeInput) -> None:
        self.input = resume
        self.text = SearchableText(resume.text)
        self.chunks = [
            (chunk, SearchableText(chunk.text))
            for chunk in sorted(resume.chunks, key=lambda chunk: chunk.position)
        ]
        self._experience_texts = [
            (
                experience,
                SearchableText(experience.title),
                [SearchableText(b) for b in experience.bullets],
            )
            for experience in resume.resume.experiences
        ]

    def chunks_matching(
        self, forms: Sequence[str], *, allow_ambiguous: bool = False
    ) -> list[ChunkInput]:
        """The chunks, in resume order, that contain one of the forms."""
        return [
            chunk
            for chunk, searchable in self.chunks
            if self._hits(searchable, forms, allow_ambiguous)
        ]

    def experiences_mentioning(self, forms: Sequence[str]) -> list[tuple[Experience, list[str]]]:
        """The experiences whose title or bullets contain one of the forms (ambiguous short names
        select nothing), each with the bullets that contain it, in resume order."""
        selected: list[tuple[Experience, list[str]]] = []
        for experience, title, bullets in self._experience_texts:
            shown = [
                bullet.text
                for bullet in bullets
                if self._hits(bullet, forms, allow_ambiguous=False)
            ]
            if shown or self._hits(title, forms, allow_ambiguous=False):
                selected.append((experience, shown))
        return selected

    def passages(
        self, forms: Sequence[str], limit: int, *, allow_ambiguous: bool = False
    ) -> list[str]:
        """Up to `limit` quotes that show the forms: the chunks that contain them first, then the
        resume's own lines where the match is outside every chunk (education, languages...)."""
        quotes: list[str] = []
        taken: list[str] = []  # normalized text of what is already quoted

        def add(quote: str) -> None:
            key = normalize(quote)
            if key and not any(key in other or other in key for other in taken):
                quotes.append(quote)
                taken.append(key)

        for chunk, searchable in self.chunks:
            hits = self._hits(searchable, forms, allow_ambiguous)
            if hits:
                add(_window(chunk.text, hits[0].start, hits[0].end))
        for hit in self._hits(self.text, forms, allow_ambiguous):
            line_start, line_end = _line_around(self.input.text, hit.start, hit.end)
            line = self.input.text[line_start:line_end]
            add(_window(line, hit.start - line_start, hit.end - line_start))
        return quotes[:limit]

    def lines_containing(self, terms: Sequence[str], limit: int) -> list[str]:
        """The resume's own lines, in text order, that contain one of the (folded) terms."""
        lines: list[str] = []
        seen: set[tuple[int, int]] = set()
        for hit in self.text.find(terms):
            span = _line_around(self.input.text, hit.start, hit.end)
            if span in seen:
                continue
            seen.add(span)
            line = self.input.text[span[0] : span[1]].strip()
            if line:
                lines.append(_window(line, hit.start - span[0], hit.end - span[0]))
        return lines[:limit]

    @staticmethod
    def _hits(
        searchable: SearchableText, forms: Sequence[str], allow_ambiguous: bool
    ) -> list[Match]:
        matches = searchable.find(forms)
        return matches if allow_ambiguous else usable(matches)
