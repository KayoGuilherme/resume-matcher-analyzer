import re
from collections import Counter

import pytest

from app.ai.matching.text import fold
from app.ai.parsing.quality import check_quality
from evals.dataset import CASES_DIR, Case, load_cases

CASES = load_cases()
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]?){9,}(?!\d)")
URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")


def test_the_dataset_has_between_ten_and_fifteen_cases_in_both_languages() -> None:
    languages = Counter(case.language for case in CASES)

    assert 10 <= len(CASES) <= 15
    assert languages["pt"] >= 5 and languages["en"] >= 5


def test_the_ids_start_with_the_language() -> None:
    assert all(case.id.startswith(f"{case.language}-") for case in CASES)


def test_each_outcome_appears_at_least_three_times() -> None:
    outcomes = Counter(case.expected_outcome for case in CASES)

    assert {o: outcomes[o] for o in ("likely_pass", "borderline", "likely_reject")} == {
        "likely_pass": outcomes["likely_pass"],
        "borderline": outcomes["borderline"],
        "likely_reject": outcomes["likely_reject"],
    }
    assert min(outcomes.values()) >= 3 and len(outcomes) == 3


def test_each_verdict_is_expected_at_least_three_times() -> None:
    verdicts = Counter(item.verdict for case in CASES for item in case.expected)

    assert set(verdicts) == {"met", "partial", "missing", "in_profile_not_in_resume"}
    assert min(verdicts.values()) >= 3


def test_the_resumes_of_at_least_two_cases_yield_a_parsing_issue() -> None:
    with_issues = [case.id for case in CASES if check_quality(case.parsed_document())]

    assert len(with_issues) >= 2


def test_only_the_cases_that_mean_to_have_issues_have_them() -> None:
    for case in CASES:
        has_facts = case.document.model_dump(exclude_defaults=True) != {}
        assert bool(check_quality(case.parsed_document())) == has_facts, case.id


def test_the_dataset_covers_a_years_and_a_language_level_requirement() -> None:
    texts = [case.job_text.lower() for case in CASES]

    assert any(re.search(r"\d\+ (years|anos)", text) for text in texts)
    assert any("fluent english" in text or "inglês avançado" in text for text in texts)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_a_case_expects_distinct_non_empty_matches(case: Case) -> None:
    matches = [fold(item.match) for item in case.expected]

    assert all(matches) and len(matches) == len(set(matches))
    assert 3 <= len(case.expected) <= 6


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_every_match_is_in_the_job_posting(case: Case) -> None:
    job = fold(case.job_text)

    for item in case.expected:
        assert fold(item.match) in job, f"{case.id}: {item.match!r} is not in the posting"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_a_case_has_standard_resume_headings(case: Case) -> None:
    assert not any(
        issue.code.startswith("missing_") for issue in check_quality(case.parsed_document())
    ), case.id


def test_no_case_file_has_an_email_a_phone_number_or_a_url() -> None:
    for path in sorted(CASES_DIR.rglob("*")):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not EMAIL.search(text), path
            assert not PHONE.search(text), path
            assert not URL.search(text), path


def test_the_case_folders_hold_exactly_the_four_files() -> None:
    for folder in CASES_DIR.iterdir():
        assert sorted(path.name for path in folder.iterdir()) == [
            "case.json",
            "job.txt",
            "profile.json",
            "resume.txt",
        ]
