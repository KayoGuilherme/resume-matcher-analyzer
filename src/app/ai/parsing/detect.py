"""Decide the real file type from the bytes. The file name and content type are never used."""

import io
import zipfile

from app.ai.parsing.models import FileType

PDF_SIGNATURE = b"%PDF-"
ZIP_SIGNATURE = b"PK\x03\x04"
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


def _open_zip(data: bytes) -> zipfile.ZipFile | None:
    if not data.startswith(ZIP_SIGNATURE):
        return None
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None


def detect_file_type(data: bytes) -> FileType | None:
    """Return `pdf` or `docx` when the content really is one, otherwise None."""
    if data.startswith(PDF_SIGNATURE):
        return "pdf"
    archive = _open_zip(data)
    if archive is None:
        return None
    names = set(archive.namelist())
    if {"[Content_Types].xml", "word/document.xml"} <= names:
        return "docx"
    return None


def exceeds_uncompressed_limit(data: bytes) -> bool:
    """True when a ZIP would expand past the cap (zip-bomb guard; 5 MB uploads can expand a lot)."""
    archive = _open_zip(data)
    if archive is None:
        return False
    return sum(info.file_size for info in archive.infolist()) > MAX_DOCX_UNCOMPRESSED_BYTES
