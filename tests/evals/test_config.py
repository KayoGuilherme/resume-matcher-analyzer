import pytest
from pydantic import ValidationError

from evals.config import EvalSettings, problems

NAMES = (
    "EVAL_RUNS",
    "EVAL_MIN_VERDICT_ACCURACY",
    "EVAL_MIN_OUTCOME_ACCURACY",
    "EVAL_MIN_CONSISTENCY",
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_the_defaults() -> None:
    settings = EvalSettings()

    assert settings.runs == 3
    assert settings.min_verdict_accuracy == 0.8
    assert settings.min_outcome_accuracy == 0.75
    assert settings.min_consistency == 0.9


def test_the_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_RUNS", "5")
    monkeypatch.setenv("EVAL_MIN_VERDICT_ACCURACY", "0.7")

    settings = EvalSettings()

    assert settings.runs == 5 and settings.min_verdict_accuracy == 0.7


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EVAL_MIN_CONSISTENCY", "1.5"),
        ("EVAL_MIN_CONSISTENCY", "-0.1"),
        ("EVAL_MIN_VERDICT_ACCURACY", "high"),
        ("EVAL_MIN_OUTCOME_ACCURACY", "nan"),
        ("EVAL_RUNS", "0"),
        ("EVAL_RUNS", "11"),
        ("EVAL_RUNS", "many"),
    ],
)
def test_an_invalid_value_is_reported_by_its_environment_name(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError) as error:
        EvalSettings()

    assert [line.split(":")[0] for line in problems(error.value)] == [name]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EVAL_RUNS", "1"),
        ("EVAL_RUNS", "10"),
        ("EVAL_MIN_CONSISTENCY", "0"),
        ("EVAL_MIN_CONSISTENCY", "1"),
    ],
)
def test_the_boundaries_are_accepted(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    EvalSettings()


def test_the_fabricated_evidence_threshold_has_no_setting() -> None:
    assert not any("fabricat" in name for name in EvalSettings.model_fields)
