import pytest

from app.core.normalization import fold_text, normalize_language_name, normalize_stack_name


@pytest.mark.parametrize("raw", ["  Spring   BOOT ", "SPRING BOOT", "spring boot"])
def test_stack_names_are_compared_in_canonical_form(raw: str) -> None:
    assert normalize_stack_name(raw) == "spring boot"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("springboot", "spring boot"), ("Postgres", "postgresql"), ("JS", "javascript")],
)
def test_stack_aliases_map_to_canonical_names(raw: str, expected: str) -> None:
    assert normalize_stack_name(raw) == expected


@pytest.mark.parametrize("raw", ["pt", "Português", "portugues", " PT "])
def test_portuguese_language_aliases(raw: str) -> None:
    assert normalize_language_name(raw) == "portuguese"


@pytest.mark.parametrize("raw", ["en", "Inglês", "ingles", "English"])
def test_english_language_aliases(raw: str) -> None:
    assert normalize_language_name(raw) == "english"


def test_aliases_are_specific_to_the_kind_of_name() -> None:
    assert normalize_stack_name("pt") == "pt"
    assert normalize_language_name("js") == "js"


def test_unknown_names_are_only_cleaned() -> None:
    assert normalize_stack_name("  Rust ") == "rust"
    assert normalize_language_name("Français") == "français"


@pytest.mark.parametrize("raw", ["Springboot", "Postgres", "  Rust ", "Spring   Boot"])
def test_normalization_is_idempotent(raw: str) -> None:
    once = normalize_stack_name(raw)

    assert normalize_stack_name(once) == once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Experiência   Profissional ", "experiencia profissional"),
        ("FORMAÇÃO ACADÊMICA", "formacao academica"),
        ("Skills", "skills"),
        ("", ""),
    ],
)
def test_fold_text_ignores_case_accents_and_spacing(raw: str, expected: str) -> None:
    assert fold_text(raw) == expected


def test_name_normalization_keeps_accents_in_unknown_names() -> None:
    assert normalize_language_name("Français") == "français"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("K8s", "kubernetes"),
        ("  GoLang ", "go"),
        ("TS", "typescript"),
        ("NodeJS", "node.js"),
        ("Kubernetes", "kubernetes"),
    ],
)
def test_more_stack_aliases(raw: str, expected: str) -> None:
    assert normalize_stack_name(raw) == expected


def test_the_new_aliases_are_stack_only() -> None:
    assert normalize_language_name("ts") == "ts"
    assert normalize_language_name("k8s") == "k8s"
