import uuid
from typing import Any

import pytest

from app.ai.matching.cache import cache_key, inputs_fingerprint
from app.ai.matching.models import AnalysisSettings
from app.ai.matching.report_models import ReportSettings

RESUME_ID = uuid.UUID(int=1)
JOB_ID = uuid.UUID(int=2)
SETTINGS = AnalysisSettings(
    top_k=5, min_similarity=0.4, max_requirements_per_call=8, max_llm_calls=10
)


REPORT = ReportSettings(screener_runs=3, max_suggestions=8)


def _fingerprint(**overrides: Any) -> str:
    values: dict[str, Any] = {
        "resume_extraction": {"resume": {"skills": ["Python"]}, "extracted_at": "2026-01-01"},
        "resume_embedding_model": "bge-m3",
        "job_extraction": {"job": {"requirements": ["Python"]}},
        "job_embedding_model": "bge-m3",
        "profile": {"stacks": [{"name": "python", "years": 5}]},
    }
    values.update(overrides)
    return inputs_fingerprint(**values)


def _key(**overrides: Any) -> str:
    values: dict[str, Any] = {
        "resume_id": RESUME_ID,
        "job_id": JOB_ID,
        "prompt_name": "gap_judge",
        "prompt_version": 1,
        "llm_provider": "openai",
        "llm_model": "m1",
        "settings": SETTINGS,
        "screener_prompt": "screener:1",
        "suggestions_prompt": "rewrite_suggestions:1",
        "report_settings": REPORT,
        "fingerprint": _fingerprint(),
    }
    values.update(overrides)
    return cache_key(**values)


def test_the_same_inputs_give_the_same_key() -> None:
    assert _key() == _key()
    assert _fingerprint() == _fingerprint()


def test_the_key_is_64_hex_characters() -> None:
    key = _key()

    assert len(key) == 64 and int(key, 16) >= 0


@pytest.mark.parametrize(
    "change",
    [
        {"resume_id": uuid.UUID(int=3)},
        {"job_id": uuid.UUID(int=3)},
        {"prompt_version": 2},
        {"prompt_name": "other"},
        {"llm_provider": "anthropic"},
        {"llm_model": "m2"},
        {"settings": SETTINGS.model_copy(update={"top_k": 4})},
        {"settings": SETTINGS.model_copy(update={"min_similarity": 0.5})},
        {"settings": SETTINGS.model_copy(update={"max_requirements_per_call": 7})},
        {"settings": SETTINGS.model_copy(update={"max_llm_calls": 9})},
        {"screener_prompt": "screener:2"},
        {"screener_prompt": "other:1"},
        {"suggestions_prompt": "rewrite_suggestions:2"},
        {"suggestions_prompt": "other:1"},
        {"report_settings": REPORT.model_copy(update={"screener_runs": 5})},
        {"report_settings": REPORT.model_copy(update={"max_suggestions": 0})},
    ],
)
def test_each_of_these_changes_the_key(change: dict[str, Any]) -> None:
    assert _key(**change) != _key()


@pytest.mark.parametrize(
    "change",
    [
        {"profile": {"stacks": [{"name": "python", "years": 6}]}},
        {"resume_extraction": {"resume": {"skills": ["Python"]}, "extracted_at": "2026-01-02"}},
        {"job_extraction": {"job": {"requirements": ["Go"]}}},
        {"resume_embedding_model": "other"},
        {"job_embedding_model": "other"},
    ],
)
def test_each_of_these_changes_the_fingerprint_and_so_the_key(change: dict[str, Any]) -> None:
    assert _fingerprint(**change) != _fingerprint()
    assert _key(fingerprint=_fingerprint(**change)) != _key()


def test_the_order_of_dict_fields_does_not_matter() -> None:
    first = _fingerprint(profile={"a": 1, "b": {"x": 1, "y": 2}})
    second = _fingerprint(profile={"b": {"y": 2, "x": 1}, "a": 1})

    assert first == second


def test_the_order_of_list_items_does_matter() -> None:
    assert _fingerprint(profile={"a": [1, 2]}) != _fingerprint(profile={"a": [2, 1]})


def test_a_score_setting_is_not_part_of_the_key() -> None:
    import inspect

    assert not any("score" in name for name in inspect.signature(cache_key).parameters)
