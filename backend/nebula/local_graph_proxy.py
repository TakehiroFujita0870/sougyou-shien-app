"""Read-only, fixed-destination proxy for the existing local Graph search route."""
from __future__ import annotations

import asyncio
import ipaddress
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request as UrlRequest, build_opener

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

GRAPH_SEARCH_URL = "http://127.0.0.1:8000/v1/founder-graph/mcp/read/search"
# The local embedding model may load on the first search after service start.
# Keep the read bounded without treating ordinary cold start as an outage.
GRAPH_SEARCH_TIMEOUT_SECONDS = 15.0
GRAPH_OWNER_ID = "owner-mvp"
_LOOPBACK_OPENER = build_opener(ProxyHandler({}))


@dataclass(frozen=True, slots=True)
class ProxyResponse:
    status_code: int
    body: object


Transport = Callable[[str, Mapping[str, str], Mapping[str, object], float], ProxyResponse]


class GraphSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=512)
    limit: int = Field(default=20, ge=1, le=20)


class LocalGraphSearchProxy:
    """Forward only validated search input to one fixed loopback destination."""

    def __init__(self, *, transport: Transport | None = None) -> None:
        self._transport = transport or _post_json

    def search(self, query: str, limit: int) -> ProxyResponse:
        response = self._transport(
            GRAPH_SEARCH_URL,
            {"Content-Type": "application/json", "X-Local-Owner-Id": GRAPH_OWNER_ID},
            {"query": query, "limit": limit},
            GRAPH_SEARCH_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            code = "unavailable" if response.status_code in {503, 504} else "upstream_error"
            raise HTTPException(status_code=503 if code == "unavailable" else 502, detail={"code": code})
        if not isinstance(response.body, dict) or not isinstance(response.body.get("results"), list):
            raise HTTPException(status_code=502, detail={"code": "upstream_error"})
        return response


def create_local_graph_search_router(
    proxy: LocalGraphSearchProxy,
    *,
    expected_host: str,
    allowed_origin: str,
) -> APIRouter:
    """Create a single local POST search route; no writes or variable paths."""
    if not expected_host or not allowed_origin:
        raise ValueError("expected_host and allowed_origin are required")
    router = APIRouter()

    @router.post("/v1/founder-graph/mcp/read/search")
    async def search_graph(payload: GraphSearchRequest, request: Request) -> object:
        peer = request.client.host if request.client else ""
        try:
            loopback = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            loopback = False
        if not loopback or request.headers.get("host") != expected_host:
            raise HTTPException(status_code=403, detail={"code": "local_only"})
        if request.headers.get("origin") != allowed_origin:
            raise HTTPException(status_code=403, detail={"code": "invalid_origin"})
        result = await asyncio.to_thread(proxy.search, payload.query, payload.limit)
        return result.body

    return router


def _post_json(url: str, headers: Mapping[str, str], payload: Mapping[str, object], timeout: float) -> ProxyResponse:
    request = UrlRequest(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with _LOOPBACK_OPENER.open(request, timeout=timeout) as response:
            return ProxyResponse(response.status, json.loads(response.read()))
    except HTTPError as error:
        return ProxyResponse(error.code, None)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return ProxyResponse(503, None)
