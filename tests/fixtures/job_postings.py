"""Job postings in English and Portuguese with a scripted model answer and the expected result.

The scripted answers deliberately contain what the code must fix or drop: a requirement the
posting does not have, a priority that contradicts the wording, alias keywords and duplicate
synonyms, and a duplicated requirement. `Expected` is what extraction must return.
"""

from dataclasses import dataclass, field

from app.ai.extraction.job_models import ExtractedJob
from tests.ai.extraction.job_builders import job, keyword, requirement

# (source_text, text, category, priority, min_years, priority_unclear, [(normalized, synonyms)])
Summary = tuple[str, str, str, str, float | None, bool, list[tuple[str, list[str]]]]


@dataclass(frozen=True)
class Posting:
    name: str
    text: str
    answers: list[ExtractedJob]  # the model's answers in order (more than one: a correction)
    language: str
    seniority: str | None
    requirements: list[Summary]
    responsibilities: list[str]
    ats_keywords: list[str]
    warnings: dict[str, int] = field(default_factory=dict)
    llm_calls: int = 1


ENGLISH_TEXT = """\
Senior Backend Engineer - Payments

About the role
We build the payments platform used by thousands of merchants.
You will design and build REST APIs, mentor junior engineers and own services in production.

Requirements:
- 5+ years of professional experience in backend development
- 3+ years of Java or Kotlin
- Strong knowledge of PostgreSQL and SQL
- Fluent English
- Bachelor's degree in Computer Science or a related field
- Experience with Docker and
  Kubernetes
- Ability to work in a team

Nice to have:
- Experience with Terraform
- Knowledge of the fintech domain
- AWS certification is a plus
"""

_E_YEARS = "5+ years of professional experience in backend development"
_E_JAVA = "3+ years of Java or Kotlin"
_E_SQL = "Strong knowledge of PostgreSQL and SQL"
_E_ENGLISH = "Fluent English"
_E_DEGREE = "Bachelor's degree in Computer Science or a related field"
_E_DOCKER = "Experience with Docker and Kubernetes"  # wrapped over two lines in the posting
_E_TEAM = "Ability to work in a team"
_E_TERRAFORM = "Experience with Terraform"
_E_FINTECH = "Knowledge of the fintech domain"
_E_AWS = "AWS certification is a plus"
_E_RESPONSIBILITY = (
    "You will design and build REST APIs, mentor junior engineers and own services in production."
)


def _english_answer() -> ExtractedJob:
    return job(
        requirement(
            _E_YEARS,
            text="Backend development experience",
            category="years",
            min_years=5,
            keywords=[keyword("Backend")],
        ),
        requirement(
            _E_JAVA,
            text="Java or Kotlin",
            min_years=3,
            priority="nice_to_have",  # wrong: it sits under "Requirements:"
            keywords=[keyword("Java", "java", "JVM"), keyword("Kotlin")],
        ),
        requirement(
            _E_SQL,
            text="PostgreSQL and SQL",
            priority="must_have",
            keywords=[keyword("Postgres", "PostgreSQL"), keyword("SQL")],
        ),
        requirement(
            _E_ENGLISH,
            text="Fluent English",
            category="language",
            keywords=[keyword("English", "EN")],
        ),
        requirement(
            _E_DEGREE,
            text="Computer Science degree",
            category="education",
            keywords=[keyword("Computer Science")],
        ),
        requirement(
            _E_DOCKER,
            text="Docker and Kubernetes",
            keywords=[keyword("Docker"), keyword("K8s", "Kubernetes", "kube")],
        ),
        requirement(_E_TEAM, text="Teamwork", category="soft"),
        requirement(
            _E_TERRAFORM,
            text="Terraform",
            priority="must_have",  # wrong: it sits under "Nice to have:"
            keywords=[keyword("Terraform")],
        ),
        requirement(
            _E_FINTECH, text="Fintech domain knowledge", category="domain", priority="unclear"
        ),
        requirement(
            _E_AWS,
            text="AWS certification",
            category="education",
            priority="must_have",  # wrong: "a plus"
            keywords=[keyword("AWS")],
        ),
        requirement("5 years of Rust experience", text="Rust", min_years=5),  # invented
        requirement(  # a duplicate of the Docker requirement
            _E_DOCKER, text="docker and kubernetes", keywords=[keyword("Docker")]
        ),
        seniority="senior",
        language="en",
        responsibilities=[_E_RESPONSIBILITY, "You will manage the engineering budget."],
        ats_keywords=["Java", "Kotlin", "Postgres", "SQL", "Docker", "K8s", "Kubernetes", "REST"],
    )


