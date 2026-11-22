import pytest

from app.ai.matching.rewrites import build_corpus, numbers_in
from tests.ai.matching.builders import profile, stack


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cut query time by 60%", {"60"}),
        ("serving 2M requests", {"2"}),
        ("a rating of 1.5", {"1.5"}),
        ("uma nota de 1,5", {"1.5"}),
        ("saved 10k users", {"10"}),
        ("from 2019 to 2021", {"2019", "2021"}),
        ("1.500 usuários", {"1500"}),
        ("1,500,000 events", {"1500000"}),
        ("2.0 version", {"2"}),
        ("five years of Python", {"5"}),
        ("cinco anos de Python", {"5"}),
        ("três serviços", {"3"}),
        ("twenty engineers", {"20"}),
        ("a b2b product on k8s", set()),
        ("one engineer and um serviço", set()),
        ("no digits here", set()),
    ],
)
def test_numbers_are_found_in_one_canonical_form(text: str, expected: set[str]) -> None:
    assert numbers_in(text) == expected


def test_the_profiles_numbers_are_allowed() -> None:
    facts = profile(total_years=5, stacks=[stack("Python", 3), stack("Docker", 3.5)])

    corpus = build_corpus("Built APIs", facts)

    assert {"3", "3.5", "5"} <= corpus.numbers
    assert "40" not in corpus.numbers


def test_the_resumes_numbers_are_allowed() -> None:
    corpus = build_corpus("Cut query time by 60% in 2021", profile())

    assert {"60", "2021"} <= corpus.numbers
