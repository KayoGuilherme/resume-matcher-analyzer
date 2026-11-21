import pytest

from app.ai.embeddings.dimension import EmbeddingDimensionMismatchError, check_embedding_dimension


def test_equal_sizes_and_a_missing_table_pass() -> None:
    check_embedding_dimension(1024, 1024)
    check_embedding_dimension(1024, None, table="job_requirements")


@pytest.mark.parametrize("table", ["resume_chunk", "job_requirements"])
def test_the_message_names_the_table_both_sizes_and_the_procedure(table: str) -> None:
    with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
        check_embedding_dimension(768, 1024, table=table)

    message = str(exc_info.value)
    assert f"{table}.embedding" in message
    assert "768" in message and "1024" in message
    assert "Changing the embedding model" in message


def test_the_default_table_is_resume_chunk() -> None:
    with pytest.raises(EmbeddingDimensionMismatchError, match="resume_chunk"):
        check_embedding_dimension(768, 1024)
