"""The check that the configured embedding size matches a vector column in the database."""


class EmbeddingDimensionMismatchError(RuntimeError):
    """The configured EMBEDDING_DIMENSION does not match the database. The app must not start."""


def check_embedding_dimension(
    configured: int, in_database: int | None, table: str = "resume_chunk"
) -> None:
    """Fail loudly when the vector column of `table` and the configuration disagree.

    `in_database` is None when the table does not exist yet: nothing to compare.
    """
    if in_database is None or in_database == configured:
        return
    raise EmbeddingDimensionMismatchError(
        f"EMBEDDING_DIMENSION is {configured} but the database column {table}.embedding has "
        f"{in_database} dimensions. Set EMBEDDING_DIMENSION={in_database}, or follow the "
        "procedure in README.md, section 'Changing the embedding model', to change the model."
    )
