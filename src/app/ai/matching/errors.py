"""Typed failures of the gap analysis. Messages carry no resume, job or profile content."""


class MatchingError(Exception):
    """Base class for every failure raised by the matching code."""


class AnalysisLimitError(MatchingError):
    """The requirements that must be judged need more LLM calls than the configured maximum."""


class EmbeddingModelMismatchError(MatchingError):
    """The resume chunks and the job requirements do not share an embedding model or size."""


class JudgeIncompleteError(MatchingError):
    """Some requirements were still unanswered after the judge was asked again."""


class AnalysisInvariantError(MatchingError):
    """A finding broke the evidence rule: a bug in a step, never stored."""
