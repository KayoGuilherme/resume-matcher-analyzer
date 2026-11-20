import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.main import create_app
from app.resumes.router import get_resume_service
from app.resumes.service import ResumeService
from tests.fixtures import documents
from tests.resumes.fakes import FakeRepository, FakeStorage

MB = 1024 * 1024

Env = tuple[httpx.AsyncClient, FakeRepository, FakeStorage]


@pytest.fixture
def make_client() -> Callable[[int], Env]:
    def make(max_bytes: int = 5 * MB) -> Env:
        settings = Settings(
            database_url="postgresql+asyncpg://u:p@localhost:5432/x",
            resume_max_upload_bytes=max_bytes,
        )
        app: FastAPI = create_app()
        repository, storage = FakeRepository(), FakeStorage()
        service = ResumeService(repository, storage, max_bytes)  # type: ignore[arg-type]
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_resume_service] = lambda: service
        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(transport=transport, base_url="http://test")
        return client, repository, storage

    return make


def _file(data: bytes, name: str = "resume.pdf") -> dict[str, Any]:
    return {"file": (name, data, "application/octet-stream")}


async def test_clean_pdf_is_created_with_the_full_resume(make_client: Callable[[int], Env]) -> None:
    client, _, storage = make_client(5 * MB)
    data = documents.clean_pdf()

    async with client:
        response = await client.post("/resumes", files=_file(data))

    assert response.status_code == 201
    body = response.json()
    assert body["file_type"] == "pdf"
    assert body["issues"] == []
    assert body["page_count"] == 2
    assert body["original_filename"] == "resume.pdf"
    assert "Experience" in body["text"]
    assert len(body["sha256"]) == 64
    assert body["metadata"]["parser"].startswith("pdfplumber")
    assert set(body) == {
        "id",
        "original_filename",
        "file_type",
        "size_bytes",
        "sha256",
        "page_count",
        "metadata",
        "issues",
        "created_at",
        "text",
    }
    assert list(storage.files.values()) == [data]


async def test_two_column_pdf_is_created_with_a_multi_column_issue(
    make_client: Callable[[int], Env],
) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        response = await client.post("/resumes", files=_file(documents.two_column_pdf()))

    assert response.status_code == 201
    assert "multi_column" in [issue["code"] for issue in response.json()["issues"]]


async def test_docx_is_created(make_client: Callable[[int], Env]) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        response = await client.post("/resumes", files=_file(documents.clean_docx(), "cv.docx"))

    assert response.status_code == 201
    assert response.json()["file_type"] == "docx"


async def test_scanned_pdf_is_422_with_the_ats_explanation(
    make_client: Callable[[int], Env],
) -> None:
    client, repository, storage = make_client(5 * MB)

    async with client:
        response = await client.post("/resumes", files=_file(documents.scanned_pdf()))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "no_extractable_text"
    assert "looks scanned or image-only" in error["message"]
    assert repository.by_id == {} and storage.files == {}


async def test_fake_pdf_is_415(make_client: Callable[[int], Env]) -> None:
    client, repository, storage = make_client(5 * MB)

    async with client:
        response = await client.post("/resumes", files=_file(documents.fake_pdf()))

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert repository.by_id == {} and storage.files == {}


async def test_empty_file_is_422(make_client: Callable[[int], Env]) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        response = await client.post("/resumes", files=_file(b""))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_file"


async def test_corrupted_pdf_is_422_unreadable(make_client: Callable[[int], Env]) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        response = await client.post("/resumes", files=_file(documents.clean_pdf()[:200]))

    assert response.json()["error"]["code"] == "unreadable_file"


async def test_a_file_over_the_limit_is_413_and_names_the_limit(
    make_client: Callable[[int], Env],
) -> None:
    client, repository, _ = make_client(MB)
    data = b"%PDF-" + b"0" * (MB)  # one byte over the 1 MB limit

    async with client:
        response = await client.post("/resumes", files=_file(data))

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "file_too_large"
    assert "1 MB" in error["message"]
    assert repository.by_id == {}


