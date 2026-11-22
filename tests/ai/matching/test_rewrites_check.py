import pytest

from app.ai.matching.rewrites import (
    EMPTY_OR_UNCHANGED,
    TOO_LONG,
    UNSUPPORTED_NUMBER,
    UNSUPPORTED_TECHNOLOGY,
    build_corpus,
    build_vocabulary,
    check_suggestion,
    shape_names,
    technology_mentions,
)
from tests.ai.matching.builders import profile, stack

RESUME = (
    "Jane Doe\nExperience\n"
    "Built REST APIs in Python and FastAPI\n"
    "Cut query time by 60% on PostgreSQL\n"
    "Deployed services on K8s\n"
    "Skills: Python, FastAPI, PostgreSQL"
)
FACTS = profile(
    total_years=5,
    stacks=[stack("Python", 3), stack("Docker", 2), stack("Terraform", 1)],
    facts=["Won a hackathon in 2022"],
)


def check(text: str, original: str | None = None, *, resume: str = RESUME, facts=FACTS, job=()):  # type: ignore[no-untyped-def]
    corpus = build_corpus(resume, facts)
    vocabulary = build_vocabulary(
        job_keywords=job, ats_keywords=[], resume_names=["Python", "FastAPI"], profile=facts
    )
    return check_suggestion(text, original, corpus, vocabulary)


def test_an_invented_technology_is_rejected() -> None:
    assert check("Deployed services on Kafka clusters") == [UNSUPPORTED_TECHNOLOGY]


def test_a_technology_from_the_profile_is_allowed() -> None:
    assert check("Containerized services with Docker") == []


def test_kubernetes_is_allowed_when_the_resume_says_k8s() -> None:
    assert check("Deployed services on Kubernetes") == []


def test_k8s_is_rejected_when_neither_source_has_kubernetes() -> None:
    assert check("Deployed services on K8s", resume="Built APIs in Python", facts=FACTS) == [
        UNSUPPORTED_TECHNOLOGY
    ]


def test_an_invented_number_is_rejected() -> None:
    assert check("Reduced response time by 40% on PostgreSQL") == [UNSUPPORTED_NUMBER]


def test_a_number_from_the_resume_is_allowed() -> None:
    assert check("Reduced query time by 60% on PostgreSQL") == []


def test_invented_years_are_rejected() -> None:
    assert check("Seven years of Python") == [UNSUPPORTED_NUMBER]
    assert check("7 years of Python") == [UNSUPPORTED_NUMBER]


def test_years_from_the_profile_are_allowed() -> None:
    assert check("3 years of Python in production") == []
    assert check("5 years of coding") == []


def test_number_words_are_numbers() -> None:
    assert check("nine years of Docker") == [UNSUPPORTED_NUMBER]
    assert check("nove anos de Docker") == [UNSUPPORTED_NUMBER]
    assert check("two years of Docker") == []  # the profile says 2
    other = profile(total_years=1, stacks=[stack("Docker", 2)])
    assert check("five years of Docker", resume="Built APIs", facts=other) == [UNSUPPORTED_NUMBER]


def test_a_calendar_year_from_the_profile_is_allowed() -> None:
    assert check("Won a hackathon in 2022 building APIs") == []
    assert check("Won a hackathon in 2023 building APIs") == [UNSUPPORTED_NUMBER]


def test_an_unknown_technology_is_rejected_by_its_shape() -> None:
    assert check("Built dashboards with Zorbify.js") == [UNSUPPORTED_TECHNOLOGY]


def test_a_capitalized_word_in_the_middle_of_a_sentence_is_a_name() -> None:
    assert check("Built dashboards with Frobnicator") == [UNSUPPORTED_TECHNOLOGY]


def test_a_capitalized_first_word_is_not_a_name() -> None:
    assert check("Developed reporting dashboards for the finance team") == []


def test_acronyms_and_plurals_of_generic_words_are_not_names() -> None:
    assert check("Built REST APIs and an API gateway in Python") == []


def test_an_unknown_acronym_is_a_name() -> None:
    assert check("Built reports in HQLX") == [UNSUPPORTED_TECHNOLOGY]


def test_symbols_make_a_name() -> None:
    assert check("Wrote services in C++") == [UNSUPPORTED_TECHNOLOGY]
    assert check("Wrote services in C#") == [UNSUPPORTED_TECHNOLOGY]
    assert check("Wrote services in C++", resume=RESUME + "\nC++ at university") == []


