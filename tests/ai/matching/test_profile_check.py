from app.ai.matching.models import Evidence, ProfileFacts, RequirementFinding
from app.ai.matching.profile_check import check
from tests.ai.matching.builders import kw, lang, profile, req, stack


def _finding(
    requirement_input,  # type: ignore[no-untyped-def]
    verdict: str = "missing",
    evidence: list[Evidence] | None = None,
    flags: list[str] | None = None,
) -> RequirementFinding:
    requirement = requirement_input.requirement
    return RequirementFinding(
        requirement_id=requirement.id,
        requirement_text=requirement.text,
        category=requirement.category,
        priority=requirement.priority,
        priority_unclear=requirement.priority_unclear,
        verdict=verdict,  # type: ignore[arg-type]
        decided_by="judge",
        evidence=evidence or [],
        explanation="before",
        flags=flags or [],
    )


def _check(requirement_input, facts: ProfileFacts, **kwargs) -> RequirementFinding:  # type: ignore[no-untyped-def]
    finding = _finding(requirement_input, **kwargs)
    return check(requirement_input.requirement, finding, facts, "en")


def test_a_skill_only_in_the_profile() -> None:
    requirement = req("Docker", keywords=[kw("Docker")])

    result = _check(requirement, profile(stacks=[stack("Docker", 3, "working")]))

    assert result.verdict == "in_profile_not_in_resume" and result.decided_by == "profile"
    assert [(e.source, e.quote) for e in result.evidence] == [
        ("profile", "docker: 3 years, working")
    ]
    assert "Add it to the resume" in result.explanation


def test_a_stack_that_is_still_being_learned_does_not_support_the_requirement() -> None:
    requirement = req("Docker", keywords=[kw("Docker")])

    result = _check(requirement, profile(stacks=[stack("Docker", 1, "learning")]))

    assert result.verdict == "missing"


def test_not_enough_profile_years_leaves_the_finding_as_it_was() -> None:
    requirement = req("5+ years of Go", min_years=5, keywords=[kw("Go")])

    result = _check(requirement, profile(stacks=[stack("Go", 3, "proficient")]))

    assert result.verdict == "missing" and result.explanation == "before"


def test_years_equal_to_the_minimum_count() -> None:
    requirement = req("5+ years of Go", min_years=5, keywords=[kw("Go")])

    assert (
        _check(requirement, profile(stacks=[stack("Go", 5)])).verdict == "in_profile_not_in_resume"
    )


def test_the_profile_years_of_a_stack_complete_a_partial_resume() -> None:
    requirement = req("5+ years of Java", min_years=5, keywords=[kw("Java")])
    resume_evidence = [Evidence(source="resume", quote="Built Java services")]

    result = _check(
        requirement,
        profile(stacks=[stack("Java", 6, "expert")]),
        verdict="partial",
        evidence=resume_evidence,
    )

    assert result.verdict == "in_profile_not_in_resume"
    assert [e.source for e in result.evidence] == ["resume", "profile"]
    assert result.evidence[0].quote == "Built Java services"


def test_a_synonym_or_alias_of_the_keyword_matches_the_stack() -> None:
    by_alias = req("Kubernetes", keywords=[kw("Kubernetes")])
    by_synonym = req("Postgres", keywords=[kw("PostgreSQL", "pg")])

    assert _check(by_alias, profile(stacks=[stack("k8s", 2)])).verdict == "in_profile_not_in_resume"
    assert (
        _check(by_synonym, profile(stacks=[stack("pg", 2)])).verdict == "in_profile_not_in_resume"
    )


def test_total_years_count_only_without_keywords() -> None:
    general = req("5+ years of experience", category="years", min_years=5)
    with_keyword = req("5+ years of Rust", min_years=5, keywords=[kw("Rust")])
    facts = profile(total_years=8)

    result = _check(general, facts)

    assert result.verdict == "in_profile_not_in_resume"
    assert [e.quote for e in result.evidence] == ["8 years coding in total"]
    assert _check(with_keyword, facts).verdict == "missing"


def test_total_years_below_the_minimum_do_not_count() -> None:
    assert (
        _check(req("10+ years", category="years", min_years=10), profile(total_years=8)).verdict
        == "missing"
    )


