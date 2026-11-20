"""Helpers the adapters share to turn SDK failures into the typed errors.

Messages carry the status code and the error type only: SDK exception strings can echo request
fragments, which contain resume text.
"""


def error_text(body: object) -> str:
    """Lower-cased text of an error body, used only to classify it (never stored or logged)."""
    return str(body).lower()


def mentions_temperature(param: object, text: str) -> bool:
    return param in {"temperature", "top_p", "top_k"} or "temperature" in text


def mentions_structured_output(param: object, text: str) -> bool:
    if isinstance(param, str) and param.startswith(("response_format", "tools", "tool_choice")):
        return True
    markers = (
        "response_format",
        "json_schema",
        "structured output",
        "structured_output",
        "does not support tools",
        "tools are not supported",
        "tool use is not supported",
        "tool_choice",
        "guided_json",
    )
    return any(marker in text for marker in markers)
