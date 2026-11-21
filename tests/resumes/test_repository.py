import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects import postgresql

from app.ai.parsing.models import ParsingIssue
from app.resumes.models import Resume
from app.resumes.repository import ResumeRepository
from app.resumes.schemas import ResumeDetail, ResumeMetadata


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._rows


class FakeSession:
    def __init__(self, rows: list[Any] | None = None, stored: Resume | None = None) -> None:
        self.rows = rows or []
        self.stored = stored
        self.statements: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.rows)

    async def get(self, model: Any, key: Any) -> Resume | None:
        assert model is Resume
        return self.stored if self.stored is not None and self.stored.id == key else None

    async def commit(self) -> None:
        self.commits += 1


def _sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _detail(page_count: int | None = 2) -> ResumeDetail:
    return ResumeDetail(
        id=uuid.uuid4(),
        original_filename="resume.pdf",
        file_type="pdf",
        size_bytes=1234,
        sha256="a" * 64,
        page_count=page_count,
        metadata=ResumeMetadata(
            parser="pdfplumber", character_count=11, word_count=2, table_count=0, image_count=0
        ),
        issues=[ParsingIssue(code="tables", severity="warning", message="Tables found.")],
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
        text="hello world",
    )


def _row(detail: ResumeDetail) -> Resume:
    return Resume(
        id=detail.id,
        sha256=detail.sha256,
        original_filename=detail.original_filename,
        file_type=detail.file_type,
        size_bytes=detail.size_bytes,
        page_count=detail.page_count,
        text=detail.text,
        parsing_metadata=detail.metadata.model_dump(),
        issues=[issue.model_dump() for issue in detail.issues],
        created_at=detail.created_at,
        status="uploaded",
    )


def _repo(session: FakeSession) -> ResumeRepository:
    return ResumeRepository(session)  # type: ignore[arg-type]


async def test_add_inserts_with_on_conflict_do_nothing_and_commits() -> None:
    detail = _detail()
    session = FakeSession(rows=[detail.id])

    inserted = await _repo(session).add(detail)

    assert inserted is True
    sql = _sql(session.statements[0])
    assert "INSERT INTO resume" in sql
    assert "ON CONFLICT (sha256) DO NOTHING" in sql
    assert "RETURNING resume.id" in sql
    params = session.statements[0].compile(dialect=postgresql.dialect()).params
    assert params["sha256"] == detail.sha256
    assert params["parsing_metadata"]["parser"] == "pdfplumber"
    assert params["issues"] == [
        {"code": "tables", "severity": "warning", "message": "Tables found."}
    ]
    assert session.commits == 1


async def test_add_reports_a_conflict_when_no_row_is_returned() -> None:
    session = FakeSession(rows=[])

    assert await _repo(session).add(_detail()) is False
    assert session.commits == 1


async def test_get_by_sha_maps_the_row_to_a_detail() -> None:
    detail = _detail(page_count=None)
    session = FakeSession(rows=[_row(detail)])

    assert await _repo(session).get_by_sha(detail.sha256) == detail
    assert "WHERE resume.sha256 =" in _sql(session.statements[0])


async def test_get_by_sha_returns_none_when_missing() -> None:
    assert await _repo(FakeSession()).get_by_sha("0" * 64) is None


async def test_get_maps_a_stored_row_including_null_page_count() -> None:
    detail = _detail(page_count=None)

    assert await _repo(FakeSession(stored=_row(detail))).get(detail.id) == detail


async def test_get_returns_none_for_an_unknown_id() -> None:
    assert await _repo(FakeSession()).get(uuid.uuid4()) is None


async def test_list_all_is_newest_first_and_does_not_select_the_text() -> None:
    newer, older = _detail(), _detail()
    session = FakeSession(rows=[_row(newer), _row(older)])

    summaries = await _repo(session).list_all()

    assert [s.id for s in summaries] == [newer.id, older.id]
    assert not hasattr(summaries[0], "text")
    sql = _sql(session.statements[0])
    assert "ORDER BY resume.created_at DESC" in sql
    assert "resume.text" not in sql.split("FROM")[0]


async def test_list_all_of_nothing_is_empty() -> None:
    assert await _repo(FakeSession()).list_all() == []


async def test_delete_returns_the_key_parts_and_commits() -> None:
    class Row:
        sha256 = "b" * 64
        file_type = "docx"

    session = FakeSession(rows=[Row()])

    result = await _repo(session).delete(uuid.uuid4())

    assert result == ("b" * 64, "docx")
    sql = _sql(session.statements[0])
    assert "DELETE FROM resume" in sql
    assert "RETURNING resume.sha256, resume.file_type" in sql
    assert session.commits == 1


async def test_delete_of_an_unknown_id_returns_none() -> None:
    session = FakeSession(rows=[])

    assert await _repo(session).delete(uuid.uuid4()) is None
    assert session.commits == 1
