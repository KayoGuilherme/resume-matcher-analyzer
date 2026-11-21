"""Step d: the profile cross-check. The most actionable finding: the resume does not show a
requirement, but the candidate's own profile says they have it.

No LLM and no resume reading here: the profile is structured data (stacks with years and level,
languages with a CEFR level, total years coding) plus free-text notable facts.
"""

from dataclasses import dataclass

from app.ai.extraction.job_models import JobRequirement
from app.ai.matching.levels import meets, parse_level
from app.ai.matching.messages import explain
from app.ai.matching.models import MAX_EVIDENCE, Evidence, ProfileFacts, RequirementFinding
from app.ai.matching.text import SearchableText, fold, keyword_forms, usable


@dataclass(frozen=True)
class _Support:
    evidence: list[Evidence]
    code: str
    params: dict[str, str | float]


def check(
    requirement: JobRequirement,
    finding: RequirementFinding,
    profile: ProfileFacts,
    language: str,
) -> RequirementFinding:
    """`finding` unchanged, or turned into `in_profile_not_in_resume` when the profile fully
    supports the requirement. Only `missing` and `partial` findings are looked at."""
    if finding.verdict not in ("missing", "partial"):
        return finding
    support = _support(requirement, profile)
    if support is None:
        return finding
    return finding.model_copy(
        update={
            "verdict": "in_profile_not_in_resume",
            "decided_by": "profile",
            "evidence": [*finding.evidence, *support.evidence],  # resume quotes stay in front
            "explanation": explain(support.code, language, support.params),
        }
    )


def _support(requirement: JobRequirement, profile: ProfileFacts) -> _Support | None:
    is_language = requirement.category == "language"
    forms = [
        form
        for keyword in requirement.keywords
        for form in keyword_forms(keyword, language=is_language)
    ]
    if is_language:
        return _language(requirement, profile, forms)
    return (
        _stacks(requirement, profile, forms)
        or _total_years(requirement, profile, forms)
        or _facts(requirement, profile, forms)
    )


def _stacks(
    requirement: JobRequirement, profile: ProfileFacts, forms: list[str]
) -> _Support | None:
    evidence: list[Evidence] = []
    first: dict[str, str | float] | None = None
    for stack in profile.stacks:
        if fold(stack.name) not in forms or stack.level == "learning":
            continue
        if requirement.min_years is not None and stack.years < requirement.min_years:
            continue
        evidence.append(
            Evidence(source="profile", quote=f"{stack.name}: {stack.years:g} years, {stack.level}")
        )
        first = first or {"name": stack.name, "years": stack.years, "level": stack.level}
    if not evidence or first is None:
        return None
    return _Support(evidence[:MAX_EVIDENCE], "profile_stack", first)


def _total_years(
    requirement: JobRequirement, profile: ProfileFacts, forms: list[str]
) -> _Support | None:
    if forms or requirement.min_years is None:
        return None
    if profile.total_years_coding < requirement.min_years:
        return None
    years = profile.total_years_coding
    return _Support(
        [Evidence(source="profile", quote=f"{years:g} years coding in total")],
        "profile_total_years",
        {"years": years},
    )


def _language(
    requirement: JobRequirement, profile: ProfileFacts, forms: list[str]
) -> _Support | None:
    required = parse_level(requirement.text)
    for language in profile.languages:
        if fold(language.name) in forms and meets(language.level, required):
            return _Support(
                [Evidence(source="profile", quote=f"{language.name}: {language.level}")],
                "profile_language",
                {"language": language.name, "level": language.level},
            )
    return None


def _facts(requirement: JobRequirement, profile: ProfileFacts, forms: list[str]) -> _Support | None:
    if requirement.min_years is not None or not forms:
        return None
    matching = [fact for fact in profile.notable_facts if usable(SearchableText(fact).find(forms))]
    if not matching:
        return None
    return _Support(
        [Evidence(source="profile", quote=fact) for fact in matching[:MAX_EVIDENCE]],
        "profile_fact",
        {},
    )
