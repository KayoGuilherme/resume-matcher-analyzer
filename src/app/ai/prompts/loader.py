"""Load versioned prompt files. Prompts are documents, never inline strings in code.

A prompt file starts with a header holding its integer version, then the prompt text:

    ---
    version: 1
    ---
    Text with {{placeholders}}.

The file is split into a system part and a user part at a line holding only `=== USER ===`
(a prompt without that line is all user text).
"""

import re
from dataclasses import dataclass
from importlib import resources

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
USER_MARKER = "=== USER ==="
_HEADER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_NAME = re.compile(r"\A[a-z][a-z0-9_]*\Z")


class PromptError(Exception):
    """A prompt file is missing or malformed. The message names the prompt, never content."""


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str
    user: str

    @property
    def placeholders(self) -> set[str]:
        return {match.group(1) for match in PLACEHOLDER.finditer(self.system + "\n" + self.user)}

    def render(self, **values: str) -> "RenderedPrompt":
        """Fill the placeholders in one pass. Values are inserted exactly as given and never
        scanned again, so text containing braces or `{{other}}` is safe."""
        expected = self.placeholders
        missing = sorted(expected - values.keys())
        if missing:
            raise PromptError(f"Prompt '{self.name}' has no value for placeholder '{missing[0]}'")
        unknown = sorted(values.keys() - expected)
        if unknown:
            raise PromptError(f"Prompt '{self.name}' has no placeholder '{unknown[0]}'")

        def fill(text: str) -> str:
            return PLACEHOLDER.sub(lambda match: values[match.group(1)], text)

        return RenderedPrompt(self.name, self.version, fill(self.system), fill(self.user))


@dataclass(frozen=True)
class RenderedPrompt:
    name: str
    version: int
    system: str
    user: str


def parse_prompt(name: str, raw: str) -> Prompt:
    header = _HEADER.match(raw.replace("\r\n", "\n"))
    if header is None:
        raise PromptError(f"Prompt '{name}' has no header with a version")
    version_line = next(
        (
            line.partition(":")[2].strip()
            for line in header.group(1).splitlines()
            if line.partition(":")[0].strip() == "version"
        ),
        None,
    )
    if version_line is None:
        raise PromptError(f"Prompt '{name}' has no version in its header")
    if not version_line.isdigit() or int(version_line) < 1:
        raise PromptError(f"Prompt '{name}' has an invalid version: it must be a positive integer")
    body = raw.replace("\r\n", "\n")[header.end() :].strip("\n")
    system, marker, user = body.partition(f"\n{USER_MARKER}\n")
    if not marker:
        system, user = "", body
    return Prompt(name, int(version_line), system.strip(), user.strip())


def load_prompt(name: str) -> Prompt:
    """Load `ai/prompts/<name>.md` from the installed package."""
    if not _NAME.match(name):
        raise PromptError(f"Prompt '{name}' is not a valid prompt name")
    resource = resources.files("app.ai.prompts").joinpath(f"{name}.md")
    try:
        raw = resource.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PromptError(f"Prompt '{name}' does not exist") from None
    return parse_prompt(name, raw)
