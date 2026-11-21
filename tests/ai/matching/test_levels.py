import pytest

from app.ai.matching.levels import SCALE, meets, parse_level, rank


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("beginner English", "A1"),
        ("Inglês iniciante", "A1"),
        ("basic", "A2"),
        ("Inglês básico", "A2"),
        ("elementary", "A2"),
        ("intermediate", "B1"),
        ("Inglês intermediário", "B1"),
        ("upper-intermediate", "B2"),
        ("Upper Intermediate English", "B2"),
        ("intermediário avançado", "B2"),
        ("advanced", "C1"),
        ("Avançado", "C1"),
        ("avancado", "C1"),
        ("Fluent English", "C1"),
        ("fluente", "C1"),
        ("proficient", "C1"),
        ("bilingual", "C2"),
        ("bilíngue", "C2"),
        ("native", "native"),
        ("nativo", "native"),
        ("Native speaker", "native"),
        ("B2", "B2"),
        ("c1", "C1"),
        ("English (C2)", "C2"),
        ("A1", "A1"),
    ],
)
def test_words_and_codes_are_read_onto_the_scale(text: str, level: str) -> None:
    assert parse_level(text) == level


def test_upper_intermediate_is_b2_and_not_b1() -> None:
    assert parse_level("upper-intermediate") == "B2"
    assert parse_level("intermediário avançado") == "B2"


@pytest.mark.parametrize("text", ["B2B sales", "abb2", "fluently", "English", "", "Python"])
def test_a_code_inside_a_longer_word_or_no_level_word_gives_none(text: str) -> None:
    assert parse_level(text) is None


def test_two_levels_in_one_text_give_the_highest() -> None:
    assert parse_level("intermediate to advanced") == "C1"
    assert parse_level("basic, B2 preferred") == "B2"


def test_meets_over_the_whole_scale() -> None:
    for have in SCALE:
        for need in SCALE:
            assert meets(have, need) is (rank(have) >= rank(need))


def test_no_level_asked_means_any_level_counts() -> None:
    assert meets("A1", None)
    assert meets(None, None)


def test_an_unknown_level_never_proves_a_level_that_is_asked() -> None:
    assert not meets(None, "A1")


def test_native_is_above_c2() -> None:
    assert rank("native") > rank("C2")
    assert meets("native", "C2") and not meets("C2", "native")
