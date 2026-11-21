import math

import pytest

from app.ai.extraction.models import Certification, Education, LanguageSkill
from app.ai.matching.deterministic import Hints, Settled
from app.ai.matching.errors import EmbeddingModelMismatchError
from app.ai.matching.retrieval import (
    Candidates,
    ChunkMatrix,
    candidates,
    cosine,
    ensure_comparable,
    rank_chunks,
    section_lines,
)
from app.ai.matching.text import ResumeIndex
from tests.ai.matching.builders import chunk, job_input, kw, req, resume_input


def _unit(angle_degrees: float) -> tuple[float, float]:
    radians = math.radians(angle_degrees)
    return (math.cos(radians), math.sin(radians))


def _chunks_at(*angles: float) -> list:  # type: ignore[type-arg]
    return [chunk(f"chunk {n}", n, _unit(angle)) for n, angle in enumerate(angles)]


def test_cosine_of_parallel_orthogonal_and_opposite_vectors() -> None:
    assert cosine([1, 0], [2, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 3]) == pytest.approx(0.0)
    assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_a_zero_vector_gives_zero_and_does_not_divide_by_zero() -> None:
    assert cosine([0, 0], [1, 0]) == 0.0
    assert rank_chunks([0, 0], _chunks_at(0), top_k=3, min_similarity=0) == []
    assert rank_chunks([1, 0], [chunk("zero", 0, (0.0, 0.0))], top_k=3, min_similarity=0) == []


def test_top_k_above_the_minimum_most_similar_first() -> None:
    # angles 0..90 apart from the query at 0 degrees: similarities fall as the angle grows
    chunks = _chunks_at(60, 0, 10, 20, 30, 40, 50, 70, 80, 90)
    ranked = rank_chunks([1.0, 0.0], chunks, top_k=5, min_similarity=math.cos(math.radians(55)))

    assert [item.chunk.text for item in ranked] == [
        "chunk 1",
        "chunk 2",
        "chunk 3",
        "chunk 4",
        "chunk 5",
    ]
    assert [round(item.similarity, 2) for item in ranked] == sorted(
        (round(item.similarity, 2) for item in ranked), reverse=True
    )


def test_ten_scored_seven_above_the_minimum_top_k_five_gives_five() -> None:
    chunks = _chunks_at(0, 5, 10, 15, 20, 25, 30, 80, 85, 90)  # 7 within 40 degrees

    ranked = rank_chunks([1.0, 0.0], chunks, top_k=5, min_similarity=math.cos(math.radians(40)))

    assert len(ranked) == 5


def test_a_chunk_exactly_at_the_minimum_is_kept() -> None:
    ranked = rank_chunks([1.0, 0.0], [chunk("edge", 0, (3.0, 4.0))], top_k=3, min_similarity=0.6)

    assert [item.chunk.text for item in ranked] == ["edge"]
    assert ranked[0].similarity == 0.6


def test_just_below_the_minimum_is_dropped() -> None:
    ranked = rank_chunks([1.0, 0.0], [chunk("edge", 0, (3.0, 4.0))], top_k=3, min_similarity=0.61)

    assert ranked == []


def test_ties_are_broken_by_position_and_the_order_is_deterministic() -> None:
    chunks = [chunk("later", 5, (1.0, 0.0)), chunk("earlier", 2, (1.0, 0.0))]

    first = rank_chunks([1.0, 0.0], chunks, top_k=2, min_similarity=0)
    second = rank_chunks([1.0, 0.0], list(reversed(chunks)), top_k=2, min_similarity=0)

    assert (
        [item.chunk.text for item in first]
        == ["earlier", "later"]
        == [item.chunk.text for item in second]
    )


def test_the_matrix_ranks_the_same_as_the_function() -> None:
    chunks = _chunks_at(0, 30, 60, 90)
    matrix = ChunkMatrix(chunks)

    assert matrix.rank([1.0, 0.2], top_k=3, min_similarity=0.1) == rank_chunks(
        [1.0, 0.2], chunks, top_k=3, min_similarity=0.1
    )


def _index(text: str = "text", **kwargs):  # type: ignore[no-untyped-def]
    return ResumeIndex(resume_input(text, **kwargs))


def test_nothing_above_the_minimum_and_no_keyword_is_missing_by_retrieval() -> None:
    requirement = req("Terraform", keywords=[kw("Terraform")]).requirement

    outcome = candidates(requirement, [], Hints(), _index())

    assert isinstance(outcome, Settled)
    assert outcome.verdict == "missing" and outcome.code == "no_similar_content"


