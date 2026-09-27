from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dots.local_graph_proxy import (
    GRAPH_SEARCH_TIMEOUT_SECONDS,
    GRAPH_SEARCH_URL,
    LocalGraphSearchProxy,
    ProxyResponse,
    create_local_graph_search_router,
)


def make_client(proxy):
    app = FastAPI()
    app.include_router(create_local_graph_search_router(
        proxy,
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
    ))
    return TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))


def test_uses_fixed_search_url_and_owner_and_returns_search_results():
    calls = []

    def transport(url, headers, payload, timeout):
        calls.append((url, headers, payload, timeout))
        return ProxyResponse(200, {"results": [{"id": "idea-1"}]})

    response = make_client(LocalGraphSearchProxy(transport=transport)).post(
        "/v1/founder-graph/mcp/read/search",
        headers={"Origin": "http://127.0.0.1:8765", "X-Local-Owner-Id": "untrusted"},
        json={"query": "idea", "limit": 5},
    )
    assert response.status_code == 200
    assert response.json() == {"results": [{"id": "idea-1"}]}
    assert calls == [(
        GRAPH_SEARCH_URL,
        {"Content-Type": "application/json", "X-Local-Owner-Id": "owner-mvp"},
        {"query": "idea", "limit": 5},
        GRAPH_SEARCH_TIMEOUT_SECONDS,
    )]


def test_rejects_cross_origin_and_invalid_payload_before_transport():
    calls = []
    client = make_client(LocalGraphSearchProxy(transport=lambda *args: calls.append(args)))
    assert client.post(
        "/v1/founder-graph/mcp/read/search",
        headers={"Origin": "http://evil.example"},
        json={"query": "x"},
    ).status_code == 403
    assert client.post(
        "/v1/founder-graph/mcp/read/search",
        headers={"Origin": "http://127.0.0.1:8765"},
        json={"query": "x" * 513},
    ).status_code == 422
    assert calls == []


def test_sanitizes_upstream_errors_and_rejects_bad_success_shape():
    for upstream in (
        ProxyResponse(503, {"detail": "private internal error"}),
        ProxyResponse(200, {"unexpected": "value"}),
    ):
        response = make_client(LocalGraphSearchProxy(
            transport=lambda *args, result=upstream: result,
        )).post(
            "/v1/founder-graph/mcp/read/search",
            headers={"Origin": "http://127.0.0.1:8765"},
            json={"query": "idea"},
        )
        assert response.status_code in {502, 503}
        assert "private internal error" not in response.text
