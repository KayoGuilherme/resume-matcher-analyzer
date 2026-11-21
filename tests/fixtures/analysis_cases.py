"""Two complete analysis cases (English and Portuguese): a resume with hand-made vectors, a job,
a profile, the scripted answer of the judge and the expected findings, so that every step and the
evidence rule are checked against exact expectations."""

from dataclasses import dataclass, field

from app.ai.extraction.models import Education, LanguageSkill
from app.ai.matching.models import AnalysisInput, JudgeAnswer, JudgeBatch
from tests.ai.matching.builders import (
    chunk,
    exp,
    job_input,
    kw,
    lang,
    profile,
    req,
    resume_input,
    stack,
)

Expected = tuple[str, str, str, tuple[tuple[str, str], ...], tuple[str, ...]]
# (requirement text, verdict, decided_by, ((source, quote), ...), flags)


@dataclass(frozen=True)
class Case:
    inputs: AnalysisInput
    judge_calls: list[JudgeBatch]
    expected: list[Expected]
    found: list[tuple[str, str]]  # (ATS keyword, matched text)
    missing: list[str]
    warnings: dict[str, int]
    language: str
    secrets: list[str] = field(default_factory=list)


def _answer(n: int, verdict: str, *quotes: str, explanation: str = "Judged.") -> JudgeAnswer:
    return JudgeAnswer.model_validate(
        {"requirement": n, "verdict": verdict, "quotes": list(quotes), "explanation": explanation}
    )


# ---------------------------------------------------------------------------------- English

EN_SKILLS = "Python, FastAPI, PostgreSQL, Docker, Git"
EN_API = "Built REST APIs in Python and FastAPI serving 2M requests per day"
EN_DB = "Migrated the billing service to PostgreSQL and cut query time by 60%"
EN_K8S = "Deployed services on K8s using Helm charts"
EN_JAVA = "Maintained Java services for the logistics team"
EN_TEXT = f"""Jane Doe
SUMMARY
Backend developer who likes small, well tested services.
EXPERIENCE
Backend Developer, ACME (Mar 2019 - Aug 2023)
- {EN_API}
- {EN_DB}
- {EN_K8S}
Junior Developer, Beta Corp (Jun 2017 - Feb 2019)
- {EN_JAVA}
SKILLS
{EN_SKILLS}
LANGUAGES
English - Intermediate
Portuguese - Native
EDUCATION
B.Sc. Computer Science - State University
"""

_NONE = (0.0, 0.0, 0.0, -1.0)  # similar to nothing in the resume


