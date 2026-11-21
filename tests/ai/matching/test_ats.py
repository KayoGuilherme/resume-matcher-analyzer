from app.ai.matching.ats import ats_coverage
from app.ai.matching.models import AtsCoverage
from app.ai.matching.text import SearchableText


def _coverage(keywords: list[str], text: str) -> AtsCoverage:
    return ats_coverage(keywords, SearchableText(text))


def test_found_and_missing_keywords_with_the_text_as_written() -> None:
    coverage = _coverage(["python", "kubernetes", "terraform"], "Python, K8s, Docker")

    assert [(f.keyword, f.matched_text) for f in coverage.found] == [
        ("python", "Python"),
        ("kubernetes", "K8s"),
    ]
    assert coverage.missing == ["terraform"]


def test_a_keyword_is_a_whole_term() -> None:
    coverage = _coverage(["java"], "Experienced with JavaScript")

    assert coverage.found == [] and coverage.missing == ["java"]


def test_symbols_are_matched_whole() -> None:
    coverage = _coverage(["c++", "c#", "c"], "C++ and Rust")

    assert [f.keyword for f in coverage.found] == ["c++"]
    assert coverage.missing == ["c#", "c"]


def test_short_names_are_still_literal() -> None:
    coverage = _coverage(["go"], "Services in Go")

    assert [f.keyword for f in coverage.found] == ["go"]


def test_a_keyword_only_in_the_profile_stays_missing() -> None:
    # the profile is not an input of the coverage at all: only the resume text is searched
    coverage = _coverage(["rust"], "Python developer")

    assert coverage.missing == ["rust"]


def test_without_ats_keywords_the_coverage_is_empty() -> None:
    coverage = _coverage([], "Python")

    assert coverage.found == [] and coverage.missing == []


def test_the_job_order_is_kept() -> None:
    coverage = _coverage(["sql", "docker", "python", "terraform"], "Python Docker")

    assert [f.keyword for f in coverage.found] == ["docker", "python"]
    assert coverage.missing == ["sql", "terraform"]


def test_accents_and_case_are_ignored() -> None:
    coverage = _coverage(["programacao"], "PROGRAMAÇÃO em Python")

    assert coverage.found[0].matched_text == "PROGRAMAÇÃO"


def test_the_coverage_is_not_a_score() -> None:
    assert set(AtsCoverage.model_fields) == {"found", "missing"}
