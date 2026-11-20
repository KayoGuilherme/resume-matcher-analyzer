"""Structured (JSON) logging. Never log resume content or personal data."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Libraries that print document or prompt content at DEBUG (pdfminer logs the tokens it parses, the
# provider SDKs log request details, httpx logs URLs). They are never allowed below WARNING,
# whatever the application log level is.
QUIET_LIBRARIES = (
    "pdfminer",
    "pdfplumber",
    "PIL",
    "openai",
    "anthropic",
    "httpx",
    "httpx2",
    "httpcore",
    "httpcore2",
    "sentence_transformers",
)

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Format records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            # Type only: exception messages may contain sensitive data.
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Configure the root logger with a single JSON stdout handler."""
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        raise ValueError(f"Unknown log level: {level}")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric)
    for name in QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(max(numeric, logging.WARNING))