ENGLISH = Posting(
    name="english",
    text=ENGLISH_TEXT,
    answers=[_english_answer(), _english_answer()],  # the correction round does not fix it
    language="en",
    seniority="senior",
    requirements=[
        (
            _E_YEARS,
            "Backend development experience",
            "years",
            "must_have",
            5,
            False,
            [("backend", [])],
        ),
        (
            _E_JAVA,
            "Java or Kotlin",
            "skill",
            "must_have",
            3,
            False,
            [("java", ["jvm"]), ("kotlin", [])],
        ),
        (
            _E_SQL,
            "PostgreSQL and SQL",
            "skill",
            "must_have",
            None,
            False,
            [("postgresql", []), ("sql", [])],
        ),
        (_E_ENGLISH, "Fluent English", "language", "must_have", None, False, [("english", [])]),
        (
            _E_DEGREE,
            "Computer Science degree",
            "education",
            "must_have",
            None,
            False,
            [("computer science", [])],
        ),
        (
            _E_DOCKER,
            "Docker and Kubernetes",
            "skill",
            "must_have",
            None,
            False,
            [("docker", []), ("kubernetes", ["kube"])],
        ),
        (_E_TEAM, "Teamwork", "soft", "must_have", None, False, []),
        (_E_TERRAFORM, "Terraform", "skill", "nice_to_have", None, False, [("terraform", [])]),
        (
            _E_FINTECH,
            "Fintech domain knowledge",
            "domain",
            "nice_to_have",
            None,
            False,
            [],
        ),
        (_E_AWS, "AWS certification", "education", "nice_to_have", None, False, [("aws", [])]),
    ],
    responsibilities=[_E_RESPONSIBILITY],
    ats_keywords=["java", "kotlin", "postgresql", "sql", "docker", "kubernetes", "rest"],
    warnings={"dropped_unverified_items": 2},
    llm_calls=2,
)

PORTUGUESE_TEXT = """\
Desenvolvedor(a) Backend Pleno - Plataforma de Pagamentos

Sobre a vaga
Atuar no desenvolvimento de APIs e na evolução da nossa plataforma de pagamentos.
Participar de revisões de código e da definição da arquitetura.

Requisitos obrigatórios:
- Experiência sólida com Java e Spring Boot
- Mais de 3 anos de experiência com desenvolvimento backend
- Inglês avançado obrigatório
- Conhecimento em bancos de dados relacionais (Postgres)
- Graduação em Ciência da Computação ou áreas afins

Diferenciais:
- Experiência com Kubernetes
- Conhecimento em arquitetura de microsserviços
- Vivência no setor financeiro
- Docker é obrigatório para nossa stack
"""

_P_JAVA = "Experiência sólida com Java e Spring Boot"
_P_YEARS = "Mais de 3 anos de experiência com desenvolvimento backend"
_P_ENGLISH = "Inglês avançado obrigatório"
_P_DB = "Conhecimento em bancos de dados relacionais (Postgres)"
_P_DEGREE = "Graduação em Ciência da Computação ou áreas afins"
_P_K8S = "Experiência com Kubernetes"
_P_MICRO = "Conhecimento em arquitetura de microsserviços"
_P_FINANCE = "Vivência no setor financeiro"
_P_DOCKER = "Docker é obrigatório para nossa stack"
_P_RESP_1 = "Atuar no desenvolvimento de APIs e na evolução da nossa plataforma de pagamentos."
_P_RESP_2 = "Participar de revisões de código e da definição da arquitetura."


