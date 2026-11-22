import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ai.embeddings.base import EmbeddingClient
from app.ai.llm.base import LLMClient
from app.ai.matching.models import JudgeBatch
from evals import run as run_module
from evals import runner
from evals.dataset import load_case
from tests.ai.extraction.builders import RESUME_TEXT
from tests.analyses.fakes import ConstantEmbeddingClient
from tests.evals.fakes import RoutedLLM
from tests.fixtures.job_postings import ENGLISH

PROFILE = {
    "target_role": "Backend Developer",
    "seniority": "mid",
    "total_years_coding": 5,
    "stacks": [{"name": "Terraform", "years": 2, "level": "working"}],
    "languages": [{"name": "English", "level": "C1"}],
    "notable_facts": [],
}
SPEC = {
    "language": "en",
    "expected_outcome": "likely_reject",
    "requirements": [
        {"match": "terraform", "verdict": "in_profile_not_in_resume"},
        {"match": "fintech", "verdict": "missing"},
    ],
}
THRESHOLDS = (
    "EVAL_RUNS",
    "EVAL_MIN_VERDICT_ACCURACY",
    "EVAL_MIN_OUTCOME_ACCURACY",
    "EVAL_MIN_CONSISTENCY",
    "DATABASE_URL",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in THRESHOLDS:
        monkeypatch.delenv(name, raising=False)


def make_dir(tmp_path: Path, **spec: object) -> Path:
    root = tmp_path / "cases"
    folder = root / "en-99"
    folder.mkdir(parents=True)
    (folder / "resume.txt").write_text(RESUME_TEXT)
    (folder / "job.txt").write_text(ENGLISH.text)
    (folder / "profile.json").write_text(json.dumps(PROFILE))
    (folder / "case.json").write_text(json.dumps({**SPEC, **spec}))
    return root


def clients(llm: RoutedLLM | None = None) -> runner.Clients:
    fake: LLMClient = llm or RoutedLLM()
    embedder: EmbeddingClient = ConstantEmbeddingClient(8, "constant")
    return runner.Clients(fake, embedder)


def execute(root: Path, *args: str, llm: RoutedLLM | None = None) -> int:
    return run_module.main(["--runs", "2", *args], cases_dir=root, clients=clients(llm))


def test_everything_passing_exits_zero_and_prints_a_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = execute(make_dir(tmp_path))

    out = capsys.readouterr().out
    assert status == 0
    assert "verdict accuracy:          1.00" in out
    assert "fabricated-evidence rate:  0.00" in out
    assert "consistency:               1.00" in out
    assert "all metrics meet their thresholds" in out
    assert "en-99: outcome expected likely_reject, got likely_reject, likely_reject" in out


def test_a_wrong_verdict_exits_one_naming_the_metric(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wrong = [
        {"match": "terraform", "verdict": "met"},
        {"match": "fintech", "verdict": "partial"},
    ]

    status = execute(make_dir(tmp_path, requirements=wrong))

    out = capsys.readouterr().out
    assert status == 1
    assert "FAILED verdict accuracy: 0.00 is below the threshold 0.80" in out
    assert "terraform: expected met, got in_profile_not_in_resume" in out


def test_a_wrong_outcome_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status = execute(make_dir(tmp_path, expected_outcome="likely_pass"))

    assert status == 1
    assert "FAILED outcome accuracy" in capsys.readouterr().out


def test_fabricated_evidence_exits_one_even_when_the_rest_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_analyze = runner.analyze

    async def bypassing_the_guard(*args, **kwargs):  # type: ignore[no-untyped-def]
        result = await real_analyze(*args, **kwargs)
        findings = list(result.findings)
        index = next(n for n, f in enumerate(findings) if f.evidence)
        invented = (
            findings[index].evidence[0].model_copy(update={"quote": "Led a team of nine at Orbit"})
        )
        findings[index] = findings[index].model_copy(update={"evidence": [invented]})
        return result.model_copy(update={"findings": findings})

    monkeypatch.setattr(runner, "analyze", bypassing_the_guard)

    status = execute(make_dir(tmp_path))

    out = capsys.readouterr().out
    assert status == 1
    assert (
        "FAILED fabricated-evidence rate" in out
        and "below" not in out.split("FAILED fabricated")[1]
    )


def test_an_unknown_case_id_exits_two_before_anything_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    llm = RoutedLLM()

    status = execute(make_dir(tmp_path), "--case", "nope", llm=llm)

    assert status == 2 and llm.calls == []
    assert "nope" in capsys.readouterr().err


def test_a_selected_case_is_the_only_one_run(tmp_path: Path) -> None:
    root = make_dir(tmp_path)
    other = root / "en-98"
    other.mkdir()
    for name in ("resume.txt", "job.txt", "profile.json", "case.json"):
        (other / name).write_text((root / "en-99" / name).read_text())
    llm = RoutedLLM()

    status = execute(root, "--case", "en-98", llm=llm)

    assert status == 0
    assert llm.calls.count(JudgeBatch) == 2 * 1  # one case, two runs, one judge call each


def test_no_provider_configured_exits_two_without_a_stack_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run_module.main(["--runs", "1"], cases_dir=make_dir(tmp_path))

    err = capsys.readouterr().err
    assert status == 2
    assert "LLM_PROVIDER" in err and "Traceback" not in err


def test_an_invalid_threshold_exits_two_naming_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EVAL_MIN_CONSISTENCY", "1.5")

    status = execute(make_dir(tmp_path))

    assert status == 2 and "EVAL_MIN_CONSISTENCY" in capsys.readouterr().err


def test_an_invalid_runs_option_exits_two(tmp_path: Path) -> None:
    assert run_module.main(["--runs", "0"], cases_dir=make_dir(tmp_path), clients=clients()) == 2


def test_an_invalid_dataset_exits_two_naming_the_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_dir(tmp_path, expected_outcome="maybe")

    status = execute(root)

    assert status == 2 and "case en-99" in capsys.readouterr().err


def test_a_case_that_cannot_finish_is_an_error_and_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = execute(make_dir(tmp_path), llm=RoutedLLM(fail_on=JudgeBatch))

    captured = capsys.readouterr()
    assert status == 2
    assert "en-99: ERROR (LLMTransientError)" in captured.out
    assert "not trusted" in captured.err


def test_nothing_is_written_without_output_and_the_file_is_json_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_dir(tmp_path)
    monkeypatch.chdir(tmp_path)
    execute(root)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["cases"]

    target = tmp_path / "results.json"
    execute(root, "--output", str(target))

    data = json.loads(target.read_text())
    assert set(data) == {"metrics", "cases"}
    assert data["metrics"]["verdict_accuracy"] == 1.0
    assert data["cases"][0]["case_id"] == "en-99" and len(data["cases"][0]["runs"]) == 2


def test_the_output_contains_no_case_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "results.json"
    execute(make_dir(tmp_path), "--output", str(target))

    printed = capsys.readouterr()
    everything = printed.out + printed.err + target.read_text()
    sentences = [line.strip("•- ") for line in RESUME_TEXT.splitlines() if len(line) > 25]
    sentences += [line.strip("- ") for line in ENGLISH.text.splitlines() if len(line) > 25]
    assert sentences
    for sentence in sentences:
        assert sentence not in everything


def test_no_database_connection_is_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.db as db

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("the evals must not touch the database")

    monkeypatch.setattr(db, "get_engine", refuse)
    monkeypatch.setattr(db, "get_sessionmaker", refuse)

    assert execute(make_dir(tmp_path)) == 0


async def test_run_case_reports_the_verdicts_and_checks_them_independently(
    tmp_path: Path,
) -> None:
    case = load_case(make_dir(tmp_path) / "en-99")

    result = await runner.run_case(
        case,
        clients(),
        run_module._pipeline_settings(2),
        datetime.now(UTC),
    )

    assert result.case_id == "en-99" and len(result.runs) == 2
    first = result.runs[0]
    assert [(c.match, c.actual) for c in first.checks] == [
        ("terraform", "in_profile_not_in_resume"),
        ("fintech", "missing"),
    ]
    assert first.fabrication.fabricated == 0 and first.fabrication.checked > 0
    assert first.screener_decision == "reject" and first.screener_consistency == 1.0


def test_evals_imports_no_provider_library() -> None:
    root = Path(__file__).resolve().parents[2] / "evals"
    providers = {"anthropic", "openai", "sentence_transformers", "httpx", "httpx2"}
    imported: set[str] = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])

    assert not imported & providers
    assert "evals" in imported  # the scan sees the package
