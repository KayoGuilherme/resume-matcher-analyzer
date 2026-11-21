import pytest

from app.ai.extraction.priority import (
    cue_priority,
    heading_priority,
    locate_in_posting,
    resolve_priority,
)


def _resolve(text: str, posting: str | None = None, model: str = "unclear") -> tuple[str, bool]:
    return resolve_priority(text, posting if posting is not None else text, model)  # type: ignore[arg-type]


# --- own wording -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Strong knowledge of Python is required",
        "You must know SQL",
        "Mandatory: Docker",
        "Essential: teamwork",
        "Inglês avançado obrigatório",
        "Experiência com Java é necessária",
        "Conhecimento de Git imprescindível",
        "Domínio de SQL indispensável",
        "Linux é obrigatório",
    ],
)
def test_must_cues(text: str) -> None:
    assert cue_priority(text) == "must"
    assert _resolve(text) == ("must_have", False)


@pytest.mark.parametrize(
    "text",
    [
        "Experience with Kubernetes is a plus",
        "AWS is nice to have",
        "Nice-to-have: Go",
        "Bonus: open source work",
        "Terraform preferred",
        "A degree is desirable",
        "Ideally, some Rust",
        "Conhecimento em Kubernetes é um diferencial",
        "Diferenciais: Go",
        "Experiência com AWS desejável",
        "Experiencia com AWS desejavel",
        "Conhecimento de Docker será um plus",
        "Preferencialmente com experiência em fintech",
    ],
)
def test_nice_cues(text: str) -> None:
    assert cue_priority(text) == "nice"
    assert _resolve(text) == ("nice_to_have", False)


@pytest.mark.parametrize(
    "text",
    [
        "A degree is not required",
        "Graduação não obrigatória",
        "Graduacao nao e obrigatoria",
        "Experience with Java is not mandatory",
        "Certification isn't required",
    ],
)
def test_a_negated_must_cue_means_nice_to_have(text: str) -> None:
    assert cue_priority(text) == "nice"
    assert _resolve(text) == ("nice_to_have", False)


@pytest.mark.parametrize(
    "text", ["Python is required, Go is a plus", "Obrigatório Java, diferencial Kotlin"]
)
def test_both_kinds_of_cue_are_unclear_and_must_have(text: str) -> None:
    assert cue_priority(text) == "both"
    assert _resolve(text, model="nice_to_have") == ("must_have", True)


@pytest.mark.parametrize(
    "text",
    [
        "Experience with Redis",
        "Software requirements documentation",  # "requirements" is not "required"
        "Plus size shirts",  # a bare "plus" is not the cue "a plus"
        "Mustard seed",
    ],
)
def test_text_without_cues(text: str) -> None:
    assert cue_priority(text) is None


# --- headings ----------------------------------------------------------------------------------

PORTUGUESE = """\
Sobre a vaga
Time de pagamentos.

Requisitos:
- Experiência com Java
- Docker é obrigatório

Diferenciais:
- Experiência com AWS
- Docker é obrigatório
"""


def test_a_bullet_under_a_nice_heading_is_nice() -> None:
    assert _resolve("Experiência com AWS", PORTUGUESE) == ("nice_to_have", False)


def test_a_bullet_under_a_must_heading_is_must() -> None:
    assert _resolve("Experiência com Java", PORTUGUESE) == ("must_have", False)


def test_the_requirements_own_cue_beats_the_heading() -> None:
    posting = "Diferenciais:\n- Docker é obrigatório\n"

    assert _resolve("Docker é obrigatório", posting) == ("must_have", False)


def test_a_heading_cue_beats_the_model() -> None:
    posting = "Nice to have:\n- Go\n"

    assert _resolve("Go", posting, model="must_have") == ("nice_to_have", False)


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("Requirements:", "must_have"),
        ("Requirements", "must_have"),
        ("## Requirements", "must_have"),
        ("**Must have**", "must_have"),
        ("Required skills", "must_have"),
        ("Basic qualifications:", "must_have"),
        ("Requisitos obrigatórios", "must_have"),
        ("Nice to have", "nice_to_have"),
        ("Preferred qualifications:", "nice_to_have"),
        ("Bonus points:", "nice_to_have"),
        ("Diferenciais", "nice_to_have"),
        ("Desejável:", "nice_to_have"),
    ],
)
def test_heading_cues_with_and_without_a_colon(heading: str, expected: str) -> None:
    posting = f"{heading}\nExperience with Redis\n"

    assert _resolve("Experience with Redis", posting) == (expected, False)


