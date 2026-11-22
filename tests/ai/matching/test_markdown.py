import re
import uuid

from app.ai.extraction.models import ExtractionWarning
from app.ai.matching.markdown import plain, render_markdown
from app.ai.matching.report import build_report
from app.ai.matching.report_models import Report, ScreenerResult, ScreenerRun
from tests.ai.matching.report_builders import (
    finding,
    issue,
    result,
    score_settings,
    stored_report,
    suggestion,
)

INJECTED = (
    "# Pwned [click](http://x.example) <script>alert(1)</script> ![img](http://y.example/a.png)"
)


def a_report(language: str = "en", **overrides: object) -> Report:
    profile_finding = finding("in_profile_not_in_resume", text="Docker")
    analysis = result(
        [finding("met", text="Python"), finding("missing", text="Rust"), profile_finding],
        found=["python"],
        missing=["docker", "rust"],
    )
    stored = stored_report(
        language=language,
        issues=[issue("tables", "warning")],
        suggestions=[
            suggestion(
                "S1",
                requirement_id=profile_finding.requirement_id,
                original="Built APIs",
                text="Built APIs and shipped them in Docker containers",
            )
        ],
        rejected=[ExtractionWarning(code="unsupported_number", count=1)],
        decisions=("pass", "borderline", "pass"),
    )
    if "screener" in overrides:
        stored = stored.model_copy(update={"screener": overrides["screener"]})
    return build_report(
        analysis_id=uuid.uuid4(),
        resume_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        result=analysis,
        stored=stored,
        score_settings=score_settings(),
    )


def test_the_sections_come_in_order() -> None:
    text = render_markdown(a_report())

    headings = [
        "# Screening report",
        "> This is a simulation",
        "## Score",
        "## Simulated screener",
        "## What to do",
        "## Rewrite suggestions",
        "## ATS keywords",
        "## Warnings",
    ]
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)


def test_the_markdown_holds_the_same_facts_as_the_report() -> None:
    report = a_report()

    text = render_markdown(report)

    assert f"**{report.score.value:g} / 100**" in text
    assert f"`{report.score.outcome}`" in text
    assert f"`{report.screener.decision}`" in text
    assert f"{report.screener.consistency:g}" in text
    assert len(re.findall(r"^\d+\. ", text, re.MULTILINE)) == len(report.actions)
    assert "S1" in text and "Built APIs and shipped them in Docker containers" in text
    assert "suggestion\\_rejected\\_unsupported\\_number: 1" in text


def test_the_actions_are_grouped_by_kind() -> None:
    text = render_markdown(a_report())

    fix = text.index("### Fix format and parsing issues")
    add = text.index("### Add what your profile proves")
    gap = text.index("### Real gaps")
    assert fix < add < gap


def test_the_runs_and_their_reasons_are_listed() -> None:
    text = render_markdown(a_report())

    assert "Run 1: `pass`" in text and "Run 2: `borderline`" in text and "Run 3: `pass`" in text
    assert text.count("Reason.") == 3


def test_a_portuguese_report_uses_portuguese_headings() -> None:
    text = render_markdown(a_report("pt"))

    assert "# Relatório de triagem" in text
    assert "## O que fazer" in text and "> Esta é uma simulação" in text


def test_a_perfect_report_says_there_is_nothing_to_fix() -> None:
    analysis = result([finding("met")], found=["python"])
    report = build_report(
        analysis_id=uuid.uuid4(),
        resume_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        result=analysis,
        stored=stored_report(),
        score_settings=score_settings(),
    )

    text = render_markdown(report)

    assert "Nothing to fix." in text and "No suggestions." in text
    assert "## Warnings" not in text


def test_a_report_without_a_score_says_so() -> None:
    report = build_report(
        analysis_id=uuid.uuid4(),
        resume_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        result=result([]),
        stored=stored_report(),
        score_settings=score_settings(),
    )

    assert "Nothing could be measured" in render_markdown(report)


def test_injected_markup_in_a_reason_stays_text() -> None:
    screener = ScreenerResult(
        decision="pass",
        consistency=1.0,
        runs=[ScreenerRun(decision="pass", reasons=[INJECTED])],
    )

    text = render_markdown(a_report(screener=screener))

    assert "<script" not in text and "</script>" not in text
    assert "&lt;script&gt;" in text
    assert not re.search(r"^#+ Pwned", text, re.MULTILINE)
    assert "[click](" not in text and "![img]" not in text and "](http" not in text
    assert "http://" not in text and "https://" not in text


def test_plain_collapses_line_breaks_and_escapes_control_characters() -> None:
    assert plain("a\n\n  b\tc") == "a b c"
    assert plain("*bold* _it_ `code` # h | x ~y~") == r"\*bold\* \_it\_ \`code\` \# h \| x \~y\~"
    assert plain("a & b < c > d") == "a &amp; b &lt; c &gt; d"
    assert plain(r"back\slash") == r"back\\slash"


def test_plain_breaks_autolinks() -> None:
    assert "://" not in plain("see https://example.com/x and ftp://host and www.example.com")
    assert "www." not in plain("www.example.com")


def test_text_from_the_resume_is_escaped_in_suggestions_and_actions() -> None:
    profile_finding = finding("in_profile_not_in_resume", text="C++ <b>& [link](http://z.example)")
    analysis = result([profile_finding])
    stored = stored_report(
        suggestions=[suggestion("S1", requirement_id=profile_finding.requirement_id, text=INJECTED)]
    )
    report = build_report(
        analysis_id=uuid.uuid4(),
        resume_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        result=analysis,
        stored=stored,
        score_settings=score_settings(),
    )

    text = render_markdown(report)

    assert "<b>" not in text and "<script" not in text
    assert "](http" not in text
