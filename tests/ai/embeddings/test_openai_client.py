import httpx2
import pytest
from openai import AsyncOpenAI

from app.ai.embeddings.base import (
    EmbeddingAuthError,
    EmbeddingError,
    EmbeddingTimeoutError,
    EmbeddingTransientError,
)
from app.ai.embeddings.openai_client import OpenAIEmbeddingTransport
from tests.ai.llm.http import Recorder, json_response, mock_http_client

KEY = "sk-test-key-123"


def _embeddings(*vectors: list[float], order: list[int] | None = None) -> object:
    indexes = order if order is not None else list(range(len(vectors)))
    return {
        "object": "list",
        "model": "m",
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in zip(indexes, vectors, strict=True)
        ],
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }


def _transport(
    recorder: Recorder,
    *,
    provider: str = "openai",
    dimensions: int | None = None,
    base_url: str | None = None,
) -> OpenAIEmbeddingTransport:
    client = AsyncOpenAI(
        api_key=KEY, base_url=base_url, max_retries=0, http_client=mock_http_client(recorder)
    )
    return OpenAIEmbeddingTransport(
        client,
        "text-embedding-3-small",
        provider=provider,  # type: ignore[arg-type]
        dimensions=dimensions,
    )


async def test_hosted_request_sends_float_encoding_and_dimensions() -> None:
    recorder = Recorder(json_response(_embeddings([1.0, 2.0], [3.0, 4.0])))

    vectors = await _transport(recorder, dimensions=1024).embed_batch(["a", "b"])

    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    body = recorder.body
    assert body["model"] == "text-embedding-3-small"
    assert body["input"] == ["a", "b"]
    assert body["encoding_format"] == "float"
    assert body["dimensions"] == 1024
    assert recorder.requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert str(recorder.requests[0].url) == "https://api.openai.com/v1/embeddings"


async def test_compatible_request_omits_dimensions_and_uses_the_base_url() -> None:
    recorder = Recorder(json_response(_embeddings([1.0])))
    transport = _transport(
        recorder, provider="openai_compatible", base_url="http://localhost:11434/v1"
    )

    await transport.embed_batch(["a"])

    assert "dimensions" not in recorder.body
    assert str(recorder.requests[0].url) == "http://localhost:11434/v1/embeddings"
    assert transport.provider == "openai_compatible"
    assert transport.model == "text-embedding-3-small"


async def test_results_are_put_back_in_input_order_by_index() -> None:
    recorder = Recorder(json_response(_embeddings([2.0], [1.0], [0.0], order=[2, 1, 0])))

    vectors = await _transport(recorder).embed_batch(["a", "b", "c"])

    assert vectors == [[0.0], [1.0], [2.0]]


@pytest.mark.parametrize("status", [401, 403])
async def test_credential_failures_are_auth_errors(status: int) -> None:
    recorder = Recorder(json_response({"error": {"message": f"bad {KEY}"}}, status))

    with pytest.raises(EmbeddingAuthError) as exc_info:
        await _transport(recorder).embed_batch(["SECRET-TEXT"])

    assert KEY not in str(exc_info.value)
    assert "SECRET-TEXT" not in str(exc_info.value)


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_rate_limits_and_server_errors_are_transient(status: int) -> None:
    recorder = Recorder(json_response({"error": {"message": "busy"}}, status, {"retry-after": "2"}))

    with pytest.raises(EmbeddingTransientError) as exc_info:
        await _transport(recorder).embed_batch(["a"])

    assert exc_info.value.retry_after == 2.0


async def test_connection_problems_are_transient_and_timeouts_are_timeouts() -> None:
    with pytest.raises(EmbeddingTransientError):
        await _transport(Recorder(httpx2.ConnectError("refused"))).embed_batch(["a"])
    with pytest.raises(EmbeddingTimeoutError):
        await _transport(Recorder(httpx2.ReadTimeout("slow"))).embed_batch(["a"])


async def test_other_rejections_are_a_general_error_with_only_the_status() -> None:
    recorder = Recorder(json_response({"error": {"message": "model not found"}}, 404))

    with pytest.raises(EmbeddingError) as exc_info:
        await _transport(recorder).embed_batch(["a"])

    assert type(exc_info.value) is EmbeddingError
    assert str(exc_info.value) == "The provider rejected the request (status 404)"
