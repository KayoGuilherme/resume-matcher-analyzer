"""File storage behind an interface. Nothing touches the disk at import time."""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import Depends

from app.core.config import Settings, get_settings


class FileStorage(Protocol):
    """Where original uploaded files live. Keys are plain names, never paths."""

    async def save(self, key: str, data: bytes) -> None: ...

    async def read(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...


class LocalFileStorage:
    """Store files in one directory on the local disk."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        if not key or key in {".", ".."} or "/" in key or "\\" in key or "\x00" in key:
            raise ValueError("Invalid storage key")
        return self._root / key

    async def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        await asyncio.to_thread(self._write, path, data)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write next to the target and move into place: readers never see a partial file.
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    async def read(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)


def get_file_storage(settings: Annotated[Settings, Depends(get_settings)]) -> FileStorage:
    """FastAPI dependency: the configured storage (created per request, cheap)."""
    return LocalFileStorage(settings.resume_storage_dir)
