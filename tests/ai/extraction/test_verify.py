from app.ai.extraction.models import ExtractedProject
from app.ai.extraction.verify import (
    drop_unverified,
    find_unverified,
    is_verbatim,
    normalize,
)
from tests.ai.extraction.builders import RESUME_TEXT, experience, extracted


def _check(item: str, text: str = RESUME_TEXT) -> bool:
    return is_verbatim(item, normalize(text))


def test_a_bullet_wrapped_over_two_lines_is_verbatim() -> None:
    assert _check("Built a payments API with Spring Boot and PostgreSQL")


def test_a_bullet_symbol_on_the_item_is_ignored() -> None:
    assert _check("• Reduced p95 latency by 40%")
    assert _check("- Reduced p95 latency by 40%")
    assert _check("  * Reduced p95 latency by 40%")


def test_hyphenation_at_a_line_break_does_not_cause_a_false_rejection() -> None:
    text = "• Designed micro-\n  services for billing"

    assert _check("Designed micro-services for billing", text)


def test_ligatures_match_through_unicode_compatibility() -> None:
    assert _check("Configured the ﬁrewall", "Configured the firewall")


def test_an_accent_difference_fails() -> None:
    assert not _check(
        "Desenvolvedora backend com foco em APIs", "Desenvolvedora backénd com foco em APIs"
    )


def test_a_case_difference_fails() -> None:
    assert not _check("reduced P95 latency by 40%")


def test_a_paraphrase_fails() -> None:
    assert not _check("Cut p95 latency by forty percent")


def test_a_portuguese_bullet_is_kept_and_its_translation_fails() -> None:
    text = "• Reduzi a latência da API em 40%"

    assert _check("Reduzi a latência da API em 40%", text)
    assert not _check("Reduced API latency by 40%", text)


def test_an_empty_item_is_never_verbatim() -> None:
    assert not _check("")
    assert not _check("  •  ")


def test_find_unverified_covers_bullets_project_bullets_and_skills_lines() -> None:
    result = extracted(
        experiences=[experience("Reduced p95 latency by 40%", "Invented achievement")],
        skills=["Languages: Java, Python, SQL", "Invented skills line"],
        projects=[
            ExtractedProject(
                name="Resume Matcher",
                bullets=["Matches resumes against job posts", "Invented project bullet"],
                technologies=[],
            )
        ],
    )

    unverified = find_unverified(result, RESUME_TEXT)

    assert [(item.kind, item.text) for item in unverified] == [
        ("skills_line", "Invented skills line"),
        ("experience_bullet", "Invented achievement"),
        ("project_bullet", "Invented project bullet"),
    ]


def test_drop_unverified_removes_only_the_bad_items_and_counts_them() -> None:
    result = extracted(
        experiences=[experience("Reduced p95 latency by 40%", "Invented achievement")],
        skills=["Cloud: AWS, Docker", "Invented skills line"],
    )

    cleaned, dropped = drop_unverified(result, RESUME_TEXT)

    assert dropped == 2
    assert cleaned.experiences[0].bullets == ["Reduced p95 latency by 40%"]
    assert [line.text for line in cleaned.skills] == ["Cloud: AWS, Docker"]
    assert len(result.experiences[0].bullets) == 2  # the input is not modified


def test_nothing_is_dropped_when_everything_is_verbatim() -> None:
    result = extracted(experiences=[experience("Reduced p95 latency by 40%")])

    cleaned, dropped = drop_unverified(result, RESUME_TEXT)

    assert dropped == 0
    assert cleaned == result
