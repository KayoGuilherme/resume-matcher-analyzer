import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.main import create_app
from tests.fixtures import documents

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[httpx.AsyncClient]:
    """Real app, real database and a temporary storage directory; `resume` emptied around tests."""
    # Fail loudly: a misconfigured integration job must not pass by skipping.
    if not os.environ.get("DATABASE_URL"):
        pytest.fail("DATABASE_URL must be set for integration tests")
    monkeypatch.setenv("RESUME_STORAGE_DIR", str(tmp_path / "files"))
    get_settings.cache_clear()
    engine = get_engine(get_settings())

    async def clear() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM resume"))

    await clear()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    await clear()
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


def _file(data: bytes, name: str = "resume.pdf") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, data, "application/octet-stream")}


def _stored(tmp_path: Path) -> list[str]:
    directory = tmp_path / "files"
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


async def test_upload_duplicate_list_get_delete(client: httpx.AsyncClient, tmp_path: Path) -> None:
    data = documents.clean_pdf()

    created = await client.post("/resumes", files=_file(data, "a.pdf"))
    duplicate = await client.post("/resumes", files=_file(data, "b.pdf"))

    assert (created.status_code, duplicate.status_code) == (201, 200)
    resume = created.json()
    assert duplicate.json() == resume
    assert _stored(tmp_path) == [f"{resume['sha256']}.pdf"]
    assert (tmp_path / "files" / f"{resume['sha256']}.pdf").read_bytes() == data

    listing = (await client.get("/resumes")).json()
    assert [item["id"] for item in listing] == [resume["id"]]
    assert "text" not in listing[0]
    assert (await client.get(f"/resumes/{resume['id']}")).json() == resume

    assert (await client.delete(f"/resumes/{resume['id']}")).status_code == 204
    assert (await client.get(f"/resumes/{resume['id']}")).status_code == 404
    assert _stored(tmp_path) == []

    again = await client.post("/resumes", files=_file(data))
    assert again.status_code == 201
    assert again.json()["id"] != resume["id"]


async def test_docx_with_an_unknown_page_count_round_trips_as_null(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        "/resumes", files=_file(documents.docx_without_page_count(), "cv.docx")
    )

    fetched = await client.get(f"/resumes/{created.json()['id']}")

    assert created.status_code == 201
    assert fetched.json()["page_count"] is None
    assert fetched.json() == created.json()


async def test_issues_and_metadata_survive_the_database(client: httpx.AsyncClient) -> None:
    created = (await client.post("/resumes", files=_file(documents.two_column_pdf()))).json()

    fetched = (await client.get(f"/resumes/{created['id']}")).json()

    assert fetched == created
    assert "multi_column" in [issue["code"] for issue in fetched["issues"]]
    assert fetched["metadata"]["word_count"] > 0


async def test_two_concurrent_identical_uploads_leave_one_resume(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    data = documents.clean_pdf()

    first, second = await asyncio.gather(
        client.post("/resumes", files=_file(data, "a.pdf")),
        client.post("/resumes", files=_file(data, "b.pdf")),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 201]
    assert first.json()["id"] == second.json()["id"]
    assert len((await client.get("/resumes")).json()) == 1
    assert _stored(tmp_path) == [f"{first.json()['sha256']}.pdf"]


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (documents.fake_pdf(), 415),
        (documents.scanned_pdf(), 422),
        (b"", 422),
        (documents.clean_pdf()[:200], 422),
    ],
)
async def test_a_rejected_upload_leaves_no_row_and_no_file(
    client: httpx.AsyncClient, tmp_path: Path, data: bytes, status: int
) -> None:
    response = await client.post("/resumes", files=_file(data))

    assert response.status_code == status
    assert (await client.get("/resumes")).json() == []
    assert _stored(tmp_path) == []
