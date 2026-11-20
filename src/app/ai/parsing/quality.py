"""ATS readability checks. Pure functions: they never see the file, only `ParsedDocument`."""

import unicodedata
from collections.abc import Callable

from app.ai.parsing.models import ParsedDocument, ParsingIssue, Severity
from app.core.normalization import fold_text

MIN_CHARS_PER_PAGE = 500
MAX_PAGES = 3

_SEVERITY_ORDER: dict[Severity, int] = {"critical": 0, "warning": 1, "info": 2}

# Recognized section headings, already folded (lowercase, no accents). English and Portuguese.
SECTION_HEADINGS: dict[str, frozenset[str]] = {
    "experience": frozenset(
        {
            "experience",
            "work experience",
            "professional experience",
            "experiencia",
            "experiencia profissional",
        }
    ),
    "education": frozenset(
        {"education", "academic background", "educacao", "formacao", "formacao academica"}
    ),
    "skills": frozenset(
        {"skills", "technical skills", "habilidades", "competencias", "tecnologias"}
    ),
}

_MESSAGES = {
    "image_only_pdf": (
        "This PDF contains only images and no text layer, so an ATS reads it as blank. Export "
        "a text-based PDF (or a DOCX) from the original editor instead of scanning it or "
        "saving pages as images."
    ),
    "multi_column": (
        "The text is laid out in two or more columns. Many ATS read straight across the page "
        "and mix the columns together, which scrambles your experience. Use a single column."
    ),
    "tables": (
        "The document uses tables. An ATS often reads table cells out of order or skips them. "
        "Move your experience, education and skills out of tables into plain paragraphs and lists."
    ),
    "header_footer_content": (
        "There is text in the header or footer area. Many ATS ignore headers and footers, so "
        "details such as your name or contact information can be lost. Put them in the main body."
    ),
    "low_text_ratio": (
        f"The document has very little text for its length (under {MIN_CHARS_PER_PAGE} "
        "characters per page on average). Content drawn as graphics or images is invisible "
        "to an ATS. Make sure your content is real text."
    ),
    "special_glyph_bullets": (
        "Some lines start with an icon or a special symbol instead of a standard bullet. An ATS "
        "may read these as unknown characters. Use plain bullets such as • or -."
    ),
    "too_many_pages": (
        f"The resume has more than {MAX_PAGES} pages. A shorter resume is easier for an ATS and "
        "for recruiters to process. Consider trimming it to one or two pages."
    ),
}


def _missing_section_message(section: str) -> str:
    return (
        f"No '{section.capitalize()}' section heading was found. An ATS looks for standard "
        f"headings to find that part of your resume. Add a heading named '{section.capitalize()}' "
        "(or its Portuguese equivalent) on its own line."
    )


def _issue(code: str, severity: Severity, message: str) -> ParsingIssue:
    return ParsingIssue(code=code, severity=severity, message=message)


def _has_special_glyph_bullets(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped and unicodedata.category(stripped[0]) in {"So", "Co"}:
            return True
    return False


def _headings(text: str) -> set[str]:
    return {fold_text(line.strip().rstrip(":")) for line in text.splitlines()}


def _is_low_text_ratio(document: ParsedDocument) -> bool:
    length = len(document.text.strip())
    if not document.page_count or length == 0:
        return False
    return length / document.page_count < MIN_CHARS_PER_PAGE


def check_quality(document: ParsedDocument) -> list[ParsingIssue]:
    """Return the readability issues of a parsed document, most severe first."""
    issues: list[ParsingIssue] = []
    checks: list[tuple[bool, Callable[[], ParsingIssue]]] = [
        (
            document.file_type == "pdf" and not document.text.strip() and document.image_count > 0,
            lambda: _issue("image_only_pdf", "critical", _MESSAGES["image_only_pdf"]),
        ),
        (
            document.multi_column,
            lambda: _issue("multi_column", "warning", _MESSAGES["multi_column"]),
        ),
        (document.table_count > 0, lambda: _issue("tables", "warning", _MESSAGES["tables"])),
        (
            document.header_footer_text,
            lambda: _issue("header_footer_content", "warning", _MESSAGES["header_footer_content"]),
        ),
        (
            _is_low_text_ratio(document),
            lambda: _issue("low_text_ratio", "warning", _MESSAGES["low_text_ratio"]),
        ),
        (
            _has_special_glyph_bullets(document.text),
            lambda: _issue("special_glyph_bullets", "warning", _MESSAGES["special_glyph_bullets"]),
        ),
        (
            document.page_count is not None and document.page_count > MAX_PAGES,
            lambda: _issue("too_many_pages", "info", _MESSAGES["too_many_pages"]),
        ),
    ]
    issues.extend(build() for failed, build in checks if failed)

    found = _headings(document.text)
    for section, names in SECTION_HEADINGS.items():
        if not found & names:
            issues.append(
                _issue(f"missing_{section}_section", "warning", _missing_section_message(section))
            )
    return sorted(issues, key=lambda issue: (_SEVERITY_ORDER[issue.severity], issue.code))
