"""Data passed between the parsing steps. No resume content ever goes into an error message."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

FileType = Literal["pdf", "docx"]
Severity = Literal["critical", "warning", "info"]


class ParsingIssue(BaseModel):
    """One readability problem for an ATS."""

    model_config = ConfigDict(frozen=True)

    code: str
    severity: Severity
    message: str


class ParsedDocument(BaseModel):
    """Text plus the facts about the document that the quality checks need."""

    model_config = ConfigDict(frozen=True)

    file_type: FileType
    text: str
    page_count: int | None  # None when the format does not tell (DOCX without properties)
    parser: str
    image_count: int = 0
    table_count: int = 0
    multi_column: bool = False
    header_footer_text: bool = False


class UnreadableDocumentError(Exception):
    """The file has a valid signature but cannot be opened (corrupt, truncated, encrypted)."""

    def __init__(self) -> None:
        super().__init__("The document could not be read")