def _portuguese_answer(java_source: str) -> ExtractedJob:
    return job(
        requirement(
            java_source,
            text="Java e Spring Boot",
            keywords=[keyword("Java"), keyword("Springboot", "Spring Boot")],
        ),
        requirement(
            _P_YEARS, text="Experiência em desenvolvimento backend", category="years", min_years=3
        ),
        requirement(
            _P_ENGLISH,
            text="Inglês avançado",
            category="language",
            priority="nice_to_have",  # wrong: "obrigatório"
            keywords=[keyword("Inglês", "Ingles", "EN")],
        ),
        requirement(
            _P_DB,
            text="Bancos de dados relacionais",
            keywords=[keyword("Postgres"), keyword("SQL")],
        ),
        requirement(_P_DEGREE, text="Graduação em Ciência da Computação", category="education"),
        requirement(
            _P_K8S, text="Kubernetes", priority="unclear", keywords=[keyword("k8s", "Kubernetes")]
        ),
        requirement(_P_MICRO, text="Arquitetura de microsserviços", category="domain"),
        requirement(
            _P_FINANCE, text="Setor financeiro", category="domain", priority="nice_to_have"
        ),
        requirement(
            _P_DOCKER,
            text="Docker",
            priority="nice_to_have",  # wrong: own cue "obrigatório" beats "Diferenciais"
            keywords=[keyword("Docker")],
        ),
        seniority="mid",
        language="pt",
        responsibilities=[_P_RESP_1, _P_RESP_2],
        ats_keywords=["Java", "Springboot", "Spring Boot", "Postgres", "Kubernetes", "Docker"],
    )


PORTUGUESE = Posting(
    name="portuguese",
    text=PORTUGUESE_TEXT,
    # The first answer paraphrases one source text ("em" for "com"); the correction fixes it.
    answers=[
        _portuguese_answer("Experiência sólida em Java e Spring Boot"),
        _portuguese_answer(_P_JAVA),
    ],
    language="pt",
    seniority="mid",
    requirements=[
        (
            _P_JAVA,
            "Java e Spring Boot",
            "skill",
            "must_have",
            None,
            False,
            [("java", []), ("spring boot", [])],
        ),
        (
            _P_YEARS,
            "Experiência em desenvolvimento backend",
            "years",
            "must_have",
            3,
            False,
            [],
        ),
        (
            _P_ENGLISH,
            "Inglês avançado",
            "language",
            "must_have",
            None,
            False,
            [("english", [])],
        ),
        (
            _P_DB,
            "Bancos de dados relacionais",
            "skill",
            "must_have",
            None,
            False,
            [("postgresql", []), ("sql", [])],
        ),
        (
            _P_DEGREE,
            "Graduação em Ciência da Computação",
            "education",
            "must_have",
            None,
            False,
            [],
        ),
        (_P_K8S, "Kubernetes", "skill", "nice_to_have", None, False, [("kubernetes", [])]),
        (
            _P_MICRO,
            "Arquitetura de microsserviços",
            "domain",
            "nice_to_have",
            None,
            False,
            [],
        ),
        (_P_FINANCE, "Setor financeiro", "domain", "nice_to_have", None, False, []),
        (_P_DOCKER, "Docker", "skill", "must_have", None, False, [("docker", [])]),
    ],
    responsibilities=[_P_RESP_1, _P_RESP_2],
    ats_keywords=["java", "spring boot", "postgresql", "kubernetes", "docker"],
    warnings={},
    llm_calls=2,
)

UNCLEAR_TEXT = """\
Software Engineer

About you
- Experience with Redis
- Comfortable with Linux
- Ideally some exposure to Go
- Python is required, Go is a plus

We offer remote work and a gym membership.
"""

UNCLEAR = Posting(
    name="unclear",
    text=UNCLEAR_TEXT,
    answers=[
        job(
            requirement("Experience with Redis", text="Redis", priority="unclear"),
            requirement("Comfortable with Linux", text="Linux", priority="must_have"),
            requirement("Ideally some exposure to Go", text="Go", priority="must_have"),
            requirement("Python is required, Go is a plus", text="Python", priority="nice_to_have"),
        )
    ],
    language="en",
    seniority=None,
    requirements=[
        ("Experience with Redis", "Redis", "skill", "must_have", None, True, []),
        ("Comfortable with Linux", "Linux", "skill", "must_have", None, False, []),
        ("Ideally some exposure to Go", "Go", "skill", "nice_to_have", None, False, []),
        ("Python is required, Go is a plus", "Python", "skill", "must_have", None, True, []),
    ],
    responsibilities=[],
    ats_keywords=[],
    warnings={"priority_unclear_requirements": 2},
    llm_calls=1,
)

POSTINGS = [ENGLISH, PORTUGUESE, UNCLEAR]
