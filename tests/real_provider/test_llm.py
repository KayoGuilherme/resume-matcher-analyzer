import pytest
from pydantic import BaseModel

from app.ai.llm import LLMClient, LLMTransientError

pytestmark = pytest.mark.real_provider


class Capital(BaseModel):
    country: str
    city: str


async def test_a_small_structured_request_validates(real_llm: LLMClient) -> None:
    try:
        result = await real_llm.generate_structured(
            "What is the capital of France? Answer with the country and the city.", Capital
        )
    except LLMTransientError as error:
        pytest.skip(f"the configured provider is not reachable or is rate limiting: {error}")

    assert isinstance(result, Capital)
    assert "paris" in result.city.lower()