def test_e_g_is_not_a_name() -> None:
    assert check("Built tools (e.g. scripts and cron jobs) in Python") == []


def test_a_job_keyword_in_neither_source_is_rejected() -> None:
    assert check("Automated releases with Jenkins", job=["jenkins"]) == [UNSUPPORTED_TECHNOLOGY]


def test_a_job_keyword_in_the_resume_is_allowed() -> None:
    assert check("Automated releases for FastAPI services", job=["fastapi"]) == []


def test_python_at_the_start_of_a_sentence_is_fine_when_in_the_resume() -> None:
    assert check("Python services behind REST APIs") == []


@pytest.mark.parametrize("text", ["", "   \n"])
def test_an_empty_text_is_rejected(text: str) -> None:
    assert check(text) == [EMPTY_OR_UNCHANGED]


def test_a_text_equal_to_the_original_is_rejected() -> None:
    original = "Built REST APIs in Python and FastAPI"

    assert check("  built REST APIs in  Python and FastAPI ", original) == [EMPTY_OR_UNCHANGED]


def test_a_text_over_the_limit_is_rejected() -> None:
    reasons = check("Built services in Python. " + "and more " * 50)

    assert TOO_LONG in reasons


def test_an_honest_portuguese_rewording_passes() -> None:
    resume = "Desenvolvi APIs REST em Python\nReduzi o tempo de consulta em 60%"

    assert (
        check("Desenvolvi APIs REST em Python, reduzindo o tempo de consulta em 60%", resume=resume)
        == []
    )


def test_mixed_inventions_report_each_reason_once() -> None:
    assert check("Led 12 engineers using Kafka") == [UNSUPPORTED_TECHNOLOGY, UNSUPPORTED_NUMBER]


def test_mentions_use_aliases() -> None:
    vocabulary = build_vocabulary(
        job_keywords=[], ats_keywords=[], resume_names=[], profile=profile()
    )

    assert technology_mentions("Ran everything on K8s", vocabulary) == {"kubernetes"}
    assert technology_mentions("Ran things on javascript", vocabulary) == {"javascript"}
    assert technology_mentions("Wrote Java, not javascript", vocabulary) == {"java", "javascript"}


def test_short_names_are_never_looked_for() -> None:
    vocabulary = build_vocabulary(
        job_keywords=["go", "c", "r"], ats_keywords=["js"], resume_names=[], profile=profile()
    )

    assert not {"go", "c", "r", "js"} & vocabulary


def test_shape_names_finds_the_expected_tokens() -> None:
    names = shape_names("Built tools with Zorbify.js and C++ for the HQLX team, e.g. cron")

    assert names == {"Zorbify.js", "C++", "HQLX"}


HONEST = [
    "Built REST APIs in Python and FastAPI, cutting query time by 60%",
    "Deployed services on Kubernetes",
    "Containerized Python services with Docker",
    "Used Terraform to provision infrastructure",
    "Won a hackathon in 2022 with a Python prototype",
    "Delivered 3 years of Python backend work",
    "Cut query time by 60% on PostgreSQL by tuning indexes",
    "Maintained FastAPI services and PostgreSQL schemas",
    "Reduced deploy time by migrating services to Docker",
    "Wrote Python scripts that automated release tasks",
    "Worked with Docker for two years",
    "Shipped REST endpoints with FastAPI for the billing team",
    "Improved query performance on PostgreSQL",
    "Automated infrastructure with Terraform for one environment",
    "Built an API gateway prototype in Python",
]
INVENTED = [
    "Deployed services on Kafka clusters",
    "Cut query time by 80% on PostgreSQL",
    "Built pipelines in Airflow",
    "Led 8 engineers building FastAPI services",
    "Seven years of Python and FastAPI",
    "Migrated workloads to AWS Lambda",
    "Used Ansible to configure servers for 3 teams of 12",
    "Built dashboards with Grafana",
    "Reduced costs by 35% using Redis",
    "Wrote services in Rust",
    "Scaled the API to 10 million requests with Zorbify.js",
    "10 years of Python experience",
    "Managed a budget of 4M with Terraform",
    "Implemented GraphQL endpoints",
    "Trained 15 interns on Docker and Jenkins",
]


@pytest.mark.parametrize("text", HONEST)
def test_honest_rewordings_pass(text: str) -> None:
    assert check(text) == [], text


@pytest.mark.parametrize("text", INVENTED)
def test_inventions_are_rejected(text: str) -> None:
    assert check(text) != [], text
