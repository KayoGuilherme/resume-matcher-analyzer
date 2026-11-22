"""The report as Markdown, rendered from the same `Report` model as the JSON so they cannot drift.

Everything that did not come from a template here (reasons, suggested text, bullets, requirement
texts, keywords, parsing messages) is inserted through `plain()`: Markdown and HTML control
characters are escaped, links are broken and line breaks are collapsed, so such text can never add
a heading, a link, an image or markup to the document.
"""

import re
from collections.abc import Iterable

from app.ai.matching.report_models import Action, ActionKind, Report, Suggestion

_ESCAPED = re.compile(r"([\\`*_\[\]()#~|])")
_SCHEME = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*):(?=//)")
_WWW = re.compile(r"(?i)\b(www)\.")
_ZERO_WIDTH = "&#8203;"

_HEADINGS = {
    "en": {
        "title": "Screening report",
        "score": "Score",
        "screener": "Simulated screener",
        "actions": "What to do",
        "suggestions": "Rewrite suggestions",
        "keywords": "ATS keywords",
        "warnings": "Warnings",
        "fix_format": "Fix format and parsing issues",
        "add_from_profile": "Add what your profile proves",
        "real_gap": "Real gaps (rewriting cannot fix these)",
        "outcome": "Outcome",
        "weighted": "Weighted coverage",
        "penalty": "Penalties",
        "not_measured": "Nothing could be measured: the job has no requirement or keyword.",
        "decision": "Decision",
        "consistency": "Consistency",
        "agrees": "Agrees with the score",
        "differs": "Differs from the score",
        "run": "Run",
        "no_actions": "Nothing to fix.",
        "no_suggestions": "No suggestions.",
        "original": "Original",
        "suggested": "Suggested",
        "based_on": "Based on",
        "found": "Found",
        "missing": "Missing",
        "none": "none",
    },
    "pt": {
        "title": "Relatório de triagem",
        "score": "Pontuação",
        "screener": "Triagem simulada",
        "actions": "O que fazer",
        "suggestions": "Sugestões de reescrita",
        "keywords": "Palavras-chave de ATS",
        "warnings": "Avisos",
        "fix_format": "Corrigir problemas de formato e leitura",
        "add_from_profile": "Incluir o que seu perfil comprova",
        "real_gap": "Lacunas reais (reescrever não resolve)",
        "outcome": "Resultado",
        "weighted": "Cobertura ponderada",
        "penalty": "Penalidades",
        "not_measured": "Nada pôde ser medido: a vaga não tem requisito nem palavra-chave.",
        "decision": "Decisão",
        "consistency": "Consistência",
        "agrees": "Concorda com a pontuação",
        "differs": "Difere da pontuação",
        "run": "Execução",
        "no_actions": "Nada a corrigir.",
        "no_suggestions": "Nenhuma sugestão.",
        "original": "Original",
        "suggested": "Sugerido",
        "based_on": "Baseado em",
        "found": "Encontradas",
        "missing": "Ausentes",
        "none": "nenhuma",
    },
}
_KIND_ORDER: tuple[ActionKind, ...] = ("fix_format", "add_from_profile", "real_gap")


def plain(text: str) -> str:
    """`text` as inert plain text inside a Markdown line."""
    flat = " ".join(text.split())
    flat = flat.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    flat = _SCHEME.sub(lambda match: f"{match.group(1)}:{_ZERO_WIDTH}", flat)
    flat = _WWW.sub(lambda match: f"{match.group(1)}{_ZERO_WIDTH}.", flat)
    return _ESCAPED.sub(r"\\\1", flat)


def _list(items: Iterable[str]) -> list[str]:
    return [f"- {item}" for item in items]


def _score(report: Report, words: dict[str, str]) -> list[str]:
    score = report.score
    lines = [f"## {words['score']}", ""]
    if score.value is None or score.outcome is None:
        return [*lines, words["not_measured"], ""]
    lines.append(
        f"**{score.value:g} / 100** - {words['outcome']}: `{score.outcome}` "
        f"(pass >= {score.pass_threshold:g}, borderline >= {score.borderline_threshold:g})"
    )
    lines.append("")
    lines.append(f"{words['weighted']}: {score.weighted_coverage:g}")
    for coverage in score.coverages:
        value = "-" if coverage.value is None else f"{coverage.value:.0%}"
        lines.append(f"- {coverage.name}: {value} (weight {coverage.weight:g})")
    if score.penalties:
        lines += ["", f"{words['penalty']}: {score.total_penalty:g}"]
        lines += _list(f"{plain(p.code)} ({p.severity}): -{p.points:g}" for p in score.penalties)
    return [*lines, ""]


def _screener(report: Report, words: dict[str, str]) -> list[str]:
    screener = report.screener
    agreement = {True: words["agrees"], False: words["differs"], None: ""}[
        screener.agrees_with_score
    ]
    lines = [
        f"## {words['screener']}",
        "",
        f"{words['decision']}: `{screener.decision}` - {words['consistency']}: "
        f"{screener.consistency:g} ({len(screener.runs)})"
        + (f" - {agreement}" if agreement else ""),
        "",
    ]
    for number, run in enumerate(screener.runs, start=1):
        lines.append(f"{words['run']} {number}: `{run.decision}`")
        lines += [f"  - {plain(reason)}" for reason in run.reasons]
    return [*lines, ""]


def _action(action: Action) -> str:
    importance = f"[{action.importance}] " if action.importance else ""
    ids = f" ({', '.join(action.suggestion_ids)})" if action.suggestion_ids else ""
    return f"{action.priority}. {importance}{plain(action.text)}{ids}"


def _actions(report: Report, words: dict[str, str]) -> list[str]:
    lines = [f"## {words['actions']}", ""]
    if not report.actions:
        return [*lines, words["no_actions"], ""]
    for kind in _KIND_ORDER:
        of_kind = [action for action in report.actions if action.kind == kind]
        if of_kind:
            lines += [f"### {words[kind]}", "", *(_action(action) for action in of_kind), ""]
    return lines


def _suggestion(suggestion: Suggestion, words: dict[str, str]) -> list[str]:
    lines = [f"### {suggestion.id} - {plain(suggestion.target.text)}", ""]
    if suggestion.original is not None:
        lines.append(f"- {words['original']}: {plain(suggestion.original)}")
    lines.append(f"- {words['suggested']}: {plain(suggestion.text)}")
    lines.append(f"- {words['based_on']}: {plain(suggestion.based_on.text)}")
    return [*lines, ""]


def _suggestions(report: Report, words: dict[str, str]) -> list[str]:
    lines = [f"## {words['suggestions']}", ""]
    if not report.suggestions:
        return [*lines, words["no_suggestions"], ""]
    for suggestion in report.suggestions:
        lines += _suggestion(suggestion, words)
    return lines


def _keywords(report: Report, words: dict[str, str]) -> list[str]:
    coverage = report.ats_coverage
    found = ", ".join(plain(item.keyword) for item in coverage.found) or words["none"]
    missing = ", ".join(plain(item) for item in coverage.missing) or words["none"]
    return [
        f"## {words['keywords']}",
        "",
        f"- {words['found']}: {found}",
        f"- {words['missing']}: {missing}",
        "",
    ]


def render_markdown(report: Report) -> str:
    words = _HEADINGS["pt" if report.language == "pt" else "en"]
    lines = [f"# {words['title']}", "", f"> {plain(report.disclaimer)}", ""]
    lines += _score(report, words)
    lines += _screener(report, words)
    lines += _actions(report, words)
    lines += _suggestions(report, words)
    lines += _keywords(report, words)
    if report.warnings:
        lines += [f"## {words['warnings']}", ""]
        lines += _list(f"{plain(w.code)}: {w.count}" for w in report.warnings)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
