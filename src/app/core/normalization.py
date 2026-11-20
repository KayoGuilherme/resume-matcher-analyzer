"""Canonical forms for technology and spoken-language names. Pure functions, no I/O.

Callers keep the text as typed themselves; these functions only return the canonical text.
"""

import unicodedata
from collections.abc import Mapping
from types import MappingProxyType

# Keys are already clean: lowercase, single spaces, no accents.
STACK_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "springboot": "spring boot",
        "postgres": "postgresql",
        "js": "javascript",
    }
)

LANGUAGE_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "pt": "portuguese",
        "portugues": "portuguese",
        "en": "english",
        "ingles": "english",
    }
)


def _clean(text: str) -> str:
    return " ".join(text.split()).lower()


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def fold_text(text: str) -> str:
    """Compare-friendly form of free text: trimmed, single spaces, lowercase, no accents."""
    return _strip_accents(_clean(text))


def _normalize(text: str, aliases: Mapping[str, str]) -> str:
    cleaned = _clean(text)
    return aliases.get(_strip_accents(cleaned), cleaned)


def normalize_stack_name(text: str) -> str:
    """Return the canonical name of a technology (e.g. ``Postgres`` -> ``postgresql``)."""
    return _normalize(text, STACK_ALIASES)


def normalize_language_name(text: str) -> str:
    """Return the canonical name of a spoken language (e.g. ``Português`` -> ``portuguese``)."""
    return _normalize(text, LANGUAGE_ALIASES)
