import uuid

from app.ai.matching.actions import build_actions
from app.ai.matching.report_models import MissingKeyword
from tests.ai.matching.report_builders import (
    finding,
    issue,
    result,
    stored_report,
    suggestion,
)


def mk(keyword: str, in_profile: bool = False, *ids: uuid.UUID) -> MissingKeyword:
    return MissingKeyword(keyword=keyword, in_profile=in_profile, requirement_ids=list(ids))


def test_the_kinds_come_in_order_and_the_priorities_are_contiguous() -> None:
    profile_finding = finding("in_profile_not_in_resume", text="Docker")
    gap = finding("missing", text="Rust")
    analysis = result([gap, profile_finding])
    stored = stored_report(issues=[issue("tables", "warning"), issue("multi_column", "warning")])

    actions = build_actions(analysis, stored)

    assert [a.kind for a in actions] == ["fix_format", "fix_format", "add_from_profile", "real_gap"]
    assert [a.priority for a in actions] == [1, 2, 3, 4]


def test_format_fixes_are_ordered_by_severity() -> None:
    stored = stored_report(
        issues=[issue("a", "warning"), issue("b", "critical"), issue("c", "info")]
    )

    actions = build_actions(result([]), stored)

    assert [(a.issue_code, a.issue_severity) for a in actions] == [
        ("b", "critical"),
        ("a", "warning"),
        ("c", "info"),
    ]
    assert actions[0].text == "About b."


def test_must_have_comes_before_nice_to_have_within_a_kind() -> None:
    nice = finding("missing", text="nice", priority="nice_to_have")
    must = finding("missing", text="must")
    nice_profile = finding("in_profile_not_in_resume", text="np", priority="nice_to_have")
    must_profile = finding("in_profile_not_in_resume", text="mp")

    actions = build_actions(result([nice, nice_profile, must, must_profile]), stored_report())

    assert [a.requirement_text for a in actions] == ["mp", "np", "must", "nice"]
    assert [a.importance for a in actions] == ["must_have", "nice_to_have"] * 2


def test_a_real_gap_is_honest_that_rewriting_cannot_fix_it() -> None:
    analysis = result([finding("missing", text="Rust"), finding("partial", text="Go")])

    actions = build_actions(analysis, stored_report())

    for action in actions:
        assert action.kind == "real_gap"
        assert "Rewriting cannot fix" in action.text
        assert "unless it is true" in action.text or "than is true" in action.text
    assert actions[0].requirement_text == "Rust" and "Rust" in actions[0].text


def test_a_real_gap_is_honest_in_portuguese_too() -> None:
    analysis = result([finding("missing", text="Rust")])

    [action] = build_actions(analysis, stored_report(language="pt"))

    assert "Reescrever não resolve" in action.text
    assert "a menos que seja verdade" in action.text


def test_the_profile_action_lists_its_suggestion() -> None:
    profile_finding = finding("in_profile_not_in_resume", text="Docker")
    stored = stored_report(
        suggestions=[
            suggestion("S1", requirement_id=profile_finding.requirement_id),
            suggestion("S2", requirement_id=uuid.uuid4()),
        ]
    )

    [action] = build_actions(result([profile_finding]), stored)

    assert action.kind == "add_from_profile" and action.suggestion_ids == ["S1"]
    assert "profile shows this" in action.text


def test_a_partial_gap_lists_the_suggestions_that_strengthen_it() -> None:
    partial = finding("partial", text="Python 5 years")
    stored = stored_report(suggestions=[suggestion("S1", requirement_id=partial.requirement_id)])

    [action] = build_actions(result([partial]), stored)

    assert action.kind == "real_gap" and action.suggestion_ids == ["S1"]


def test_a_profile_keyword_gets_an_add_action_with_its_suggestion() -> None:
    stored = stored_report(
        missing_keywords=[mk("docker", True)], suggestions=[suggestion("S1", keyword="docker")]
    )

    [action] = build_actions(result([], missing=["docker"]), stored)

    assert (action.kind, action.keyword, action.suggestion_ids) == (
        "add_from_profile",
        "docker",
        ["S1"],
    )
    assert action.requirement_id is None and action.importance is None


def test_a_keyword_that_is_not_in_the_profile_is_a_real_gap() -> None:
    stored = stored_report(missing_keywords=[mk("terraform")])

    [action] = build_actions(result([], missing=["terraform"]), stored)

    assert (action.kind, action.keyword) == ("real_gap", "terraform")
    assert "Rewriting cannot fix" in action.text


def test_a_keyword_of_a_requirement_that_has_an_action_gets_none() -> None:
    gap = finding("missing", text="Kubernetes")
    profile_finding = finding("in_profile_not_in_resume", text="Docker")
    stored = stored_report(
        missing_keywords=[
            mk("kubernetes", False, gap.requirement_id),
            mk("docker", True, profile_finding.requirement_id),
        ]
    )

    actions = build_actions(result([gap, profile_finding]), stored)

    assert [a.requirement_text for a in actions] == ["Docker", "Kubernetes"]
    assert all(a.keyword is None for a in actions)


def test_a_requirement_appears_in_one_action_only() -> None:
    findings = [
        finding("missing", text="a"),
        finding("partial", text="b"),
        finding("in_profile_not_in_resume", text="c"),
        finding("met", text="d"),
    ]

    actions = build_actions(result(findings), stored_report())

    ids = [a.requirement_id for a in actions]
    assert len(ids) == len(set(ids)) == 3


def test_a_portuguese_job_gets_portuguese_texts() -> None:
    analysis = result([finding("in_profile_not_in_resume", text="Docker")])

    [action] = build_actions(analysis, stored_report(language="pt"))

    assert "Seu perfil mostra isto" in action.text


def test_an_other_language_job_gets_english() -> None:
    analysis = result([finding("in_profile_not_in_resume", text="Docker")])

    [action] = build_actions(analysis, stored_report(language="other"))

    assert "Your profile shows this" in action.text


def test_a_perfect_analysis_has_no_action() -> None:
    assert build_actions(result([finding("met")], found=["python"]), stored_report()) == []
