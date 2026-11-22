"""Rewrite suggestions, and the deterministic check that keeps them honest.

An LLM proposes a reworded or new bullet for things the candidate can truthfully show. Whatever it
says is checked here, in code: a suggestion that adds a technology, a number or a year that is in
neither the resume nor the profile is rejected, and rejected text is only counted, never kept. The
model points at its source by number and the number is resolved here, so a pointer cannot be
mistyped or invented.

The check fails in the safe direction: it may reject an honest suggestion, never knowingly accept
an invented fact. Known limits: a lowercase technology name that no list contains and that has
no special shape, a name of one or two letters (`go`, `c`, `r`), and a number that is in the
source but used for a different claim.
"""

import logging
import re
import unicodedata
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.ai.extraction.job_models import Priority
from app.ai.extraction.models import ExtractionWarning, Resume
from app.ai.llm.base import LLMClient
from app.ai.matching.models import AnalysisResult, ProfileFacts, ProfileLanguage, ProfileStack
from app.ai.matching.report_models import (
    MissingKeyword,
    Suggestion,
    SuggestionBasis,
    SuggestionBatch,
    SuggestionSet,
    SuggestionTarget,
    TargetKind,
)
from app.ai.matching.technologies import COMMON_TECHNOLOGIES
from app.ai.matching.text import SearchableText, ats_forms, fold
from app.ai.prompts.loader import Prompt, load_prompt
from app.core.normalization import normalize_stack_name

logger = logging.getLogger(__name__)

PROMPT_NAME = "rewrite_suggestions"
MAX_SUGGESTION_CHARS = 400
MIN_TECHNOLOGY_CHARS = 3  # shorter names are too ambiguous to look for in prose

EMPTY_OR_UNCHANGED = "empty_or_unchanged"
TOO_LONG = "too_long"
UNSUPPORTED_TECHNOLOGY = "unsupported_technology"
UNSUPPORTED_NUMBER = "unsupported_number"
UNKNOWN_SOURCE = "unknown_source"

# --- numbers ----------------------------------------------------------------------------------

# 2 to 20 in English and Portuguese, folded. `one`, `um` and `uma` are left out on purpose: they
# are also the articles "a"/"an" and would reject honest sentences.
_NUMBER_WORDS: dict[str, str] = {
    **{
        word: str(number)
        for number, word in enumerate(
            (
                "two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                "fifteen sixteen seventeen eighteen nineteen twenty"
            ).split(),
            start=2,
        )
    },
    **{
        word: str(number)
        for number, word in enumerate(
            (
                "dois tres quatro cinco seis sete oito nove dez onze doze treze quatorze quinze "
                "dezesseis dezessete dezoito dezenove vinte"
            ).split(),
            start=2,
        )
    },
    "duas": "2",
    "catorze": "14",
    "dezasseis": "16",
    "dezassete": "17",
    "dezanove": "19",
}
_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*")
_THOUSANDS = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
_WORD = re.compile(r"[^\W\d_]+")


def _canonical_number(raw: str) -> str:
    if _THOUSANDS.match(raw):
        return str(int(re.sub(r"[.,]", "", raw)))
    text = raw.replace(",", ".")
    if "." in text:
        whole, _, fraction = text.partition(".")
        fraction = fraction.rstrip("0")
        return f"{int(whole)}.{fraction}" if fraction else str(int(whole))
    return str(int(text))


def numbers_in(text: str) -> set[str]:
    """The numbers a text states, in one canonical form: digits (`60%`, `2M`, `1,5`, `2019`) and
    number words from two to twenty in English and Portuguese. A digit inside a word (`b2b`,
    `k8s`) is not a number."""
    found = {_canonical_number(match.group()) for match in _NUMBER.finditer(text)}
    for word in _WORD.findall(text):
        number = _NUMBER_WORDS.get(fold(word))
        if number is not None:
            found.add(number)
    return found


# --- the profile as text ----------------------------------------------------------------------


def _years(value: float) -> str:
    return f"{value:g}"


def stack_statement(stack: ProfileStack) -> str:
    """A statement made only of the stack's own values."""
    return f"{stack.name}, {_years(stack.years)} years ({stack.level})"


def language_statement(language: ProfileLanguage) -> str:
    return f"{language.name} ({language.level})"


def profile_items(profile: ProfileFacts) -> list[str]:
    """The profile's stacks and languages (as statements made of their own values) and then its
    notable facts (as written): the numbered list a suggestion can be based on."""
    return [
        *(stack_statement(stack) for stack in profile.stacks),
        *(language_statement(language) for language in profile.languages),
        *profile.notable_facts,
    ]


def profile_text(profile: ProfileFacts) -> str:
    return "\n".join(
        [*profile_items(profile), f"{_years(profile.total_years_coding)} years of coding"]
    )