def test_a_keyword_chunk_below_the_minimum_is_still_a_candidate_and_there_are_no_repeats() -> None:
    similar = chunk("Used Terraform at scale", 0, (1.0, 0.0))
    keyword_only = chunk("Terraform modules", 1, (0.0, 1.0))
    requirement = req("Terraform", keywords=[kw("Terraform")]).requirement
    ranked = rank_chunks([1.0, 0.0], [similar, keyword_only], top_k=5, min_similarity=0.9)

    outcome = candidates(
        requirement, ranked, Hints(keyword_chunks=(similar, keyword_only)), _index()
    )

    assert isinstance(outcome, Candidates)
    assert [c.text for c in outcome.chunks] == ["Used Terraform at scale", "Terraform modules"]


def test_education_requirements_get_the_lines_of_the_education_entries() -> None:
    resume = resume_input(
        "EDUCATION\nB.Sc. Computer Science - State University\nSKILLS\nPython",
        education=[
            Education(
                institution="State University",
                degree="B.Sc.",
                field_of_study="Computer Science",
                start_year=None,
                end_year=None,
            )
        ],
        certifications=[Certification(name="AWS Certified Developer", issuer=None, date=None)],
    )
    requirement = req("A degree", category="education", keywords=[kw("degree")]).requirement

    outcome = candidates(requirement, [], Hints(), ResumeIndex(resume))

    assert isinstance(outcome, Candidates)
    assert outcome.lines == ("B.Sc. Computer Science - State University",)


def test_language_requirements_get_the_language_lines() -> None:
    resume = resume_input(
        "LANGUAGES\nEnglish - Advanced\nPortuguese - Native\nPython",
        languages=[LanguageSkill(name="English", level="Advanced")],
    )

    lines = section_lines(ResumeIndex(resume), "language")

    assert lines == ["English - Advanced"]


def test_other_categories_get_no_section_lines() -> None:
    resume = resume_input(
        "EDUCATION\nB.Sc. - State University",
        education=[
            Education(
                institution="State University",
                degree="B.Sc.",
                field_of_study=None,
                start_year=None,
                end_year=None,
            )
        ],
    )

    for category in ("skill", "years", "domain", "soft"):
        assert section_lines(ResumeIndex(resume), category) == []  # type: ignore[arg-type]


def test_a_resume_without_chunks_is_missing_unless_there_are_lines_or_keyword_hints() -> None:
    requirement = req("Kafka", keywords=[kw("Kafka")]).requirement

    assert isinstance(candidates(requirement, [], Hints(), _index()), Settled)


def test_a_resume_without_chunks_still_gives_education_lines() -> None:
    resume = resume_input(
        "EDUCATION\nState University",
        education=[
            Education(
                institution="State University",
                degree=None,
                field_of_study=None,
                start_year=None,
                end_year=None,
            )
        ],
    )
    requirement = req("A degree", category="education", keywords=[kw("degree")]).requirement

    assert isinstance(candidates(requirement, [], Hints(), ResumeIndex(resume)), Candidates)


def test_different_embedding_models_raise_the_mismatch_error() -> None:
    resume = resume_input("x", chunks=[chunk("a")], embedding_model="model-a")
    job = job_input(req("Python"), embedding_model="model-b")

    with pytest.raises(EmbeddingModelMismatchError):
        ensure_comparable(resume, job)


def test_different_vector_sizes_raise_the_mismatch_error() -> None:
    resume = resume_input("x", chunks=[chunk("a", 0, (1.0, 0.0, 0.0))])
    job = job_input(req("Python", vector=(1.0, 0.0)))

    with pytest.raises(EmbeddingModelMismatchError):
        ensure_comparable(resume, job)


def test_comparable_vectors_pass_the_guard() -> None:
    ensure_comparable(resume_input("x", chunks=[chunk("a")]), job_input(req("Python")))


def test_nothing_to_compare_passes_the_guard_whatever_the_models() -> None:
    ensure_comparable(
        resume_input("x", embedding_model="model-a"), job_input(req("Python"), embedding_model="b")
    )
    ensure_comparable(
        resume_input("x", chunks=[chunk("a")], embedding_model="model-a"),
        job_input(embedding_model="model-b"),
    )
