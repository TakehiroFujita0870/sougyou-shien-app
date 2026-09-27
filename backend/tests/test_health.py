from fastapi.testclient import TestClient
from dots.main import app, create_app

def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_current_api_exposes_only_health_and_founder_graph_mcp() -> None:
    routes = {route.path for route in create_app().routes if route.path == "/health" or route.path.startswith("/v1/")}
    assert routes == {
        "/health",
        "/v1/founder-graph/mcp/tools",
        "/v1/founder-graph/mcp/read/{tool_name}",
        "/v1/founder-graph/mcp/write/{tool_name}",
    }
