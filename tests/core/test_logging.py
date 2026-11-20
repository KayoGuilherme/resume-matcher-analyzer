import json
import logging

import pytest

from app.core.logging import JsonFormatter, configure_logging


def _record(msg: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord("app.test", level, __file__, 1, msg, None, None)


def test_formatter_outputs_valid_json_with_core_fields() -> None:
    line = JsonFormatter().format(_record("hello"))

    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert "timestamp" in payload


def test_formatter_includes_extra_fields() -> None:
    record = _record("hello")
    record.request_path = "/health"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["request_path"] == "/health"


def test_formatter_includes_exception_type_only() -> None:
    try:
        raise ValueError("secret resume text")
    except ValueError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())

    payload = json.loads(JsonFormatter().format(record))

    assert payload["exception_type"] == "ValueError"
    assert "secret resume text" not in json.dumps(payload)


def test_configure_logging_sets_level_and_single_json_handler() -> None:
    configure_logging("WARNING")
    configure_logging("WARNING")  # idempotent

    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_logging_rejects_unknown_level() -> None:
    with pytest.raises(ValueError):
        configure_logging("NOPE")
