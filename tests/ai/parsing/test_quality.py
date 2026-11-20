from typing import Any

import pytest

from app.ai.parsing import parse_document
from app.ai.parsing.models import ParsedDocument
from app.ai.parsing.quality import check_quality
from tests.fixtures import documents

CLEAN_TEXT = (
    "Experience\n• Built APIs\nEducation\nBSc\nSkills\nPython\n" + "Lorem ipsum dolor. " * 40
)


def _doc(**overrides: Any) -> ParsedDocument:
    fields: dict[str, Any] = {
        "file_type": "pdf",
        "text": CLEAN_TEXT,
        "page_count": 1,
        "parser": "test",
    }
    fields.update(overrides)
    return ParsedDocument(**fields)


def _codes(document: ParsedDocument) -> list[str]:
    return [issue.code for issue in check_quality(document)]


def test_a_clean_document_has_no_issues() -> None:
    assert check_quality(_doc()) == []


def test_image_only_pdf_is_critical() -> None:
    issues = check_quality(_doc(text="", image_count=2, page_count=2))

    critical = [i for i in issues if i.code == "image_only_pdf"]
    assert [i.severity for i in critical] == ["critical"]


def test_no_text_and_no_images_is_not_called_image_only() -> None:
    assert "image_only_pdf" not in _codes(_doc(text="", image_count=0))


def test_pdf_with_text_and_images_is_not_image_only() -> None:
    assert "image_only_pdf" not in _codes(_doc(image_count=3))


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"multi_column": True}, "multi_column"),
        ({"table_count": 1}, "tables"),
        ({"header_footer_text": True}, "header_footer_content"),
    ],
)
def test_layout_facts_become_warnings(overrides: dict[str, Any], code: str) -> None:
    issues = [i for i in check_quality(_doc(**overrides)) if i.code == code]

    assert [i.severity for i in issues] == ["warning"]


def test_low_text_ratio_for_a_two_page_document_with_little_text() -> None:
    text = "Experience\nEducation\nSkills\n" + "x" * 270  # about 300 characters in total

    assert "low_text_ratio" in _codes(_doc(text=text, page_count=2))


def test_low_text_ratio_boundary_is_500_characters_per_page() -> None:
    headings = "Experience\nEducation\nSkills\n"
    just_under = headings + "x" * (999 - len(headings))
    exactly = headings + "x" * (1000 - len(headings))

    assert "low_text_ratio" in _codes(_doc(text=just_under, page_count=2))
    assert "low_text_ratio" not in _codes(_doc(text=exactly, page_count=2))


def test_normal_density_is_not_flagged() -> None:
    text = "Experience\nEducation\nSkills\n" + "x" * 2000

    assert "low_text_ratio" not in _codes(_doc(text=text, page_count=1))


def test_unknown_page_count_skips_the_page_based_checks() -> None:
    codes = _codes(
        _doc(file_type="docx", text="Experience\nEducation\nSkills\nshort", page_count=None)
    )

    assert "low_text_ratio" not in codes
    assert "too_many_pages" not in codes


@pytest.mark.parametrize("glyph", ["➢", "✔", "■", "", "\U0001f539"])
def test_icon_and_special_glyph_bullets_are_flagged(glyph: str) -> None:
    text = CLEAN_TEXT + f"\n{glyph} Built a payments API"

    issues = [i for i in check_quality(_doc(text=text)) if i.code == "special_glyph_bullets"]

    assert [i.severity for i in issues] == ["warning"]


@pytest.mark.parametrize("bullet", ["•", "-", "–", "*", "·"])
def test_standard_bullets_are_not_flagged(bullet: str) -> None:
    text = CLEAN_TEXT + f"\n{bullet} Built a payments API\n  {bullet} Indented item"

    assert "special_glyph_bullets" not in _codes(_doc(text=text))


