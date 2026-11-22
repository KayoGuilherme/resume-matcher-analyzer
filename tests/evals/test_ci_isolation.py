import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_no_workflow_runs_the_evals() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))

    assert workflows
    for workflow in workflows:
        text = workflow.read_text()
        assert "evals.run" not in text and "python -m evals" not in text, workflow.name


def test_the_default_test_run_collects_no_real_provider_test_and_never_the_evals() -> None:
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]

    assert "not integration and not real_provider" in " ".join(options["addopts"])
    assert options["testpaths"] == ["tests"]  # `evals/` is run on demand, not collected


def test_env_example_lists_the_four_eval_settings_with_their_defaults() -> None:
    example = (ROOT / ".env.example").read_text()

    for line in (
        "EVAL_RUNS=3",
        "EVAL_MIN_VERDICT_ACCURACY=0.8",
        "EVAL_MIN_OUTCOME_ACCURACY=0.75",
        "EVAL_MIN_CONSISTENCY=0.9",
    ):
        assert f"\n{line}\n" in example
    assert "never in CI" in example