def english() -> Case:
    resume = resume_input(
        EN_TEXT,
        chunks=[
            chunk(EN_SKILLS, 0, (0.5, 0.5, 0.5, 0.5), section="skills"),
            chunk(EN_API, 1, (1.0, 0.0, 0.0, 0.0)),
            chunk(EN_DB, 2, (0.0, 1.0, 0.0, 0.0)),
            chunk(EN_K8S, 3, (0.0, 0.0, 1.0, 0.0)),
            chunk(EN_JAVA, 4, (0.0, 0.0, 0.0, 1.0)),
        ],
        experiences=[
            exp(EN_API, EN_DB, EN_K8S, title="Backend Developer", start="2019-03", end="2023-08"),
            exp(EN_JAVA, title="Junior Developer", start="2017-06", end="2019-02"),
        ],
        languages=[
            LanguageSkill(name="English", level="Intermediate"),
            LanguageSkill(name="Portuguese", level="Native"),
        ],
        education=[
            Education(
                institution="State University",
                degree="B.Sc.",
                field_of_study="Computer Science",
                start_year=None,
                end_year=None,
            )
        ],
    )
    job = job_input(
        req(
            "5+ years of backend development",
            category="years",
            min_years=5,
            keywords=[kw("backend")],
            vector=(1.0, 0.0, 0.0, 0.0),
        ),
        req("Python", keywords=[kw("Python")], vector=(1.0, 0.0, 0.0, 0.0)),
        req("Kubernetes", keywords=[kw("Kubernetes")], vector=(0.0, 0.0, 1.0, 0.0)),
        req(
            "Fluent English",
            category="language",
            keywords=[kw("English", language=True)],
            vector=_NONE,
        ),
        req("Terraform", priority="nice_to_have", keywords=[kw("Terraform")], vector=_NONE),
        req("AWS", keywords=[kw("AWS")], vector=_NONE),
        req(
            "Bachelor's degree in Computer Science",
            category="education",
            keywords=[kw("computer science")],
            vector=_NONE,
        ),
        req(
            "Message queues (Kafka or RabbitMQ)",
            keywords=[kw("Kafka"), kw("RabbitMQ")],
            vector=(0.8, 0.6, 0.0, 0.0),
        ),
        ats_keywords=[
            "python",
            "fastapi",
            "kubernetes",
            "terraform",
            "postgresql",
            "docker",
            "kafka",
        ],  # fmt: skip
    )
    facts = profile(
        stacks=[stack("AWS", 3, "working"), stack("Python", 6, "expert")],
        languages=[lang("English", "C1")],
    )
    judged = JudgeBatch(
        answers=[
            _answer(1, "partial", EN_API, explanation="About 4.5 years of backend work."),
            _answer(2, "partial", "English - Intermediate", explanation="Intermediate only."),
            _answer(3, "met", "Designed event-driven systems with Kafka"),  # invented
        ]
    )
    expected: list[Expected] = [
        (
            "5+ years of backend development",
            "partial",
            "judge",
            (("resume", EN_API),),
            (),
        ),
        ("Python", "met", "deterministic", (("resume", EN_SKILLS), ("resume", EN_API)), ()),
        ("Kubernetes", "met", "deterministic", (("resume", EN_K8S),), ()),
        (
            "Fluent English",
            "in_profile_not_in_resume",
            "profile",
            (("resume", "English - Intermediate"), ("profile", "english: C1")),
            (),
        ),
        ("Terraform", "missing", "semantic", (), ()),
        ("AWS", "in_profile_not_in_resume", "profile", (("profile", "aws: 3 years, working"),), ()),
        (
            "Bachelor's degree in Computer Science",
            "met",
            "deterministic",
            (("resume", "B.Sc. Computer Science - State University"),),
            (),
        ),
        ("Message queues (Kafka or RabbitMQ)", "missing", "judge", (), ("evidence_not_verbatim",)),
    ]
    return Case(
        inputs=AnalysisInput(resume=resume, job=job, profile=facts),
        judge_calls=[judged],
        expected=expected,
        found=[
            ("python", "Python"),
            ("fastapi", "FastAPI"),
            ("kubernetes", "K8s"),
            ("postgresql", "PostgreSQL"),
            ("docker", "Docker"),
        ],
        missing=["terraform", "kafka"],
        warnings={"dropped_unverified_evidence": 1, "verdicts_downgraded_to_missing": 1},
        language="en",
        secrets=[EN_API, EN_K8S, "Jane Doe", "State University"],
    )


# ------------------------------------------------------------------------------- Portuguese

PT_SKILLS = "Java, Spring Boot, PostgreSQL, Docker"
PT_JAVA = "Desenvolvi serviços em Java para o sistema de cobrança"
PT_DOCKER = "Padronizei os ambientes com Docker e Docker Compose"
PT_COM = "Alinhava prioridades semanalmente com o time de produto"
PT_TEXT = f"""Maria Souza
EXPERIÊNCIA
Desenvolvedora Java, Empresa X (jan. 2018 - dez. 2021)
- {PT_JAVA}
- {PT_DOCKER}
- {PT_COM}
HABILIDADES
{PT_SKILLS}
IDIOMAS
Inglês: Avançado
FORMAÇÃO
Bacharelado em Ciência da Computação - Universidade Federal
"""


