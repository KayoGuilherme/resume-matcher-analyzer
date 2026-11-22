from app.ai.matching.technologies import COMMON_TECHNOLOGIES


def test_the_names_are_lowercase_and_have_at_least_three_characters() -> None:
    assert all(name == name.lower() for name in COMMON_TECHNOLOGIES)
    assert all(len(name) >= 3 for name in COMMON_TECHNOLOGIES)


def test_the_list_is_a_frozenset_of_about_two_hundred_names() -> None:
    assert isinstance(COMMON_TECHNOLOGIES, frozenset)
    assert 180 <= len(COMMON_TECHNOLOGIES) <= 300


def test_the_common_technologies_are_in_it() -> None:
    expected = {"python", "kubernetes", "postgresql", "react", "terraform", "aws", "docker"}

    assert expected <= COMMON_TECHNOLOGIES


def test_names_with_symbols_are_in_it() -> None:
    assert {"c++", ".net", "node.js", "asp.net"} <= COMMON_TECHNOLOGIES
