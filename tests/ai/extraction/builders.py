"""Small builders so extraction tests stay readable."""

from app.ai.extraction.models import (
    Certification,
    Education,
    ExtractedExperience,
    ExtractedProject,
    ExtractedResume,
    LanguageSkill,
    SkillLine,
)


def experience(
    *bullets: str,
    title: str = "Backend Developer",
    start: str | None = "2020-01",
    end: str | None = "2021-12",
    is_current: bool = False,
) -> ExtractedExperience:
    return ExtractedExperience(
        title=title,
        company="ACME",
        start=start,
        end=end,
        is_current=is_current,
        bullets=list(bullets),
    )


def extracted(
    *,
    experiences: list[ExtractedExperience] | None = None,
    skills: list[str] | None = None,
    projects: list[ExtractedProject] | None = None,
    summary: str | None = None,
) -> ExtractedResume:
    return ExtractedResume(
        summary=summary,
        skills=[SkillLine(text=text, names=[]) for text in skills or []],
        experiences=experiences or [],
        education=[
            Education(
                institution="USP",
                degree="BSc",
                field_of_study="Computer Science",
                start_year=2014,
                end_year=2018,
            )
        ],
        languages=[LanguageSkill(name="Portuguese", level="native")],
        certifications=[Certification(name="AWS SAA", issuer="AWS", date="2022")],
        projects=projects or [],
    )


RESUME_TEXT = """\
Resumo
Desenvolvedora backend com foco em APIs.

Experiência
Backend Developer - ACME                                   01/2020 - 12/2021
• Built a payments API with Spring Boot and
  PostgreSQL
• Reduced p95 latency by 40%

Habilidades
Languages: Java, Python, SQL
Cloud: AWS, Docker

Projetos
Resume Matcher
- Matches resumes against job posts
"""
