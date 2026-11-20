"""Domain errors and their single mapping to HTTP responses."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base class for business-rule failures. Subclass per feature."""

    status_code: int = 400
    code: str = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


async def _handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):  # pragma: no cover - registered for DomainError only
        raise exc
    return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message))


def _field_path(location: tuple[int | str, ...]) -> str:
    """Render a Pydantic location as ``stacks[0].years``, without the leading ``body``."""
    if location[:1] == ("body",):
        location = location[1:]
    if not location or isinstance(location[0], int):  # e.g. a JSON syntax error offset
        return "request body"
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else part
    return path


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - registered for it only
        raise exc
    # Only the field path and the reason: never `input`/`ctx`, which hold the submitted values.
    problems = [f"{_field_path(tuple(e['loc']))}: {e['msg']}" for e in exc.errors()]
    return JSONResponse(status_code=422, content=_body("validation_error", "; ".join(problems)))


async def _handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    # Log the type only: messages may contain DSNs or document content.
    logger.error("unhandled exception", extra={"exception_type": type(exc).__name__})
    return JSONResponse(status_code=500, content=_body("internal_error", "Internal server error"))


def register_error_handlers(app: FastAPI) -> None:
    """Register the one place where errors become HTTP responses."""
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
