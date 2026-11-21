import string

import pytest

from app.ai.matching.messages import CODES, TEMPLATES, explain

ALLOWED_PARAMS = {"keyword", "years", "required", "language", "level", "name"}


def test_every_code_exists_in_both_languages() -> None:
    assert set(TEMPLATES["en"]) == set(TEMPLATES["pt"]) == set(CODES)


def test_the_codes_the_steps_use_are_all_defined() -> None:
    used = {
        "keyword_found", "years_reached", "language_level_reached", "language_listed",
        "education_section_absent", "no_similar_content", "evidence_not_verbatim",
        "judge_met", "judge_partial", "judge_missing", "profile_stack",
        "profile_total_years", "profile_language", "profile_fact",
    }  # fmt: skip

    assert used == set(CODES)


def test_templates_use_only_the_allowed_parameters() -> None:
    for templates in TEMPLATES.values():
        for template in templates.values():
            fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
            assert fields <= ALLOWED_PARAMS


def test_a_portuguese_job_gets_portuguese_text_and_everything_else_english() -> None:
    assert explain("no_similar_content", "pt").startswith("Nada no currículo")
    assert explain("no_similar_content", "en").startswith("Nothing in the resume")
    assert explain("no_similar_content", "other") == explain("no_similar_content", "en")


def test_parameters_are_inserted() -> None:
    text = explain("years_reached", "en", {"years": 3.4, "required": 3.0})

    assert "3.4 years" in text and "3 years asked" in text
    assert explain("keyword_found", "en", {"keyword": "K8s"}) == 'Found "K8s" in the resume.'
    assert 'lists "docker"' in explain(
        "profile_stack", "en", {"name": "docker", "years": 3, "level": "working"}
    )


def test_a_missing_parameter_is_an_error_not_a_silent_blank() -> None:
    with pytest.raises(KeyError):
        explain("keyword_found", "en", {})


def test_no_template_mentions_a_score() -> None:
    for templates in TEMPLATES.values():
        assert not any("score" in text.lower() for text in templates.values())


def test_no_template_is_empty() -> None:
    assert all(text.strip() for templates in TEMPLATES.values() for text in templates.values())
