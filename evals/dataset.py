"""The eval dataset: synthetic resume / job / profile cases with the results a careful human
reviewer expects.

A case is a folder `cases/<id>/` with `resume.txt`, `job.txt`, `profile.json` (the profile API's
request body) and `case.json` (language, expected outcome, optional document facts and the
expected requirements). Loading validates everything and names the case in every error.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.matching.models import ProfileFacts, ProfileLanguage, ProfileStack
from app.ai.matching.report_models import Outcome
from app.ai.parsing.models import ParsedDocument
from app.core.normalization import normalize_language_name, normalize_stack_name
from app.profile.schemas import ProfileIn

CASES_DIR = Path(__file__).resolve().parent / "cases"
FILES = ("resume.txt", "job.txt", "profile.json", "case.json")

ExpectedVerdict = Literal["met", "partial", "missing", "in_profile_not_in_resume"]


class DatasetError(Exception):
    """A case cannot be loaded. The message names the case and the problem, never its content."""

    def __init__(self, case_id: str, problem: str) -> None:
        super().__init__(f"case {case_id}: {problem}")
        self.case_id = case_id
        self.problem = problem


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentFacts(_Strict):
    """What the parser would have seen of the file, so the production quality checks produce
    the resume's parsing issues."""

    page_count: int | None = Field(default=None, ge=1)
    multi_column: bool = False
    table_count: int = Field(default=0, ge=0)
    image_count: int = Field(default=0, ge=0)
    header_footer_text: bool = False


class ExpectedRequirement(_Strict):
    match: str = Field(min_length=1)  # compared folded with the requirement's text and keywords
    verdict: ExpectedVerdict


class CaseSpec(_Strict):
    """The content of `case.json`."""

    language: Literal["en", "pt"]
    expected_outcome: Outcome
    document: DocumentFacts = DocumentFacts()
    requirements: list[ExpectedRequirement] = Field(min_length=1)


class Case(BaseModel):
    id: str
    language: Literal["en", "pt"]
    resume_text: str
    job_text: str
    profile: ProfileIn
    document: DocumentFacts
    expected_outcome: Outcome
    expected: list[ExpectedRequirement]

    def parsed_document(self) -> ParsedDocument:
        """The document the parser would have produced, for `check_quality`."""
        return ParsedDocument(
            file_type="pdf",
            text=self.resume_text,
            page_count=self.document.page_count,
            parser="evals",
            image_count=self.document.image_count,
            table_count=self.document.table_count,
            multi_column=self.document.multi_column,
            header_footer_text=self.document.header_footer_text,
        )

    def profile_facts(self) -> ProfileFacts:
        """The profile as the analysis reads it: names in their canonical form."""
        return ProfileFacts(
            total_years_coding=self.profile.total_years_coding,
            stacks=[
                ProfileStack(
                    name=normalize_stack_name(stack.name), years=stack.years, level=stack.level
                )
                for stack in self.profile.stacks
            ],
            languages=[
                ProfileLanguage(name=normalize_language_name(item.name), level=item.level)
                for item in self.profile.languages
            ],
            notable_facts=list(self.profile.notable_facts),
        )


def _read(folder: Path, name: str, case_id: str) -> str:
    path = folder / name
    if not path.is_file():
        raise DatasetError(case_id, f"missing file {name}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise DatasetError(case_id, f"{name} is empty")
    return text


def _problem(error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first["loc"]) or "value"
    return f"{location}: {first['msg']}"


def load_case(folder: Path) -> Case:
    case_id = folder.name
    resume_text = _read(folder, "resume.txt", case_id)
    job_text = _read(folder, "job.txt", case_id)
    try:
        profile = ProfileIn.model_validate(json.loads(_read(folder, "profile.json", case_id)))
    except json.JSONDecodeError:
        raise DatasetError(case_id, "profile.json is not valid JSON") from None
    except ValidationError as error:
        raise DatasetError(case_id, f"profile.json {_problem(error)}") from None
    try:
        spec = CaseSpec.model_validate(json.loads(_read(folder, "case.json", case_id)))
    except json.JSONDecodeError:
        raise DatasetError(case_id, "case.json is not valid JSON") from None
    except ValidationError as error:
        raise DatasetError(case_id, f"case.json {_problem(error)}") from None
    return Case(
        id=case_id,
        language=spec.language,
        resume_text=resume_text,
        job_text=job_text,
        profile=profile,
        document=spec.document,
        expected_outcome=spec.expected_outcome,
        expected=spec.requirements,
    )


def load_cases(root: Path = CASES_DIR) -> list[Case]:
    """Every case under `root`, in id order. Raises `DatasetError` on the first invalid one."""
    folders = sorted(path for path in root.iterdir() if path.is_dir())
    return [load_case(folder) for folder in folders]
