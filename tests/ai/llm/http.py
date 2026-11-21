"""Mock the HTTP layer under the real SDKs (both use httpx2) so request building, response parsing
and error mapping are exercised without a network."""

import json
from collections.abc import Callable
from typing import Any

import httpx2

Handler = Callable[[httpx2.Request], httpx2.Response]


class Recorder:
    """An HTTP handler that records requests and answers with the scripted responses in order."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self._responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def body(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.requests[-1].content)
        return loaded


def mock_http_client(handler: Handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def json_response(
    payload: object, status: int = 200, headers: dict[str, str] | None = None
) -> httpx2.Response:
    return httpx2.Response(status, json=payload, headers=headers)
