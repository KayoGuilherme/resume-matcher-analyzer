"""The prioritized actions of a report, in three kinds and in this order:

1. `fix_format`: parsing issues of the resume, most severe first.
2. `add_from_profile`: things the profile proves and the resume omits, with the suggestions that
   address them.
3. `real_gap`: what neither the resume nor the profile shows. Said plainly: rewriting cannot fix
   it, and it must not be claimed unless it is true.

The texts are fixed templates (English, Portuguese for a Portuguese job), never LLM output. A
pure function of the analysis result and the stored report.
"""

from collections.abc import Sequence

from app.ai.extraction.job_models import Priority
from app.ai.matching.models import AnalysisResult, RequirementFinding
from app.ai.matching.report_models import Action, MissingKeyword, StoredReport, Suggestion

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_PRIORITY_ORDER: dict[Priority, int] = {"must_have": 0, "nice_to_have": 1}

_TEMPLATES = {
    "en": {
        "profile_requirement": (
            'Your profile shows this, but your resume does not: "{subject}". Add it to your '
            "resume with a bullet that states it, as long as it is true."
        ),
        "profile_keyword": (
            'The job asks for "{subject}" and your profile lists it, but your resume never '
            "mentions it. Name it in the bullet where you used it, as long as it is true."
        ),
        "gap_missing": (
            'Neither your resume nor your profile shows: "{subject}". Rewriting cannot fix '
            "this: it is a real gap in skills, experience or evidence. Do not add it to your "
            "resume unless it is true; consider learning it, building something with it, or "
            "applying to roles that do not require it."
        ),
        "gap_partial": (
            'Your resume shows only part of: "{subject}", and your profile does not show '
            "more. Rewriting cannot fix the missing part: it is a real gap in skills, "
            "experience or evidence. Do not claim more than is true."
        ),
        "gap_keyword": (
            'The job\'s keyword "{subject}" is in neither your resume nor your profile. '
            "Rewriting cannot fix this: it is a real gap. Do not add it unless it is true."
        ),
    },
    "pt": {
        "profile_requirement": (
            'Seu perfil mostra isto, mas seu currículo não: "{subject}". Inclua no currículo '
            "um item que diga isso, desde que seja verdade."
        ),
        "profile_keyword": (
            'A vaga pede "{subject}" e seu perfil lista essa tecnologia, mas o currículo nunca '
            "a menciona. Cite-a no item em que você a usou, desde que seja verdade."
        ),
        "gap_missing": (
            'Nem seu currículo nem seu perfil mostram: "{subject}". Reescrever não resolve '
            "isso: é uma lacuna real de habilidade, experiência ou comprovação. Não inclua no "
            "currículo a menos que seja verdade; considere aprender, construir algo com isso "
            "ou se candidatar a vagas que não exijam."
        ),
        "gap_partial": (
            'Seu currículo mostra só parte de: "{subject}", e seu perfil não mostra mais. '
            "Reescrever não resolve a parte que falta: é uma lacuna real de habilidade, "
            "experiência ou comprovação. Não afirme mais do que é verdade."
        ),
        "gap_keyword": (
            'A palavra-chave "{subject}" da vaga não está no seu currículo nem no seu perfil. '
            "Reescrever não resolve isso: é uma lacuna real. Não inclua a menos que seja "
            "verdade."
        ),
    },
}


def _text(language: str, name: str, subject: str) -> str:
    return _TEMPLATES["pt" if language == "pt" else "en"][name].format(subject=subject)


def _suggestion_ids(
    suggestions: Sequence[Suggestion],
    *,
    requirement: RequirementFinding | None = None,
    keyword: str | None = None,
) -> list[str]:
    ids: list[str] = []
    for suggestion in suggestions:
        target = suggestion.target
        if requirement is not None and target.requirement_id == requirement.requirement_id:
            ids.append(suggestion.id)
        elif keyword is not None and target.kind == "keyword" and target.text == keyword:
            ids.append(suggestion.id)
    return ids


def _requirement_action(
    finding: RequirementFinding, kind: str, template: str, language: str, ids: list[str]
) -> Action:
    return Action.model_validate(
        {
            "priority": 0,
            "kind": kind,
            "importance": finding.priority,
            "requirement_id": finding.requirement_id,
            "requirement_text": finding.requirement_text,
            "text": _text(language, template, finding.requirement_text),
            "suggestion_ids": ids,
        }
    )


def _keyword_action(
    entry: MissingKeyword, kind: str, template: str, language: str, ids: list[str]
) -> Action:
    return Action.model_validate(
        {
            "priority": 0,
            "kind": kind,
            "keyword": entry.keyword,
            "text": _text(language, template, entry.keyword),
            "suggestion_ids": ids,
        }
    )


def _by_importance(findings: Sequence[RequirementFinding]) -> list[RequirementFinding]:
    return sorted(findings, key=lambda finding: _PRIORITY_ORDER[finding.priority])  # stable


def build_actions(result: AnalysisResult, stored: StoredReport) -> list[Action]:
    language = stored.language
    suggestions = stored.suggestions.accepted
    actions: list[Action] = []

    for issue in sorted(
        stored.issues, key=lambda item: (_SEVERITY_ORDER[item.severity], item.code)
    ):
        actions.append(
            Action(
                priority=0,
                kind="fix_format",
                issue_code=issue.code,
                issue_severity=issue.severity,
                text=issue.message,
            )
        )

    from_profile = [f for f in result.findings if f.verdict == "in_profile_not_in_resume"]
    for finding in _by_importance(from_profile):
        ids = _suggestion_ids(suggestions, requirement=finding)
        actions.append(
            _requirement_action(finding, "add_from_profile", "profile_requirement", language, ids)
        )
    profile_ids = {f.requirement_id for f in from_profile}
    for entry in stored.missing_keywords:
        if entry.in_profile and not profile_ids & set(entry.requirement_ids):
            ids = _suggestion_ids(suggestions, keyword=entry.keyword)
            actions.append(
                _keyword_action(entry, "add_from_profile", "profile_keyword", language, ids)
            )

    gaps = [f for f in result.findings if f.verdict in ("missing", "partial")]
    for finding in _by_importance(gaps):
        template = "gap_missing" if finding.verdict == "missing" else "gap_partial"
        ids = _suggestion_ids(suggestions, requirement=finding)
        actions.append(_requirement_action(finding, "real_gap", template, language, ids))
    with_action = profile_ids | {f.requirement_id for f in gaps}
    for entry in stored.missing_keywords:
        if not entry.in_profile and not with_action & set(entry.requirement_ids):
            actions.append(_keyword_action(entry, "real_gap", "gap_keyword", language, []))

    return [action.model_copy(update={"priority": n}) for n, action in enumerate(actions, start=1)]
