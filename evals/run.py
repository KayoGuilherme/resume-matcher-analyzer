"""`uv run python -m evals.run`: run the eval cases against the configured providers.

Exit status 0: every metric meets its threshold. 1: a metric is below its threshold (any
fabricated evidence counts). 2: the run could not be done (bad configuration, dataset or case id,
no provider, a case that failed). Output names cases, requirement matches, verdicts and numbers,
never resume, job or profile text, quotes or suggestions.
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.ai.embeddings import get_embedding_client
from app.ai.errors import AINotConfiguredError
from app.ai.llm import get_llm_client
from app.analyses.service import analysis_settings, report_settings, score_settings
from app.core.config import Settings as AppSettings
from evals import config, metrics, runner
from evals.dataset import CASES_DIR, Case, DatasetError, load_cases

OK, BELOW_THRESHOLD, CANNOT_RUN = 0, 1, 2
_UNUSED_DATABASE = "postgresql+asyncpg://unused:unused@localhost:5432/unused"  # never connected to


def _say(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _fail(text: str) -> int:
    sys.stderr.write(text + "\n")
    return CANNOT_RUN


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run", description="Run the eval cases against the real providers."
    )
    parser.add_argument("--runs", type=int, help="times to repeat the analysis per case")
    parser.add_argument("--case", action="append", default=[], help="a case id (repeatable)")
    parser.add_argument("--output", type=Path, help="write the full results as JSON here")
    return parser.parse_args(argv)


def _app_settings() -> AppSettings:
    """The application settings for the providers and the analysis. The database is never used,
    so a missing `DATABASE_URL` is not an error."""
    return AppSettings(database_url=os.environ.get("DATABASE_URL") or _UNUSED_DATABASE)


def _clients() -> runner.Clients:
    app_settings = _app_settings()
    return runner.Clients(get_llm_client(app_settings), get_embedding_client(app_settings))


def _pipeline_settings(runs: int) -> runner.Settings:
    app_settings = _app_settings()
    return runner.Settings(
        runs=runs,
        analysis=analysis_settings(app_settings),
        report=report_settings(app_settings),
        score=score_settings(app_settings),
    )


def _percent(value: float) -> str:
    return f"{value:.2f}"


def _case_lines(result: metrics.CaseResult) -> list[str]:
    outcomes = ", ".join(run.outcome or "none" for run in result.runs)
    lines = [f"{result.case_id}: outcome expected {result.expected_outcome}, got {outcomes}"]
    lines += [
        f"    {wrong.match}: expected {wrong.expected}, got {' / '.join(wrong.actual)}"
        + (f" ({wrong.reason})" if wrong.reason else "")
        for wrong in metrics.wrong_requirements(result)
    ]
    return lines


def _summary(summary: metrics.Metrics, failures: Sequence[metrics.Failure]) -> list[str]:
    failed = {failure.metric for failure in failures}

    def mark(name: str) -> str:
        return "  FAIL" if name in failed else ""

    return [
        "",
        f"verdict accuracy:          {_percent(summary.verdict_accuracy)}"
        f"{mark('verdict accuracy')}",
        f"outcome accuracy:          {_percent(summary.outcome_accuracy)}"
        f"{mark('outcome accuracy')}",
        f"fabricated-evidence rate:  {_percent(summary.fabricated_rate)} "
        f"({summary.fabricated} of {summary.checked}){mark('fabricated-evidence rate')}",
        f"consistency:               {_percent(summary.consistency)}{mark('consistency')}",
        f"  outcome consistency:     {_percent(summary.outcome_consistency)}",
        f"  screener consistency:    {_percent(summary.screener_consistency)}",
        f"  dropped quote share:     {_percent(summary.dropped_quote_share)}",
    ]


def _json(results: Sequence[metrics.CaseResult], summary: metrics.Metrics) -> str:
    return json.dumps({"metrics": asdict(summary), "cases": [asdict(r) for r in results]}, indent=2)


def _select(cases: list[Case], wanted: Sequence[str]) -> list[Case] | str:
    if not wanted:
        return cases
    known = {case.id for case in cases}
    unknown = sorted(set(wanted) - known)
    if unknown:
        return f"unknown case id: {', '.join(unknown)} (known: {', '.join(sorted(known))})"
    return [case for case in cases if case.id in set(wanted)]


def main(
    argv: Sequence[str] | None = None,
    *,
    cases_dir: Path = CASES_DIR,
    clients: runner.Clients | None = None,
) -> int:
    args = _parse(argv)
    try:
        eval_settings = config.EvalSettings()
    except ValidationError as error:
        return _fail("invalid eval settings:\n  " + "\n  ".join(config.problems(error)))
    runs = args.runs if args.runs is not None else eval_settings.runs
    if not 1 <= runs <= 10:
        return _fail("invalid --runs: it must be a whole number from 1 to 10")

    try:
        selected = _select(load_cases(cases_dir), args.case)
    except DatasetError as error:
        return _fail(f"invalid dataset: {error}")
    if isinstance(selected, str):
        return _fail(selected)

    try:
        use = clients or _clients()
    except AINotConfiguredError as error:
        return _fail(f"cannot run: {error}")

    _say(f"running {len(selected)} case(s), {runs} run(s) each")
    results, errors = asyncio.run(
        runner.run_cases(selected, use, _pipeline_settings(runs), datetime.now(UTC))
    )
    if errors:
        for item in errors:
            _say(f"{item.case_id}: ERROR ({item.error_type})")
        return _fail(f"{len(errors)} case(s) could not finish: the metrics are not trusted")

    summary = metrics.summarize(results)
    failures = metrics.gate(summary, eval_settings)
    for result in results:
        for line in _case_lines(result):
            _say(line)
    for line in _summary(summary, failures):
        _say(line)
    if args.output is not None:
        args.output.write_text(_json(results, summary), encoding="utf-8")
    if failures:
        _say("")
        for failure in failures:
            _say(
                f"FAILED {failure.metric}: {_percent(failure.value)} is {failure.direction} "
                f"the threshold {_percent(failure.threshold)}"
            )
        return BELOW_THRESHOLD
    _say("\nall metrics meet their thresholds")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
