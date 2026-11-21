import warnings
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from app.ai.extraction.verify import is_verbatim, normalize
from app.ai.llm import LLMClient, LLMTransientError
from app.ai.matching.engine import analyze
from app.ai.matching.models import AnalysisSettings
from tests.fixtures.analysis_cases import Case, english, portuguese

pytestmark = pytest.mark.real_provider

SETTINGS = AnalysisSettings(
    top_k=5, min_similarity=0.4, max_requirements_per_call=8, max_llm_calls=10
)


@pytest.mark.parametrize("build", [english, portuguese], ids=["english", "portuguese"])
async def test_the_configured_model_judges_within_the_evidence_rules(
    real_llm: LLMClient, build: Callable[[], Case]
) -> None:
    case = build()
    try:
        result = await analyze(case.inputs, real_llm, SETTINGS, datetime.now(UTC))
    except LLMTransientError as error:
        pytest.skip(f"the configured provider is not reachable or is rate limiting: {error}")

    # The structural rules: they hold whatever the model answered.
    normalized = normalize(case.inputs.resume.text)
    assert len(result.findings) == len(case.expected)
    for finding in result.findings:
        assert finding.explanation.strip()
        if finding.verdict in ("met", "partial"):
            assert 1 <= len(finding.evidence) <= 3
        for evidence in finding.evidence:
            if evidence.source == "resume":
                assert is_verbatim(evidence.quote, normalized), finding.requirement_text

    # Differences from the expected verdicts are reported, not failed: wording and judgment
    # vary by model, and this is how the thresholds and the prompt are tuned.
    for finding, expected in zip(result.findings, case.expected, strict=True):
        if (finding.verdict, finding.decided_by) != (expected[1], expected[2]):
            warnings.warn(
                f"{finding.requirement_text!r}: expected {expected[1]} by {expected[2]}, "
                f"got {finding.verdict} by {finding.decided_by}",
                stacklevel=1,
            )
