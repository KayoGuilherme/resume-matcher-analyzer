import json
import logging
from collections.abc import Iterator

import pytest

from app.ai.parsing import parse_document
from app.core.logging import QUIET_LIBRARIES, JsonFormatter, configure_logging
from tests.fixtures import documents


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


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    libraries = {name: logging.getLogger(name).level for name in QUIET_LIBRARIES}
    yield
    root.handlers, root.level = handlers, level
    for name, library_level in libraries.items():
        logging.getLogger(name).setLevel(library_level)


@pytest.mark.usefixtures("restore_logging")
def test_libraries_are_capped_at_warning_while_the_application_follows_the_level() -> None:
    configure_logging("DEBUG")

    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("app.anything").getEffectiveLevel() == logging.DEBUG
    for name in QUIET_LIBRARIES:
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING
        assert logging.getLogger(f"{name}.sub").getEffectiveLevel() == logging.WARNING


@pytest.mark.usefixtures("restore_logging")
def test_a_stricter_application_level_is_not_lowered_for_libraries() -> None:
    configure_logging("ERROR")

    assert logging.getLogger("pdfminer").getEffectiveLevel() == logging.ERROR


@pytest.mark.usefixtures("restore_logging")
def test_parsing_a_pdf_at_debug_level_logs_no_resume_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("DEBUG")

    parse_document(documents.clean_pdf(), "pdf")

    output = capsys.readouterr().out
    assert "Alex Example" not in output
    assert "payments platform" not in output


def test_ai_provider_libraries_are_quiet_libraries() -> None:
    assert {"openai", "anthropic", "httpx", "httpcore", "sentence_transformers"} <= set(
        QUIET_LIBRARIES
    )
