import pytest

from app.ai.matching.text import (
    AMBIGUOUS_MAX_LENGTH,
    MAX_QUOTE_CHARS,
    ResumeIndex,
    SearchableText,
    ats_forms,
    fold,
    keyword_forms,
    usable,
)
from app.core.normalization import aliases_of
from tests.ai.matching.builders import chunk, kw, resume_input


def _found(text: str, *forms: str) -> list[str]:
    return [match.text for match in SearchableText(text).find(list(forms))]


def test_aliases_of_is_the_inverse_of_the_alias_tables() -> None:
    assert aliases_of("kubernetes") == ["k8s"]
    assert aliases_of("portuguese", language=True) == ["portugues", "pt"]
    assert aliases_of("rust") == []
    assert aliases_of("Kubernetes") == ["k8s"]
    assert aliases_of("portuguese") == []  # a language name is not a stack


def test_java_is_not_found_in_javascript() -> None:
    assert _found("I know JavaScript", "java") == []
    assert _found("I know Java, JavaScript", "java") == ["Java"]


def test_c_is_not_found_in_c_plus_plus_or_c_sharp() -> None:
    assert _found("Wrote C++ and C# services", "c") == []
    assert _found("Wrote C and C++ services", "c") == ["C"]


@pytest.mark.parametrize(
    ("text", "form"),
    [
        ("Wrote C++ services", "c++"),
        ("Wrote C# services", "c#"),
        ("Built it in Node.js, then more", "node.js"),
        ("Worked on ASP .NET apps", ".net"),
        ("Used Python.", "python"),
        ("Skills: Python, Go", "python"),
    ],
)
def test_terms_with_symbols_and_punctuation_are_found_whole(text: str, form: str) -> None:
    assert len(_found(text, form)) == 1


def test_dot_net_is_not_found_inside_another_word() -> None:
    assert _found("asp.net apps", ".net") == []


def test_case_and_accents_are_ignored_and_the_text_is_returned_as_written() -> None:
    assert _found("Experiência com PROGRAMAÇÃO", "programacao") == ["PROGRAMAÇÃO"]
    assert _found("Deployed on K8s", "k8s") == ["K8s"]


def test_multiple_matches_come_in_text_order_one_per_span() -> None:
    matches = SearchableText("Go first, then Python, then Go again").find(["go", "python", "go"])

    assert [match.text for match in matches] == ["Go", "Python", "Go"]
    assert [match.start for match in matches] == sorted(match.start for match in matches)


def test_whitespace_is_collapsed_inside_a_term() -> None:
    assert _found("Spring   Boot services", "spring boot") == ["Spring   Boot"]


def test_a_term_wrapped_over_a_line_break_is_found_as_one_space() -> None:
    assert _found("Spring\nBoot services", "spring boot") == ["Spring\nBoot"]


def test_literal_means_literal_no_stemming_and_no_translation() -> None:
    assert _found("I managed teams", "management") == []
    assert _found("Inglês fluente", "english") == []


def test_go_in_go_to_market_is_found_but_flagged_ambiguous() -> None:
    (match,) = SearchableText("Go-to-market planning").find(["go"])

    assert match.ambiguous
    assert usable([match]) == []
    assert len("go") <= AMBIGUOUS_MAX_LENGTH


def test_a_three_character_form_is_not_ambiguous() -> None:
    (match,) = SearchableText("Used SQL daily").find(["sql"])

    assert not match.ambiguous


def test_fold_is_lowercase_accent_free_with_single_spaces() -> None:
    assert fold("  Programação   EM  Português ") == "programacao em portugues"


def test_keyword_forms_hold_the_name_synonyms_and_aliases() -> None:
    forms = keyword_forms(kw("Kubernetes", "K8s", "kube"))

    assert forms == ["kubernetes", "k8s", "kube"]


def test_keyword_forms_use_the_language_aliases_for_languages() -> None:
    forms = keyword_forms(kw("Português", language=True), language=True)

    assert {"portuguese", "pt", "portugues"} <= set(forms)


def test_keyword_forms_are_folded() -> None:
    assert keyword_forms(kw("Programação")) == ["programacao"]


def test_ats_forms_hold_the_name_and_its_aliases() -> None:
    assert ats_forms("kubernetes") == ["kubernetes", "k8s"]
    assert ats_forms("rust") == ["rust"]


def test_resume_index_quotes_the_chunk_that_contains_the_match() -> None:
    bullet = "Deployed services on K8s with Helm"
    index = ResumeIndex(
        resume_input(
            f"EXPERIENCE\n{bullet}\nOther line",
            chunks=[chunk("Wrote docs", 0), chunk(bullet, 1)],
        )
    )

    assert index.passages(["kubernetes", "k8s"], 3) == [bullet]


def test_resume_index_falls_back_to_the_resume_line_outside_the_chunks() -> None:
    index = ResumeIndex(
        resume_input("EDUCATION\nB.Sc. Computer Science - State University\nSKILLS\nPython")
    )

    assert index.passages(["computer science"], 3) == ["B.Sc. Computer Science - State University"]


def test_resume_index_does_not_quote_a_line_twice_when_a_chunk_already_holds_it() -> None:
    bullet = "Built APIs in Python"
    index = ResumeIndex(resume_input(f"EXPERIENCE\n{bullet}\n", chunks=[chunk(bullet)]))

    assert index.passages(["python"], 3) == [bullet]


def test_resume_index_returns_at_most_the_limit_in_resume_order() -> None:
    chunks = [chunk(f"Used Python in project {n}", n) for n in range(5)]
    index = ResumeIndex(resume_input("\n".join(c.text for c in chunks), chunks=chunks))

    assert index.passages(["python"], 3) == [c.text for c in chunks[:3]]


def test_resume_index_ignores_ambiguous_matches_unless_asked() -> None:
    index = ResumeIndex(resume_input("Go-to-market planning\n", chunks=[chunk("Go-to-market")]))

    assert index.passages(["go"], 3) == []
    assert index.passages(["go"], 3, allow_ambiguous=True) == ["Go-to-market"]
    assert index.chunks_matching(["go"]) == []
    assert len(index.chunks_matching(["go"], allow_ambiguous=True)) == 1


def test_a_long_line_is_cut_to_a_stretch_that_still_holds_the_match_and_is_verbatim() -> None:
    long_line = "x " * 500 + "Terraform" + " y" * 500
    index = ResumeIndex(resume_input(long_line))

    (quote,) = index.passages(["terraform"], 3)

    assert len(quote) <= MAX_QUOTE_CHARS
    assert "Terraform" in quote
    assert quote in long_line


def test_a_long_chunk_is_cut_the_same_way() -> None:
    long_bullet = "word " * 200 + "Kafka" + " word" * 200
    index = ResumeIndex(resume_input(long_bullet, chunks=[chunk(long_bullet)]))

    (quote,) = index.passages(["kafka"], 3)

    assert len(quote) <= MAX_QUOTE_CHARS and "Kafka" in quote and quote in long_bullet


def test_chunks_matching_come_in_position_order() -> None:
    chunks = [chunk("Python b", 2), chunk("Python a", 1), chunk("Rust", 0)]
    index = ResumeIndex(resume_input("text", chunks=chunks))

    assert [c.text for c in index.chunks_matching(["python"])] == ["Python a", "Python b"]
