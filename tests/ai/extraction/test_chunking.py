import uuid

from app.ai.extraction.chunking import build_chunks
from app.ai.extraction.models import Experience, ExtractedProject, Project, Resume, SkillLine
from tests.ai.extraction.builders import extracted


def _resume(
    experiences: list[list[str]] | None = None,
    skills: list[str] | None = None,
    projects: list[list[str]] | None = None,
) -> Resume:
    base = extracted()
    return Resume(
        summary="A summary that is not chunked",
        skills=[SkillLine(text=text, names=[]) for text in skills or []],
        experiences=[
            Experience(
                id=uuid.uuid4(),
                title="Dev",
                company="ACME",
                start="2020-01",
                end="2020-12",
                is_current=False,
                bullets=bullets,
            )
            for bullets in experiences or []
        ],
        education=base.education,
        languages=base.languages,
        certifications=base.certifications,
        projects=[
            Project(
                **ExtractedProject(name="P", bullets=bullets, technologies=[]).model_dump(),
                id=uuid.uuid4(),
            )
            for bullets in projects or []
        ],
    )


def test_each_bullet_and_each_skills_line_becomes_a_chunk() -> None:
    resume = _resume(
        experiences=[["a1", "a2", "a3"], ["b1", "b2"]],
        skills=["Languages: Java", "Cloud: AWS"],
        projects=[["p1", "p2"]],
    )

    chunks = build_chunks(resume)

    assert len(chunks) == 9
    assert [c.section for c in chunks].count("experience") == 5
    assert [c.section for c in chunks].count("projects") == 2
    assert [c.section for c in chunks].count("skills") == 2


def test_chunks_follow_the_order_skills_experience_projects_with_running_positions() -> None:
    chunks = build_chunks(_resume(experiences=[["e1"]], skills=["s1"], projects=[["p1"]]))

    assert [(c.position, c.section, c.text) for c in chunks] == [
        (0, "skills", "s1"),
        (1, "experience", "e1"),
        (2, "projects", "p1"),
    ]


def test_experience_chunks_point_to_their_experience_and_keep_the_text() -> None:
    resume = _resume(experiences=[["first", "second"], ["third"]])

    chunks = build_chunks(resume)

    first, second = resume.experiences
    assert [(c.experience_id, c.text) for c in chunks] == [
        (first.id, "first"),
        (first.id, "second"),
        (second.id, "third"),
    ]


def test_skills_and_project_chunks_have_no_experience_id() -> None:
    chunks = build_chunks(_resume(skills=["s"], projects=[["p"]]))

    assert [c.experience_id for c in chunks] == [None, None]


def test_text_is_kept_exactly_as_in_the_resume() -> None:
    text = "  Built an API — 40%   faster  "

    (chunk,) = build_chunks(_resume(experiences=[[text]]))

    assert chunk.text == text


def test_whitespace_only_items_are_skipped_and_positions_stay_dense() -> None:
    chunks = build_chunks(_resume(experiences=[["a", "  ", "", "b"]]))

    assert [(c.position, c.text) for c in chunks] == [(0, "a"), (1, "b")]


def test_a_resume_without_bullets_or_skills_has_no_chunks() -> None:
    assert build_chunks(_resume()) == []
