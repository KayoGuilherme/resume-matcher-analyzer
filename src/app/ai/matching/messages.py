"""The explanations the system writes itself, in the language of the job (Portuguese for `pt`,
English otherwise). Fixed templates: they take only the listed parameters, never other content.
"""

from collections.abc import Mapping

_EN = {
    "keyword_found": 'Found "{keyword}" in the resume.',
    "years_reached": (
        "The dates in the resume add up to {years:g} years of experience, which reaches the "
        "{required:g} years asked."
    ),
    "language_level_reached": (
        "The resume lists {language} at level {level}, which reaches the level asked."
    ),
    "language_listed": "The resume lists {language}.",
    "education_section_absent": "The resume has no education or certification section.",
    "no_similar_content": "Nothing in the resume is similar enough to this requirement.",
    "evidence_not_verbatim": (
        "The evidence given for this requirement could not be found in the resume, so it is "
        "treated as missing."
    ),
    "judge_met": "The resume passages show this requirement.",
    "judge_partial": "The resume passages show only part of this requirement.",
    "judge_missing": "The resume passages do not show this requirement.",
    "profile_stack": (
        'The resume does not show this, but your profile lists "{name}" ({years:g} years, '
        "level {level}). Add it to the resume, with where and how you used it."
    ),
    "profile_total_years": (
        "The resume does not show enough years, but your profile says {years:g} years coding in "
        "total. Make the dates and roles in the resume show them."
    ),
    "profile_language": (
        "The resume does not show this, but your profile lists {language} at level {level}. "
        "Add the language and its level to the resume."
    ),
    "profile_fact": (
        "The resume does not show this, but your profile mentions it. Add it to the resume."
    ),
}

_PT = {
    "keyword_found": 'Encontrado "{keyword}" no currículo.',
    "years_reached": (
        "As datas do currículo somam {years:g} anos de experiência, o que atinge os "
        "{required:g} anos pedidos."
    ),
    "language_level_reached": (
        "O currículo lista {language} no nível {level}, que atinge o nível pedido."
    ),
    "language_listed": "O currículo lista {language}.",
    "education_section_absent": "O currículo não tem seção de formação ou certificações.",
    "no_similar_content": "Nada no currículo é parecido o bastante com este requisito.",
    "evidence_not_verbatim": (
        "A evidência dada para este requisito não foi encontrada no currículo, então ele é "
        "tratado como ausente."
    ),
    "judge_met": "Os trechos do currículo mostram este requisito.",
    "judge_partial": "Os trechos do currículo mostram só parte deste requisito.",
    "judge_missing": "Os trechos do currículo não mostram este requisito.",
    "profile_stack": (
        'O currículo não mostra isto, mas o seu perfil lista "{name}" ({years:g} anos, '
        "nível {level}). Inclua no currículo, com onde e como você usou."
    ),
    "profile_total_years": (
        "O currículo não mostra anos suficientes, mas o seu perfil diz {years:g} anos "
        "programando no total. Faça as datas e os cargos do currículo mostrarem isso."
    ),
    "profile_language": (
        "O currículo não mostra isto, mas o seu perfil lista {language} no nível {level}. "
        "Inclua o idioma e o nível no currículo."
    ),
    "profile_fact": (
        "O currículo não mostra isto, mas o seu perfil menciona. Inclua no currículo."
    ),
}

TEMPLATES: Mapping[str, Mapping[str, str]] = {"en": _EN, "pt": _PT}
CODES = frozenset(_EN)


def explain(code: str, language: str, params: Mapping[str, str | float] | None = None) -> str:
    """The fixed explanation for `code` in the job's language (`pt`, else English)."""
    templates = TEMPLATES["pt" if language == "pt" else "en"]
    return templates[code].format(**(params or {}))
