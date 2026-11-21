"""Turn model text into a validated schema instance."""

import json
from typing import Any

from pydantic import BaseModel, ValidationError


class OutputProblem(Exception):
    """The text is not valid for the schema. `problems` are safe to repeat to the model."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("invalid structured output")
        self.problems = problems


def extract_json(text: str) -> Any:
    """Parse JSON that may be wrapped in a Markdown fence or in a sentence."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char in "{[":
            try:
                value, _ = decoder.raw_decode(stripped, index)
            except ValueError:
                continue
            return value
    raise ValueError("no JSON value found")


def parse_structured[T: BaseModel](text: str, schema: type[T]) -> T:
    """Extract JSON from `text` and validate it. Problems name fields, never echo values."""
    try:
        data = extract_json(text)
    except ValueError:
        raise OutputProblem(["the answer is not valid JSON"]) from None
    try:
        return schema.model_validate(data)
    except ValidationError as error:
        problems = [
            f"{'.'.join(str(part) for part in item['loc']) or 'answer'}: {item['msg']}"
            for item in error.errors()
        ]
        raise OutputProblem(problems) from None
