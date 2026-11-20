import pytest

from app.ai.prompts.loader import Prompt, PromptError, load_prompt, parse_prompt


def test_a_prompt_is_loaded_by_name_without_its_header() -> None:
    prompt = load_prompt("resume_extraction")

    assert prompt.name == "resume_extraction"
    assert isinstance(prompt.version, int) and prompt.version >= 1
    assert not prompt.system.startswith("---")
    assert "version:" not in prompt.user
    assert prompt.placeholders == {"resume_text", "corrections"}


def test_the_system_and_user_parts_are_split_at_the_marker() -> None:
    prompt = parse_prompt("p", "---\nversion: 3\n---\nSystem text\n=== USER ===\nUser {{x}}\n")

    assert (prompt.version, prompt.system, prompt.user) == (3, "System text", "User {{x}}")


def test_a_prompt_without_a_marker_is_all_user_text() -> None:
    prompt = parse_prompt("p", "---\nversion: 1\n---\nJust text\n")

    assert (prompt.system, prompt.user) == ("", "Just text")


def test_a_missing_version_names_the_prompt() -> None:
    with pytest.raises(PromptError, match="'p'.*version"):
        parse_prompt("p", "---\nowner: me\n---\ntext")


def test_a_missing_header_is_an_error() -> None:
    with pytest.raises(PromptError, match="'p'.*version"):
        parse_prompt("p", "text without header")


@pytest.mark.parametrize("version", ["abc", "0", "-1", "1.5", ""])
def test_an_invalid_version_is_an_error(version: str) -> None:
    with pytest.raises(PromptError, match="'p'.*invalid version"):
        parse_prompt("p", f"---\nversion: {version}\n---\ntext")


def test_an_unknown_prompt_names_it() -> None:
    with pytest.raises(PromptError, match="'nope'.*does not exist"):
        load_prompt("nope")


@pytest.mark.parametrize("name", ["../secrets", "a/b", "A", ""])
def test_a_prompt_name_cannot_escape_the_prompts_folder(name: str) -> None:
    with pytest.raises(PromptError, match="not a valid prompt name"):
        load_prompt(name)


def _prompt() -> Prompt:
    return parse_prompt("p", "---\nversion: 1\n---\nSys {{a}}\n=== USER ===\nUser {{b}} {{a}}")


def test_values_are_inserted_in_both_parts() -> None:
    rendered = _prompt().render(a="1", b="2")

    assert (rendered.system, rendered.user) == ("Sys 1", "User 2 1")
    assert (rendered.name, rendered.version) == ("p", 1)


def test_values_with_braces_and_placeholder_names_are_inserted_unchanged() -> None:
    nasty = 'function() { return {{b}}; } and {{a}} {"k": "v"}'

    rendered = _prompt().render(a=nasty, b="B")

    assert rendered.system == f"Sys {nasty}"
    assert rendered.user == f"User B {nasty}"


def test_a_missing_value_names_the_placeholder() -> None:
    with pytest.raises(PromptError, match="placeholder 'b'"):
        _prompt().render(a="1")


def test_an_unknown_value_is_rejected() -> None:
    with pytest.raises(PromptError, match="no placeholder 'zzz'"):
        _prompt().render(a="1", b="2", zzz="3")
