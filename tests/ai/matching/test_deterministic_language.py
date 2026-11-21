from datetime import date

from app.ai.extraction.models import LanguageSkill
from app.ai.matching.deterministic import Hints, Settled, check
from app.ai.matching.models import RequirementInput
from app.ai.matching.text import ResumeIndex
from tests.ai.matching.builders import kw, req, resume_input

TODAY = date(2026, 1, 15)


def _language(text: str, name: str) -> RequirementInput:
    return req(text, category="language", keywords=[kw(name, language=True)])


def _check(
    requirement: RequirementInput, text: str, *languages: tuple[str, str | None]
) -> Settled | Hints:
    resume = resume_input(
        text, languages=[LanguageSkill(name=name, level=level) for name, level in languages]
    )
    return check(requirement.requirement, ResumeIndex(resume), TODAY)


def test_fluent_english_is_met_by_english_advanced() -> None:
    outcome = _check(
        _language("Fluent English", "English"),
        "LANGUAGES\nPortuguese - Native\nEnglish - Advanced\n",
        ("English", "Advanced"),
    )

    assert isinstance(outcome, Settled) and outcome.verdict == "met"
    assert [e.quote for e in outcome.evidence] == ["English - Advanced"]
    assert outcome.code == "language_level_reached"


def test_portuguese_wording_is_read_too() -> None:
    outcome = _check(
        _language("Inglês avançado", "Inglês"),
        "IDIOMAS\nInglês: Avançado\n",
        ("Inglês", "Avançado"),
    )

    assert isinstance(outcome, Settled)
    assert [e.quote for e in outcome.evidence] == ["Inglês: Avançado"]


def test_a_language_with_no_level_asked_is_met_at_any_level() -> None:
    outcome = _check(
        _language("English", "English"), "LANGUAGES\nEnglish - Basic\n", ("English", "Basic")
    )

    assert isinstance(outcome, Settled)


def test_no_level_asked_and_no_level_written_is_still_met() -> None:
    outcome = _check(_language("English", "English"), "LANGUAGES\nEnglish\n", ("English", None))

    assert isinstance(outcome, Settled)


def test_a_level_that_is_too_low_settles_nothing() -> None:
    outcome = _check(
        _language("Fluent English", "English"),
        "LANGUAGES\nEnglish - Intermediate\n",
        ("English", "Intermediate"),
    )

    assert isinstance(outcome, Hints)
    assert outcome.resume_language_level == "Intermediate" and outcome.required_level == "C1"


def test_an_unreadable_resume_level_does_not_prove_a_level() -> None:
    outcome = _check(
        _language("Fluent English", "English"), "LANGUAGES\nEnglish - so-so\n", ("English", "so-so")
    )

    assert isinstance(outcome, Hints)


def test_a_language_the_resume_does_not_list_settles_nothing() -> None:
    outcome = _check(
        _language("Fluent English", "English"),
        "LANGUAGES\nPortuguese - Native\n",
        ("Portuguese", "Native"),
    )

    assert isinstance(outcome, Hints) and outcome.resume_language_level is None


def test_english_and_ingles_are_the_same_language() -> None:
    outcome = _check(
        _language("Fluent English", "English"), "IDIOMAS\nInglês - Fluente\n", ("Inglês", "Fluente")
    )

    assert isinstance(outcome, Settled)


def test_the_line_that_shows_the_level_is_preferred() -> None:
    text = "SUMMARY\nI teach English to colleagues\nLANGUAGES\nEnglish - Advanced\n"

    outcome = _check(_language("Fluent English", "English"), text, ("English", "Advanced"))

    assert isinstance(outcome, Settled)
    assert [e.quote for e in outcome.evidence] == ["English - Advanced"]


def test_a_language_requirement_without_keywords_settles_nothing() -> None:
    outcome = _check(req("Good communication in a foreign language", category="language"), "x")

    assert isinstance(outcome, Hints)


def test_a_listed_language_without_a_written_level_has_its_own_explanation_code() -> None:
    outcome = _check(_language("English", "English"), "LANGUAGES\nEnglish\n", ("English", None))

    assert isinstance(outcome, Settled) and outcome.code == "language_listed"
