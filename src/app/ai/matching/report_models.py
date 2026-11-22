"""Models of the screening report: the score, the simulated screener, the rewrite suggestions,
the prioritized actions, what is stored with an analysis and what the report endpoint returns.

`StoredReport` is what costs tokens or reads the profile and the resume, so it is frozen with the
analysis. The score, the actions and the Markdown are computed from it when the report is read.
The LLM schemas at the end have every field required (strict structured-output modes) and no id,
score or outcome field.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.ai.extraction.job_models import PostingLanguage, Priority
from app.ai.extraction.models import ExtractionWarning
from app.ai.matching.models import AtsCoverage
from app.ai.parsing.models import ParsingIssue, Severity

Outcome = Literal["likely_pass", "borderline", "likely_reject"]
ScreenerDecision = Literal["pass", "borderline", "reject"]
CoverageName = Literal["must_have", "nice_to_have", "keywords"]
ActionKind = Literal["fix_format", "add_from_profile", "real_gap"]
SuggestionSource = Literal["resume", "profile"]
TargetKind = Literal["requirement", "keyword"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# --- score ----------------------------------------------------------------------------------


class ScoreSettings(_Frozen):
    """A snapshot of the `SCORE_*` configuration (`ai/matching` does not import the app config)."""

    weight_must_have: float
    weight_nice_to_have: float
    weight_keywords: float
    partial_credit: float
    penalty_critical: float
    penalty_warning: float
    penalty_info: float
    pass_threshold: float
    borderline_threshold: float

    def penalty(self, severity: Severity) -> float:
        return {
            "critical": self.penalty_critical,
            "warning": self.penalty_warning,
            "info": self.penalty_info,
        }[severity]


class ReportSettings(_Frozen):
    """A snapshot of the settings that shape the LLM part of a report."""

    screener_runs: int
    max_suggestions: int


class ScoreCoverage(BaseModel):
    name: CoverageName
    value: float | None  # 0-1; None when there was nothing to measure (left out)
    weight: float  # as configured
    included: bool


class ScorePenalty(BaseModel):
    code: str
    severity: Severity
    points: float


class Score(BaseModel):
    """The number, the outcome and everything needed to recompute them."""

    value: float | None  # None only when nothing could be measured
    outcome: Outcome | None
    measured: bool
    weighted_coverage: float | None  # 0-100 before the penalties
    coverages: list[ScoreCoverage]
    penalties: list[ScorePenalty]
    total_penalty: float
    pass_threshold: float
    borderline_threshold: float


# --- screener -------------------------------------------------------------------------------


class ScreenerRun(BaseModel):
    decision: ScreenerDecision
    reasons: list[str]


class ScreenerResult(BaseModel):
    """What is stored: the majority decision, how much the runs agree and every run."""

    decision: ScreenerDecision
    consistency: float
    runs: list[ScreenerRun]


class ScreenerReport(ScreenerResult):
    """What is returned: also whether the decision matches the score's outcome (None when there
    is no score to compare with)."""

    agrees_with_score: bool | None


# --- suggestions ----------------------------------------------------------------------------


class SuggestionTarget(BaseModel):
    kind: TargetKind
    requirement_id: uuid.UUID | None
    text: str  # the requirement's text or the keyword


class SuggestionBasis(BaseModel):
    """The resume bullet (verbatim) or the profile fact the suggestion is based on."""

    source: SuggestionSource
    text: str


class Suggestion(BaseModel):
    id: str
    target: SuggestionTarget
    original: str | None  # the bullet being reworded; None for a new bullet
    text: str
    based_on: SuggestionBasis


class SuggestionSet(BaseModel):
    accepted: list[Suggestion]
    rejected: list[ExtractionWarning]  # counts by reason code; rejected text is never kept


# --- stored report and response -------------------------------------------------------------


class ReportProvenance(BaseModel):
    screener_prompt_name: str
    screener_prompt_version: int
    suggestions_prompt_name: str
    suggestions_prompt_version: int
    llm_provider: str
    llm_model: str
    llm_calls: int  # the report's own calls (screener runs + the suggestion call)
    screener_runs: int
    max_suggestions: int
    generated_at: datetime


class MissingKeyword(BaseModel):
    """An ATS keyword that is not in the resume, with what the actions need to place it: whether
    the profile has it as a stack and which requirements of the job it belongs to."""

    keyword: str
    in_profile: bool
    requirement_ids: list[uuid.UUID]


class StoredReport(BaseModel):
    language: PostingLanguage
    screener: ScreenerResult
    suggestions: SuggestionSet
    missing_keywords: list[MissingKeyword]  # in the job's order
    issues: list[ParsingIssue]  # the resume's parsing issues when the analysis ran
    provenance: ReportProvenance


class Action(BaseModel):
    priority: int  # 1.. following the list order
    kind: ActionKind
    importance: Priority | None = None
    requirement_id: uuid.UUID | None = None
    requirement_text: str | None = None
    keyword: str | None = None
    issue_code: str | None = None
    issue_severity: Severity | None = None
    text: str
    suggestion_ids: list[str] = []


class Report(BaseModel):
    analysis_id: uuid.UUID
    resume_id: uuid.UUID
    job_id: uuid.UUID
    language: PostingLanguage
    disclaimer: str
    score: Score
    score_settings: ScoreSettings
    screener: ScreenerReport
    ats_coverage: AtsCoverage
    actions: list[Action]
    suggestions: list[Suggestion]
    warnings: list[ExtractionWarning]
    provenance: ReportProvenance


# --- the schemas the LLM answers with (every field required) --------------------------------


class ScreenerAnswer(BaseModel):
    decision: ScreenerDecision
    reasons: list[str]


class SuggestionAnswer(BaseModel):
    target: int  # the number of the target in the prompt, starting at 1
    source: SuggestionSource
    number: int  # the number of the bullet (resume) or profile item (profile), starting at 1
    text: str


class SuggestionBatch(BaseModel):
    suggestions: list[SuggestionAnswer]
