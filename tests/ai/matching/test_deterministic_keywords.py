from datetime import date

from app.ai.extraction.models import Certification, Education
from app.ai.extraction.verify import is_verbatim, normalize
from app.ai.matching.deterministic import Hints, Settled, check
from app.ai.matching.text import ResumeIndex
from tests.ai.matching.builders import chunk, kw, req, resume_input

TODAY = date(2026, 1, 15)


def _check(requirement_input, resume):  # type: ignore[no-untyped-def]
    return check(requirement_input.requirement, ResumeIndex(resume), TODAY)


def _met(outcome: Settled | Hints) -> Settled:
    assert isinstance(outcome, Settled), outcome
    assert outcome.verdict == "met"
    return outcome


def test_an_alias_is_found_and_the_bullet_is_the_evidence() -> None:
    bullet = "Deployed services on K8s"
    resume = resume_input(f"EXPERIENCE\n{bullet}\n", chunks=[chunk(bullet)])

    outcome = _met(_check(req("Kubernetes", keywords=[kw("Kubernetes")]), resume))

    assert [e.quote for e in outcome.evidence] == [bullet]
    assert outcome.evidence[0].source == "resume"
    assert outcome.code == "keyword_found" and outcome.params == {"keyword": "K8s"}


def test_a_synonym_is_found_and_the_skills_line_is_the_evidence() -> None:
    line = "Postgres, Redis, Docker"
    resume = resume_input(f"SKILLS\n{line}\n", chunks=[chunk(line, section="skills")])
    requirement = req("PostgreSQL", keywords=[kw("PostgreSQL", "postgres")])

    outcome = _met(_check(requirement, resume))

    assert [e.quote for e in outcome.evidence] == [line]


def test_java_is_not_found_in_javascript() -> None:
    resume = resume_input("Wrote JavaScript\n", chunks=[chunk("Wrote JavaScript")])

    outcome = _check(req("Java", keywords=[kw("Java")]), resume)

    assert isinstance(outcome, Hints) and outcome.keyword_chunks == ()


def test_symbols_are_matched_whole() -> None:
    resume = resume_input("Wrote C++ services\n", chunks=[chunk("Wrote C++ services")])

    assert isinstance(_check(req("C++", keywords=[kw("C++")]), resume), Settled)
    assert isinstance(_check(req("C", keywords=[kw("C")]), resume), Hints)


def test_accents_are_ignored() -> None:
    resume = resume_input(
        "Experiência em programacao\n", chunks=[chunk("Experiência em programacao")]
    )

    _met(_check(req("Programação", category="soft", keywords=[kw("Programação")]), resume))


def test_an_ambiguous_short_name_is_only_a_hint() -> None:
    bullet = "Go-to-market planning"
    resume = resume_input(bullet, chunks=[chunk(bullet)])

    outcome = _check(req("Go", keywords=[kw("Go")]), resume)

    assert isinstance(outcome, Hints)
    assert [c.text for c in outcome.keyword_chunks] == [bullet]


def test_no_match_settles_nothing_and_never_missing_for_a_skill() -> None:
    resume = resume_input("Wrote Python\n", chunks=[chunk("Wrote Python")])

    for category in ("skill", "domain", "soft", "years"):
        outcome = _check(req("Rust", category=category, keywords=[kw("Rust")]), resume)
        assert isinstance(outcome, Hints)


def test_a_requirement_without_keywords_settles_nothing() -> None:
    resume = resume_input("Wrote Python\n", chunks=[chunk("Wrote Python")])

    assert isinstance(_check(req("Strong sense of ownership", category="soft"), resume), Hints)


def test_evidence_is_a_resume_line_when_the_match_is_outside_the_chunks() -> None:
    resume = resume_input(
        "EDUCATION\nB.Sc. Computer Science - State University\nSKILLS\nPython",
        education=[
            Education(
                institution="State University",
                degree="B.Sc.",
                field_of_study=None,
                start_year=None,
                end_year=None,
            )
        ],
    )
    requirement = req(
        "Computer science degree", category="education", keywords=[kw("computer science")]
    )

    outcome = _met(_check(requirement, resume))

    assert [e.quote for e in outcome.evidence] == ["B.Sc. Computer Science - State University"]


def test_at_most_three_pieces_of_evidence_in_resume_order() -> None:
    chunks = [chunk(f"Used Python in project {n}", n) for n in range(5)]
    resume = resume_input("\n".join(c.text for c in chunks), chunks=chunks)

    outcome = _met(_check(req("Python", keywords=[kw("Python")]), resume))

    assert [e.quote for e in outcome.evidence] == [c.text for c in chunks[:3]]


def test_every_quote_is_found_verbatim_in_the_resume_text() -> None:
    bullet = "Led the   migration to\nKubernetes"
    resume = resume_input(f"EXPERIENCE\n{bullet}\n", chunks=[chunk(bullet)])

    outcome = _met(_check(req("Kubernetes", keywords=[kw("Kubernetes")]), resume))

    assert all(is_verbatim(e.quote, normalize(resume.text)) for e in outcome.evidence)


def test_education_without_any_section_is_missing_by_the_deterministic_step() -> None:
    resume = resume_input("Python developer\n", chunks=[chunk("Python developer")])
    requirement = req(
        "Computer science degree", category="education", keywords=[kw("computer science")]
    )

    outcome = _check(requirement, resume)

    assert isinstance(outcome, Settled)
    assert outcome.verdict == "missing" and outcome.evidence == ()
    assert outcome.code == "education_section_absent"


def test_education_with_an_entry_settles_nothing_when_the_keywords_are_not_found() -> None:
    resume = resume_input(
        "EDUCATION\nHistory - State University",
        education=[
            Education(
                institution="State University",
                degree=None,
                field_of_study="History",
                start_year=None,
                end_year=None,
            )
        ],
    )
    requirement = req(
        "Computer science degree", category="education", keywords=[kw("computer science")]
    )

    assert isinstance(_check(requirement, resume), Hints)


def test_a_certification_counts_as_an_education_section() -> None:
    resume = resume_input(
        "CERTIFICATIONS\nAWS Certified",
        certifications=[Certification(name="AWS Certified", issuer=None, date=None)],
    )
    requirement = req("A degree", category="education", keywords=[kw("degree")])

    assert isinstance(_check(requirement, resume), Hints)


def test_the_section_rule_applies_to_education_only() -> None:
    resume = resume_input("Python developer\n")

    outcome = _check(req("Rust", category="skill", keywords=[kw("Rust")]), resume)

    assert isinstance(outcome, Hints)