# --- the allowed corpus and the vocabulary ----------------------------------------------------


@dataclass(frozen=True)
class Corpus:
    """What a suggestion may state: the resume text and the profile, as text."""

    searchable: SearchableText
    numbers: frozenset[str]

    def contains(self, name: str) -> bool:
        """Whether the technology (or one of its aliases) is written in the corpus."""
        return bool(self.searchable.find(_forms(name)))


def build_corpus(resume_text: str, profile: ProfileFacts) -> Corpus:
    text = f"{resume_text}\n{profile_text(profile)}"
    return Corpus(SearchableText(text), frozenset(numbers_in(text)))


def _forms(name: str) -> list[str]:
    return ats_forms(normalize_stack_name(name))


def build_vocabulary(
    *,
    job_keywords: Iterable[str],
    ats_keywords: Iterable[str],
    resume_names: Iterable[str],
    profile: ProfileFacts,
) -> frozenset[str]:
    """Normalized technology names to look for in a suggestion: the job's own keywords (what an
    invention would most likely add), the candidate's stacks and skills, and the common ones."""
    names = [
        *job_keywords,
        *ats_keywords,
        *resume_names,
        *(stack.name for stack in profile.stacks),
        *COMMON_TECHNOLOGIES,
    ]
    normalized = (normalize_stack_name(name) for name in names)
    return frozenset(name for name in normalized if len(name) >= MIN_TECHNOLOGY_CHARS)


def technology_mentions(text: str, vocabulary: Iterable[str]) -> set[str]:
    """The vocabulary names (by their alias forms too) that the text mentions."""
    searchable = SearchableText(text)
    return {name for name in vocabulary if searchable.find(_forms(name))}


# --- names with a technology's shape ----------------------------------------------------------

_TOKEN = re.compile(r"[^\W\d_][\w+#.]*")
_GENERIC_ACRONYMS = frozenset({"api", "kpi", "roi", "sla", "okr", "pdf", "url", "faq", "cto"})
_SENTENCE_END = ".!?:;\n•-–—*"


def _is_sentence_start(text: str, start: int) -> bool:
    before = text[:start].rstrip(" \t")
    return not before or before[-1] in _SENTENCE_END


def _has_shape(token: str, text: str, start: int) -> bool:
    """A symbol (`+`, `#`, an inner `.`), an all-capital acronym of three letters or more, a
    CamelCase word, or a capitalized word that is not the first of its sentence."""
    if "+" in token or "#" in token:
        return True  # C++, C#
    if len(token) < MIN_TECHNOLOGY_CHARS:
        return False
    if token.endswith("s") and token[:-1].isupper():
        token = token[:-1]  # APIs, SDKs
        if len(token) < MIN_TECHNOLOGY_CHARS:
            return False
    if "." in token:
        parts = token.split(".")
        return not all(len(part) <= 2 for part in parts)  # `e.g`, `i.e` are not names
    if token.isupper() and sum(char.isalpha() for char in token) >= MIN_TECHNOLOGY_CHARS:
        return fold(token) not in _GENERIC_ACRONYMS
    letters = [char for char in token if char.isalpha()]
    if (
        token[0].isupper()
        and any(char.isupper() for char in letters[1:])
        and any(char.islower() for char in letters)
    ):
        return True  # CamelCase: PostgreSQL, FastAPI, GitHub
    return token[0].isupper() and not _is_sentence_start(text, start)


def shape_names(text: str) -> set[str]:
    """Tokens of the text that look like technology names, whether or not a list knows them."""
    names: set[str] = set()
    for match in _TOKEN.finditer(text):
        token = match.group().rstrip(".")
        if _has_shape(token, text, match.start()):
            names.add(token)
    return names


# --- the check --------------------------------------------------------------------------------


def check_suggestion(
    text: str, original: str | None, corpus: Corpus, vocabulary: Iterable[str]
) -> list[str]:
    """The reasons to reject a suggested text; empty when it states nothing the resume and the
    profile do not already state."""
    if not text.strip() or (original is not None and _plain(text) == _plain(original)):
        return [EMPTY_OR_UNCHANGED]
    reasons: list[str] = []
    if len(text) > MAX_SUGGESTION_CHARS:
        reasons.append(TOO_LONG)
    mentioned = technology_mentions(text, vocabulary)
    unknown_shapes = [name for name in shape_names(text) if not corpus.contains(name)]
    if any(not corpus.contains(name) for name in mentioned) or unknown_shapes:
        reasons.append(UNSUPPORTED_TECHNOLOGY)
    if numbers_in(text) - corpus.numbers:
        reasons.append(UNSUPPORTED_NUMBER)
    return reasons