async def test_a_declared_content_length_far_over_the_limit_is_rejected_before_the_body(
    make_client: Callable[[int], Env],
) -> None:
    client, repository, _ = make_client(MB)

    async with client:
        response = await client.post(
            "/resumes",
            content=b"not even multipart",
            headers={
                "content-type": "multipart/form-data; boundary=x",
                "content-length": str(10 * MB),
            },
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert repository.lookups == 0


async def test_the_same_file_twice_is_201_then_200_with_one_resume(
    make_client: Callable[[int], Env],
) -> None:
    client, _, storage = make_client(5 * MB)
    data = documents.clean_pdf()

    async with client:
        first = await client.post("/resumes", files=_file(data, "a.pdf"))
        second = await client.post("/resumes", files=_file(data, "b.pdf"))
        listing = await client.get("/resumes")

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json() == first.json()
    assert len(listing.json()) == 1
    assert len(storage.files) == 1


async def test_a_missing_file_field_is_a_validation_error_naming_file(
    make_client: Callable[[int], Env],
) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        response = await client.post("/resumes", data={"other": "x"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"].startswith("file: ")


async def test_list_is_newest_first_without_text(make_client: Callable[[int], Env]) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        older = (await client.post("/resumes", files=_file(documents.clean_pdf()))).json()
        newer = (
            await client.post("/resumes", files=_file(documents.clean_docx(), "b.docx"))
        ).json()
        listing = await client.get("/resumes")

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [newer["id"], older["id"]]
    assert all("text" not in item for item in listing.json())
    assert all({"issues", "metadata", "sha256"} <= set(item) for item in listing.json())


async def test_list_with_nothing_stored_is_empty(make_client: Callable[[int], Env]) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        response = await client.get("/resumes")

    assert (response.status_code, response.json()) == (200, [])


async def test_get_returns_the_upload_body(make_client: Callable[[int], Env]) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        uploaded = (await client.post("/resumes", files=_file(documents.clean_pdf()))).json()
        fetched = await client.get(f"/resumes/{uploaded['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == uploaded


async def test_get_of_an_unknown_id_is_404(make_client: Callable[[int], Env]) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        response = await client.get(f"/resumes/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resume_not_found"


async def test_a_malformed_id_is_a_validation_error(make_client: Callable[[int], Env]) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        get = await client.get("/resumes/not-a-uuid")
        delete = await client.delete("/resumes/not-a-uuid")

    assert get.status_code == delete.status_code == 422
    assert get.json()["error"]["code"] == "validation_error"


async def test_delete_removes_the_resume_and_the_stored_file(
    make_client: Callable[[int], Env],
) -> None:
    client, _, storage = make_client(5 * MB)

    async with client:
        uploaded = (await client.post("/resumes", files=_file(documents.clean_pdf()))).json()
        deleted = await client.delete(f"/resumes/{uploaded['id']}")
        after = await client.get(f"/resumes/{uploaded['id']}")
        again = await client.delete(f"/resumes/{uploaded['id']}")

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert after.status_code == 404
    assert again.status_code == 404
    assert storage.files == {}


async def test_a_deleted_file_can_be_uploaded_again_as_a_new_resume(
    make_client: Callable[[int], Env],
) -> None:
    client, _, _ = make_client(5 * MB)
    data = documents.clean_pdf()

    async with client:
        first = (await client.post("/resumes", files=_file(data))).json()
        await client.delete(f"/resumes/{first['id']}")
        again = await client.post("/resumes", files=_file(data))

    assert again.status_code == 201
    assert again.json()["id"] != first["id"]


async def test_error_responses_never_contain_the_file_name(
    make_client: Callable[[int], Env],
) -> None:
    client, _, _ = make_client(5 * MB)

    async with client:
        response = await client.post(
            "/resumes", files=_file(documents.fake_pdf(), "Alex_Example_PRIVATE_CV.pdf")
        )

    assert "PRIVATE" not in response.text
    assert "Alex" not in response.text


def test_the_routes_are_registered() -> None:
    paths = create_app().openapi()["paths"]

    assert set(paths["/resumes"]) == {"post", "get"}
    assert set(paths["/resumes/{resume_id}"]) == {"get", "delete"}
