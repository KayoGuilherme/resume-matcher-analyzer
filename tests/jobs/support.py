"""Helpers for the job tests: stored jobs and the fixture postings as job texts."""

import uuid
from datetime import UTC, datetime

from app.jobs.schemas import JobDetail
from tests.fixtures.job_postings import Posting


def stored_job(
    text: str = "Backend role. Python is required.", status: str = "uploaded"
) -> JobDetail:
    return JobDetail(
        id=uuid.uuid4(),
        title="Backend Engineer",
        company="ACME",
        description=text,
        requirements_text=None,
        created_at=datetime(2026, 11, 21, tzinfo=UTC),
        status=status,  # type: ignore[arg-type]
    )


def job_from(posting: Posting, status: str = "uploaded") -> JobDetail:
    return stored_job(posting.text, status)
