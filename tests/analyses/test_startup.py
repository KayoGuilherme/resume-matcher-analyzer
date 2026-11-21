import logging

import pytest

from app.analyses.startup import run_analyses_startup, run_analysis_startup_checks
from app.core.config import Settings
from app.core.processing import PROCESSING_MESSAGES
from tests.analyses.env import make_env

DB = "postgresql+asyncpg://u:p@localhost:5432/x"


async def test_an_analysis_that_was_processing_becomes_failed_with_the_interrupted_code() -> None:
    env = await make_env()
    running, _ = await env.service.request(env.resume_id, env.job_id, _llm())

    await run_analysis_startup_checks(env.analyses)  # type: ignore[arg-type]

    recovered = await env.service.get(running.id)
    assert recovered.status == "failed" and recovered.error is not None
    assert recovered.error.code == "processing_interrupted"
    assert recovered.error.message == PROCESSING_MESSAGES["processing_interrupted"]


async def test_finished_analyses_are_left_alone() -> None:
    env = await make_env()
    llm = _llm()
    analysis, _ = await env.service.request(env.resume_id, env.job_id, llm)
    await env.service.run(analysis.id, llm)

    await run_analysis_startup_checks(env.analyses)  # type: ignore[arg-type]

    assert (await env.service.get(analysis.id)).status == "ready"


async def test_an_unreachable_database_only_skips_the_check_with_a_warning(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(_settings: Settings) -> object:
        raise ConnectionRefusedError("postgres://u:secret@host/db")

    monkeypatch.setattr("app.analyses.startup.get_sessionmaker", unreachable)

    with caplog.at_level(logging.WARNING):
        await run_analyses_startup(Settings(database_url=DB))  # type: ignore[call-arg]

    assert "skipped" in caplog.text and "secret" not in caplog.text


async def test_a_database_without_the_table_only_skips_the_check(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import ProgrammingError

    class Broken:
        async def mark_interrupted(self, message: str) -> int:
            raise ProgrammingError("SELECT 1", {}, Exception("relation analysis does not exist"))

    class Session:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr("app.analyses.startup.get_sessionmaker", lambda _s: lambda: Session())
    monkeypatch.setattr("app.analyses.startup.AnalysisRepository", lambda _session: Broken())

    with caplog.at_level(logging.WARNING):
        await run_analyses_startup(Settings(database_url=DB))  # type: ignore[call-arg]

    assert "skipped" in caplog.text


def _llm():  # type: ignore[no-untyped-def]
    from tests.analyses.fakes import AnswerAllLLM

    return AnswerAllLLM()
