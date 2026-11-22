"""Eval settings, read from `EVAL_*` environment variables (use `uv run --env-file .env`).

The fabricated-evidence threshold is not here on purpose: it is fixed at 0.
"""

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EVAL_", extra="ignore", frozen=True)

    runs: int = Field(default=3, ge=1, le=10)  # times the analysis is repeated per case
    min_verdict_accuracy: float = Field(default=0.8, ge=0, le=1, allow_inf_nan=False)
    min_outcome_accuracy: float = Field(default=0.75, ge=0, le=1, allow_inf_nan=False)
    min_consistency: float = Field(default=0.9, ge=0, le=1, allow_inf_nan=False)


def problems(error: ValidationError) -> list[str]:
    """One line per invalid setting, named as in the environment (`EVAL_MIN_CONSISTENCY`)."""
    return [
        f"EVAL_{'_'.join(str(part) for part in item['loc']).upper()}: {item['msg']}"
        for item in error.errors()
    ]