def _plain(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


# --- the targets ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """Something to suggest a bullet for: a requirement or an ATS keyword."""

    kind: TargetKind
    text: str  # the requirement's text or the keyword
    requirement_id: uuid.UUID | None = None
    priority: Priority | None = None


_PRIORITY_RANK: dict[Priority, int] = {"must_have": 0, "nice_to_have": 1}


def select_targets(
    result: AnalysisResult, keywords: Sequence[MissingKeyword], max_suggestions: int
) -> list[Target]:
    """In order: requirements the profile proves but the resume omits, `partial` requirements,
    then missing ATS keywords that are profile stacks and belong to no targeted requirement. Must
    before nice within a group, the job's order kept, at most `max_suggestions`."""

    def requirements(verdict: str) -> list[Target]:
        chosen = [f for f in result.findings if f.verdict == verdict]
        chosen.sort(key=lambda finding: _PRIORITY_RANK[finding.priority])  # stable: job order
        return [
            Target("requirement", f.requirement_text, f.requirement_id, f.priority) for f in chosen
        ]

    by_requirement = [*requirements("in_profile_not_in_resume"), *requirements("partial")]
    covered = {target.requirement_id for target in by_requirement}
    by_keyword = [
        Target("keyword", entry.keyword)
        for entry in keywords
        if entry.in_profile and not covered & set(entry.requirement_ids)
    ]
    return [*by_requirement, *by_keyword][:max_suggestions]


# --- the sources the model may point to -------------------------------------------------------


def resume_bullets(resume: Resume) -> list[str]:
    """The experience bullets and then the project bullets, as written: the `B..` list."""
    return [
        *(bullet for experience in resume.experiences for bullet in experience.bullets),
        *(bullet for project in resume.projects for bullet in project.bullets),
    ]


def _numbered(prefix: str, items: Sequence[str]) -> str:
    return "\n".join(f"[{prefix}{number}] {item}" for number, item in enumerate(items, start=1))


def render_targets(targets: Sequence[Target]) -> str:
    lines = []
    for number, target in enumerate(targets, start=1):
        label = f"requirement ({target.priority})" if target.kind == "requirement" else "keyword"
        lines.append(f"[T{number}] {label}: {target.text}")
    return "\n".join(lines)


# --- the LLM step -----------------------------------------------------------------------------


def _reject(rejected: Counter[str], *reasons: str) -> None:
    rejected.update(reasons)


async def suggest(
    targets: Sequence[Target],
    resume: Resume,
    profile: ProfileFacts,
    corpus: Corpus,
    vocabulary: Iterable[str],
    llm: LLMClient,
    prompt: Prompt | None = None,
) -> tuple[SuggestionSet, int]:
    """Ask for suggestions in one call and keep only the ones that pass the check.

    Returns the set and the number of LLM calls made (0 when there is no target). A rejected
    suggestion adds one to the count of each of its reasons and its text is dropped. At most one
    suggestion is kept per target. Raises the LLM layer's errors.
    """
    if not targets:
        return SuggestionSet(accepted=[], rejected=[]), 0
    prompt = prompt or load_prompt(PROMPT_NAME)
    bullets = resume_bullets(resume)
    items = profile_items(profile)
    rendered = prompt.render(
        targets=render_targets(targets),
        bullets=_numbered("B", bullets),
        profile=_numbered("P", items),
    )
    batch = await llm.generate_structured(rendered.user, SuggestionBatch, system=rendered.system)

    accepted: list[Suggestion] = []
    rejected: Counter[str] = Counter()
    done: set[int] = set()
    vocabulary = frozenset(vocabulary)
    for answer in batch.suggestions:
        sources = bullets if answer.source == "resume" else items
        if not 1 <= answer.target <= len(targets) or not 1 <= answer.number <= len(sources):
            _reject(rejected, UNKNOWN_SOURCE)
            continue
        if answer.target in done:
            continue
        source = sources[answer.number - 1]
        original = source if answer.source == "resume" else None
        reasons = check_suggestion(answer.text, original, corpus, vocabulary)
        if reasons:
            _reject(rejected, *reasons)
            continue
        target = targets[answer.target - 1]
        done.add(answer.target)
        accepted.append(
            Suggestion(
                id=f"S{len(accepted) + 1}",
                target=SuggestionTarget(
                    kind=target.kind, requirement_id=target.requirement_id, text=target.text
                ),
                original=original,
                text=answer.text.strip(),
                based_on=SuggestionBasis(source=answer.source, text=source),
            )
        )
    logger.info(
        "suggestions finished",
        extra={
            "targets": len(targets),
            "accepted": len(accepted),
            "rejected": dict(rejected),
        },
    )
    return (
        SuggestionSet(
            accepted=accepted,
            rejected=[
                ExtractionWarning(code=code, count=n) for code, n in sorted(rejected.items())
            ],
        ),
        1,
    )