def test_a_language_only_in_the_profile() -> None:
    requirement = req(
        "Fluent English", category="language", keywords=[kw("English", language=True)]
    )

    result = _check(requirement, profile(languages=[lang("English", "C1")]))

    assert result.verdict == "in_profile_not_in_resume"
    assert [e.quote for e in result.evidence] == ["english: C1"]


def test_a_profile_language_below_the_asked_level_does_not_count() -> None:
    requirement = req(
        "Fluent English", category="language", keywords=[kw("English", language=True)]
    )

    assert _check(requirement, profile(languages=[lang("English", "B2")])).verdict == "missing"


def test_a_language_without_a_level_asked_accepts_any_profile_level() -> None:
    requirement = req("English", category="language", keywords=[kw("English", language=True)])

    assert _check(requirement, profile(languages=[lang("English", "A2")])).verdict == (
        "in_profile_not_in_resume"
    )


def test_a_notable_fact_that_contains_a_keyword() -> None:
    requirement = req("Fintech experience", category="domain", keywords=[kw("fintech")])
    fact = "Built the payments platform of a fintech"

    result = _check(requirement, profile(facts=[fact, "Unrelated fact"]))

    assert result.verdict == "in_profile_not_in_resume"
    assert [(e.source, e.quote) for e in result.evidence] == [("profile", fact)]


def test_a_short_keyword_never_matches_a_fact_on_its_own() -> None:
    requirement = req("Go", keywords=[kw("Go")])

    assert _check(requirement, profile(facts=["Go-to-market lead"])).verdict == "missing"


def test_facts_do_not_prove_years() -> None:
    requirement = req(
        "5+ years of fintech", category="domain", min_years=5, keywords=[kw("fintech")]
    )

    assert _check(requirement, profile(facts=["Worked in fintech"])).verdict == "missing"


def test_nothing_in_the_profile_leaves_the_finding_untouched() -> None:
    requirement = req("Terraform", keywords=[kw("Terraform")])
    finding = _finding(requirement)

    assert (
        check(requirement.requirement, finding, profile(stacks=[stack("Docker", 3)]), "en")
        == finding
    )


def test_met_is_never_changed() -> None:
    requirement = req("Docker", keywords=[kw("Docker")])
    evidence = [Evidence(source="resume", quote="Used Docker")]

    result = _check(
        requirement, profile(stacks=[stack("Docker", 3)]), verdict="met", evidence=evidence
    )

    assert result.verdict == "met" and result.decided_by == "judge"


def test_the_evidence_is_at_most_three_profile_entries() -> None:
    requirement = req("Cloud", keywords=[kw("cloud")])
    facts = [f"Cloud project {n}" for n in range(5)]

    result = _check(requirement, profile(facts=facts))

    assert len(result.evidence) == 3


def test_every_profile_quote_is_a_fact_or_composed_only_of_profile_values() -> None:
    facts = profile(
        stacks=[stack("Docker", 3, "working")],
        languages=[lang("English", "C1")],
        total_years=8,
        facts=["Built the payments platform of a fintech"],
    )
    cases = [
        req("Docker", keywords=[kw("Docker")]),
        req("Fluent English", category="language", keywords=[kw("English", language=True)]),
        req("5+ years", category="years", min_years=5),
        req("Fintech", category="domain", keywords=[kw("fintech")]),
    ]
    allowed = (
        {f"{s.name}: {s.years:g} years, {s.level}" for s in facts.stacks}
        | {f"{language.name}: {language.level}" for language in facts.languages}
        | {f"{facts.total_years_coding:g} years coding in total"}
        | set(facts.notable_facts)
    )

    for case in cases:
        result = _check(case, facts)
        assert result.verdict == "in_profile_not_in_resume"
        assert {e.quote for e in result.evidence if e.source == "profile"} <= allowed


def test_the_flags_of_the_earlier_step_are_kept() -> None:
    requirement = req("Docker", keywords=[kw("Docker")])

    result = _check(
        requirement, profile(stacks=[stack("Docker", 3)]), flags=["evidence_not_verbatim"]
    )

    assert result.flags == ["evidence_not_verbatim"]


def test_the_explanation_follows_the_job_language() -> None:
    requirement = req("Docker", keywords=[kw("Docker")])
    finding = _finding(requirement)

    result = check(requirement.requirement, finding, profile(stacks=[stack("Docker", 3)]), "pt")

    assert "Inclua no currículo" in result.explanation