def test_symbols_inside_a_line_are_not_flagged() -> None:
    assert "special_glyph_bullets" not in _codes(_doc(text=CLEAN_TEXT + "\nBuilt APIs ✔ fast"))


def test_portuguese_headings_are_recognized() -> None:
    text = "Experiência Profissional\nFormação Acadêmica\nCompetências\n" + "x" * 800

    issues = [c for c in _codes(_doc(text=text)) if c.startswith("missing_")]

    assert issues == []


def test_headings_ignore_case_colons_and_spacing() -> None:
    text = "  WORK   EXPERIENCE: \nEDUCATION\nTechnical Skills:\n" + "x" * 800

    assert [c for c in _codes(_doc(text=text)) if c.startswith("missing_")] == []


def test_only_the_missing_section_is_reported() -> None:
    text = "Experience\nEducation\n" + "x" * 800

    issues = [i for i in check_quality(_doc(text=text)) if i.code.startswith("missing_")]

    assert [(i.code, i.severity) for i in issues] == [("missing_skills_section", "warning")]


def test_a_heading_must_be_the_whole_line() -> None:
    text = "My experience is vast\nEducation\nSkills\n" + "x" * 800

    assert "missing_experience_section" in _codes(_doc(text=text))


@pytest.mark.parametrize(("pages", "flagged"), [(3, False), (4, True)])
def test_more_than_three_pages_is_an_info_issue(pages: int, flagged: bool) -> None:
    text = CLEAN_TEXT + "x" * 3000
    issues = [
        i for i in check_quality(_doc(text=text, page_count=pages)) if i.code == "too_many_pages"
    ]

    assert [i.severity for i in issues] == (["info"] if flagged else [])


def test_issues_are_ordered_by_severity_then_code() -> None:
    document = _doc(
        text="",
        image_count=1,
        page_count=5,
        table_count=1,
        multi_column=True,
    )

    issues = check_quality(document)

    assert [(i.severity, i.code) for i in issues] == [
        ("critical", "image_only_pdf"),
        ("warning", "missing_education_section"),
        ("warning", "missing_experience_section"),
        ("warning", "missing_skills_section"),
        ("warning", "multi_column"),
        ("warning", "tables"),
        ("info", "too_many_pages"),
    ]


def test_messages_explain_the_problem_and_hold_no_resume_text() -> None:
    private_text = "PRIVATE-resume-text-123"
    document = _doc(text=f"{private_text}\n➢ {private_text}", table_count=1, multi_column=True)

    for issue in check_quality(document):
        assert private_text not in issue.message
        assert len(issue.message) > 40


def test_clean_pdf_fixture_has_no_issues() -> None:
    assert check_quality(parse_document(documents.clean_pdf(), "pdf")) == []


def test_two_column_pdf_fixture_is_flagged() -> None:
    assert "multi_column" in _codes(parse_document(documents.two_column_pdf(), "pdf"))


def test_table_header_footer_and_scanned_fixtures() -> None:
    assert "tables" in _codes(parse_document(documents.table_pdf(), "pdf"))
    assert "header_footer_content" in _codes(parse_document(documents.header_footer_pdf(), "pdf"))
    assert "image_only_pdf" in _codes(parse_document(documents.scanned_pdf(), "pdf"))


def test_four_page_pdf_fixture_is_flagged_but_three_pages_is_not() -> None:
    assert "too_many_pages" in _codes(parse_document(documents.many_pages_pdf(4), "pdf"))
    assert "too_many_pages" not in _codes(parse_document(documents.many_pages_pdf(3), "pdf"))


def test_docx_fixtures() -> None:
    assert "tables" in _codes(parse_document(documents.docx_with_table(), "docx"))
    assert "header_footer_content" in _codes(parse_document(documents.docx_with_header(), "docx"))
    assert "multi_column" in _codes(parse_document(documents.two_column_docx(), "docx"))
    assert check_quality(parse_document(documents.docx_without_page_count(), "docx")) == []
