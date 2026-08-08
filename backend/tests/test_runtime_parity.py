from fastapi.testclient import TestClient

from kadode_api.main import create_app
from kadode_api.runtime import RuntimeProfile, create_runtime


def test_local_profile_reports_all_service_ports_as_fake() -> None:
    client = TestClient(create_app(runtime=create_runtime(RuntimeProfile.LOCAL)))

    response = client.get("/v1/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["profile"] == "local"
    assert {item["service"] for item in body["services"]} == {"auth", "db", "storage", "ai", "web_search", "billing"}
    assert {item["connection"] for item in body["services"]} == {"fake"}


def test_fake_auth_success_and_cross_owner_access_is_denied() -> None:
    client = TestClient(create_app(runtime=create_runtime(RuntimeProfile.TEST)))

    allowed = client.get("/v1/runtime/objects/sample-object", headers={"X-Local-Owner-Id": "local-user"})
    denied = client.get("/v1/runtime/objects/sample-object", headers={"X-Local-Owner-Id": "other-user"})

    assert allowed.status_code == 200
    assert allowed.json()["owner_id"] == "local-user"
    assert denied.status_code == 403
    assert denied.json()["detail"] == {"code": "access_denied", "message": "You do not have access to this resource."}


def test_fake_billing_limit_and_ai_timeout_are_recoverable_contract_errors() -> None:
    client = TestClient(create_app(runtime=create_runtime(RuntimeProfile.LOCAL)))
    headers = {"X-Local-Owner-Id": "local-user"}

    assert client.post("/v1/runtime/billing/consume", headers=headers).status_code == 200
    limit = client.post("/v1/runtime/billing/consume", headers=headers)
    timeout = client.post("/v1/runtime/ai", headers=headers, json={"prompt": "simulate timeout"})

    assert limit.status_code == 429
    assert limit.json()["detail"] == {"code": "usage_limit_exceeded", "message": "Your local usage limit has been reached."}
    assert timeout.status_code == 504
    assert timeout.json()["detail"] == {"code": "service_timeout", "message": "The service timed out. Please retry."}


def test_fake_delete_makes_owned_object_unavailable() -> None:
    client = TestClient(create_app(runtime=create_runtime(RuntimeProfile.LOCAL)))
    headers = {"X-Local-Owner-Id": "local-user"}

    deleted = client.delete("/v1/runtime/objects/sample-object", headers=headers)
    missing = client.get("/v1/runtime/objects/sample-object", headers=headers)

    assert deleted.status_code == 200
    assert deleted.json()["state"] == "deleted"
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "resource_not_found", "message": "The resource does not exist."}


def test_unconfigured_production_is_an_explicit_connection_state() -> None:
    client = TestClient(create_app(runtime=create_runtime(RuntimeProfile.PRODUCTION)))

    response = client.get("/v1/runtime/status")

    assert response.status_code == 200
    assert {item["connection"] for item in response.json()["services"]} == {"unconfigured"}
    assert {item["message"] for item in response.json()["services"]} == {"external connection is not configured"}
