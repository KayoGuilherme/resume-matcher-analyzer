from app.ai.extraction.job import (
    build_posting_text,
    dedupe_requirements,
    normalize_ats_keywords,
    normalize_keywords,
)
from tests.ai.extraction.job_builders import keyword, requirement


def test_a_stack_alias_is_normalized_and_the_given_name_is_kept() -> None:
    (result,) = normalize_keywords(requirement("x", keywords=[keyword("Postgres", "PostgreSQL")]))

    assert (result.name, result.normalized, result.synonyms) == ("Postgres", "postgresql", [])


def test_a_language_requirement_uses_the_language_aliases() -> None:
    req = requirement(
        "Português fluente", category="language", keywords=[keyword("Português", "PT")]
    )

    (result,) = normalize_keywords(req)

    assert (result.normalized, result.synonyms) == ("portuguese", [])


def test_the_same_alias_is_not_a_language_alias_for_a_skill() -> None:
    (result,) = normalize_keywords(requirement("x", category="skill", keywords=[keyword("PT")]))

    assert result.normalized == "pt"


def test_synonyms_are_normalized_deduplicated_and_never_repeat_the_keyword() -> None:
    req = requirement(
        "x", keywords=[keyword("JavaScript", "JS", "javascript", "Javascript", "ES6")]
    )

    (result,) = normalize_keywords(req)

    assert result.synonyms == ["es6"]


def test_new_aliases_apply_to_keywords() -> None:
    (result,) = normalize_keywords(
        requirement("x", keywords=[keyword("K8s", "Kubernetes", "Kube")])
    )

    assert (result.normalized, result.synonyms) == ("kubernetes", ["kube"])


def test_blank_and_duplicate_keywords_are_dropped() -> None:
    req = requirement(
        "x",
        keywords=[keyword("Docker"), keyword("  "), keyword("docker", "container"), keyword("Go")],
    )

    result = normalize_keywords(req)

    assert [k.normalized for k in result] == ["docker", "go"]
    assert result[0].synonyms == []  # the duplicate's synonyms are not merged


def test_ats_keywords_are_normalized_and_deduplicated_in_order() -> None:
    assert normalize_ats_keywords(["Springboot", "spring boot", "Docker", " ", "docker", "JS"]) == [
        "spring boot",
        "docker",
        "javascript",
    ]


def test_duplicate_requirements_are_kept_once() -> None:
    first = requirement("Python is required", text="Python")
    again = requirement("  Python   is required", text="python")

    assert dedupe_requirements([first, again]) == [first]


def test_a_split_sentence_keeps_both_requirements() -> None:
    python = requirement("Python and Go are required", text="Python")
    go = requirement("Python and Go are required", text="Go")

    assert dedupe_requirements([python, go]) == [python, go]


def test_the_posting_text_joins_description_and_requirements() -> None:
    assert build_posting_text("desc", "reqs") == "desc\n\nreqs"
    assert build_posting_text("desc", None) == "desc"
    assert build_posting_text("desc", "  ") == "desc"