def test_a_bullet_under_benefits_does_not_inherit_an_earlier_requirements_heading() -> None:
    posting = "Requirements:\n- Python\n\nBenefits:\n- Gym membership\n"

    assert _resolve("Gym membership", posting, model="unclear") == ("must_have", True)
    assert heading_priority("Gym membership", posting) is None
    assert heading_priority("Python", posting) == "must"


def test_a_neutral_heading_without_a_colon_also_stops_the_search() -> None:
    posting = "Requirements:\n- Python\nBenefits\n- Gym membership\n"

    assert heading_priority("Gym membership", posting) is None


def test_an_introduction_ending_with_a_colon_is_not_a_heading() -> None:
    posting = "Diferenciais:\nCandidates who also have these will stand out in the process:\n- Go\n"

    assert heading_priority("Go", posting) == "nice"


def test_plain_lines_in_a_list_do_not_become_headings() -> None:
    posting = "Requirements:\nPython\nDocker\nAWS\n"

    assert heading_priority("AWS", posting) == "must"


def test_a_short_sentence_is_not_a_heading() -> None:
    posting = "Python is required\nGo is a plus\nDocker\n"

    assert heading_priority("Docker", posting) is None
    assert heading_priority("Docker", "Python é obrigatório\nDocker\n") is None


def test_a_wrapped_bullet_is_located_and_resolved() -> None:
    posting = "Nice to have:\n• Experience with Kubernetes and\n  service meshes in production\n"
    wrapped = "Experience with Kubernetes and service meshes in production"

    assert locate_in_posting(wrapped, posting) == posting.index("Experience")
    assert _resolve(wrapped, posting) == ("nice_to_have", False)


def test_markdown_bold_headings_and_bullets() -> None:
    posting = "**Diferenciais**\n* Go\n* Rust\n"

    assert heading_priority("Rust", posting) == "nice"


# --- model judgment and the unclear default -------------------------------------------------------


def test_the_model_decides_when_the_posting_gives_no_evidence() -> None:
    posting = "About you:\n- Experience with Redis\n"

    assert _resolve("Experience with Redis", posting, model="nice_to_have") == (
        "nice_to_have",
        False,
    )
    assert _resolve("Experience with Redis", posting, model="must_have") == ("must_have", False)


def test_no_evidence_and_no_model_judgment_is_must_have_and_flagged() -> None:
    posting = "About you:\n- Experience with Redis\n"

    unclear = _resolve("Experience with Redis", posting, model="unclear")
    assert unclear == ("must_have", True)


def test_a_text_not_in_the_posting_falls_back_to_cues_and_the_model() -> None:
    assert _resolve("Redis", "something else", model="nice_to_have") == ("nice_to_have", False)
    assert _resolve("Redis is a plus", "something else", model="must_have") == (
        "nice_to_have",
        False,
    )
    assert heading_priority("Redis", "something else") is None


def test_a_clear_decision_is_never_flagged() -> None:
    assert _resolve("Python is required")[1] is False
    assert _resolve("Go is a plus")[1] is False


# --- locating ----------------------------------------------------------------------------------


def test_locate_ignores_whitespace_bullets_and_unicode_variants() -> None:
    posting = "Intro\n•  Designed micro-\n   services for the ﬁnance team\n"

    index = locate_in_posting("Designed micro-services for the finance team", posting)

    assert index == posting.index("Designed")


def test_locate_handles_decomposed_accents() -> None:
    posting = "Requisitos:\n- Experiência com Java\n"

    assert locate_in_posting("Experiência com Java", posting) is not None


def test_locate_returns_none_when_absent_or_empty() -> None:
    assert locate_in_posting("Go", "Python only") is None
    assert locate_in_posting("  •  ", "Python only") is None
