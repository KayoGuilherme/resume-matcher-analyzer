"""In-memory stand-ins for the repository and storage (no database, no disk)."""

import uuid

from app.resumes.schemas import ResumeDetail, ResumeSummary


class FakeRepository:
    def __init__(self) -> None:
        self.by_id: dict[uuid.UUID, ResumeDetail] = {}
        self.add_calls = 0
        self.lookups = 0
        self.fail_on_add: Exception | None = None
        self.lose_race_to: ResumeDetail | None = None

    async def add(self, resume: ResumeDetail) -> bool:
        self.add_calls += 1
        if self.fail_on_add is not None:
            raise self.fail_on_add
        if self.lose_race_to is not None:
            self.by_id[self.lose_race_to.id] = self.lose_race_to
            return False
        if any(existing.sha256 == resume.sha256 for existing in self.by_id.values()):
            return False
        self.by_id[resume.id] = resume
        return True

    async def get_by_sha(self, sha256: str) -> ResumeDetail | None:
        self.lookups += 1
        return next((r for r in self.by_id.values() if r.sha256 == sha256), None)

    async def get(self, resume_id: uuid.UUID) -> ResumeDetail | None:
        return self.by_id.get(resume_id)

    async def list_all(self) -> list[ResumeSummary]:
        newest_first = sorted(self.by_id.values(), key=lambda r: r.created_at, reverse=True)
        return [ResumeSummary(**r.model_dump(exclude={"text"})) for r in newest_first]

    async def delete(self, resume_id: uuid.UUID) -> tuple[str, str] | None:
        resume = self.by_id.pop(resume_id, None)
        return None if resume is None else (resume.sha256, resume.file_type)


class FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.fail_on_save: Exception | None = None
        self.fail_on_delete: Exception | None = None

    async def save(self, key: str, data: bytes) -> None:
        if self.fail_on_save is not None:
            raise self.fail_on_save
        self.files[key] = data

    async def read(self, key: str) -> bytes:
        return self.files[key]

    async def delete(self, key: str) -> None:
        if self.fail_on_delete is not None:
            raise self.fail_on_delete
        self.files.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.files