def portuguese() -> Case:
    resume = resume_input(
        PT_TEXT,
        chunks=[
            chunk(PT_SKILLS, 0, (0.5, 0.5, 0.5, 0.5), section="skills"),
            chunk(PT_JAVA, 1, (1.0, 0.0, 0.0, 0.0)),
            chunk(PT_DOCKER, 2, (0.0, 1.0, 0.0, 0.0)),
            chunk(PT_COM, 3, (0.0, 0.0, 1.0, 0.0)),
        ],
        experiences=[
            exp(
                PT_JAVA,
                PT_DOCKER,
                PT_COM,
                title="Desenvolvedora Java",
                start="2018-01",
                end="2021-12",
            ),
        ],
        languages=[LanguageSkill(name="Inglês", level="Avançado")],
        education=[
            Education(
                institution="Universidade Federal",
                degree="Bacharelado",
                field_of_study="Ciência da Computação",
                start_year=None,
                end_year=None,
            )
        ],
    )
    job = job_input(
        req(
            "Inglês avançado",
            category="language",
            keywords=[kw("Inglês", language=True)],
            vector=_NONE,
        ),
        req("Experiência com Docker", keywords=[kw("Docker")], vector=(0.0, 1.0, 0.0, 0.0)),
        req(
            "Conhecimento em Kubernetes",
            priority="nice_to_have",
            keywords=[kw("Kubernetes")],
            vector=_NONE,
        ),
        req(
            "3+ anos de experiência com Java",
            min_years=3,
            keywords=[kw("Java")],
            vector=(1.0, 0.0, 0.0, 0.0),
        ),
        req(
            "Formação superior em Ciência da Computação",
            category="education",
            keywords=[kw("ciência da computação")],
            vector=_NONE,
        ),
        req(
            "Experiência com fintech",
            category="domain",
            keywords=[kw("fintech")],
            vector=_NONE,
        ),
        req(
            "Comunicação clara com times de produto",
            category="soft",
            keywords=[],
            vector=(0.0, 0.0, 1.0, 0.0),
        ),
        language="pt",
        ats_keywords=["java", "spring boot", "kubernetes", "docker"],
    )
    facts = profile(
        facts=["Construí a plataforma de pagamentos de uma fintech"],
        languages=[lang("Inglês", "C1")],
    )
    judged = JudgeBatch(
        answers=[_answer(1, "met", PT_COM, explanation="Alinha com o time de produto.")]
    )
    expected: list[Expected] = [
        ("Inglês avançado", "met", "deterministic", (("resume", "Inglês: Avançado"),), ()),
        (
            "Experiência com Docker",
            "met",
            "deterministic",
            (("resume", PT_SKILLS), ("resume", PT_DOCKER)),
            (),
        ),
        ("Conhecimento em Kubernetes", "missing", "semantic", (), ()),
        ("3+ anos de experiência com Java", "met", "deterministic", (("resume", PT_JAVA),), ()),
        (
            "Formação superior em Ciência da Computação",
            "met",
            "deterministic",
            (("resume", "Bacharelado em Ciência da Computação - Universidade Federal"),),
            (),
        ),
        (
            "Experiência com fintech",
            "in_profile_not_in_resume",
            "profile",
            (("profile", "Construí a plataforma de pagamentos de uma fintech"),),
            (),
        ),
        (
            "Comunicação clara com times de produto",
            "met",
            "judge",
            (("resume", PT_COM),),
            (),
        ),
    ]
    return Case(
        inputs=AnalysisInput(resume=resume, job=job, profile=facts),
        judge_calls=[judged],
        expected=expected,
        found=[("java", "Java"), ("spring boot", "Spring Boot"), ("docker", "Docker")],
        missing=["kubernetes"],
        warnings={},
        language="pt",
        secrets=[PT_JAVA, PT_COM, "Maria Souza", "Universidade Federal"],
    )
