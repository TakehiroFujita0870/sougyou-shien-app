from fastapi.testclient import TestClient

from kadode_api.account_privacy import InMemoryAccountPrivacyRepository
from kadode_api.main import create_app


def client() -> TestClient:
    return TestClient(create_app(account_privacy_repository=InMemoryAccountPrivacyRepository.seeded()))


def headers(owner_id: str) -> dict[str, str]:
    return {"X-Local-Owner-Id": owner_id}


def test_export_returns_only_the_owners_profile_ideas_documents_research_and_decisions_in_json_and_markdown() -> None:
    response = client().get("/v1/account/export", headers=headers("owner-a"))

    assert response.status_code == 200
    exported = response.json()
    assert exported["json"]["profile"]["display_name"] == "owner-a profile"
    assert exported["json"]["ideas"][0]["id"] == "idea-a"
    assert exported["json"]["documents"][0]["id"] == "document-a"
    assert exported["json"]["research"][0]["id"] == "research-a"
    assert exported["json"]["decisions"][0]["id"] == "decision-a"
    assert "owner-b" not in str(exported)
    assert "# Kadode data export" in exported["markdown"]
    assert "owner-a profile" in exported["markdown"]


def test_deletion_manifest_excludes_every_owned_document_artifact_and_returns_a_completed_audit() -> None:
    api = client()
    response = api.post("/v1/account/deletion", headers=headers("owner-a"))

    assert response.status_code == 202
    deleted = response.json()
    targets = {item["artifact_type"] for item in deleted["manifest"]["items"]}
    assert {"original", "extracted_text", "embedding", "search_index"} <= targets
    assert {item["state"] for item in deleted["audit"]["items"]} == {"excluded"}

    after = api.get("/v1/account/export", headers=headers("owner-a"))
    assert after.status_code == 200
    assert after.json()["json"] == {"profile": None, "ideas": [], "documents": [], "research": [], "decisions": []}


def test_deletion_does_not_disclose_or_change_another_owners_data() -> None:
    api = client()
    before = api.get("/v1/account/export", headers=headers("owner-b")).json()

    deleted = api.post("/v1/account/deletion", headers=headers("owner-a"))
    after = api.get("/v1/account/export", headers=headers("owner-b")).json()

    assert deleted.status_code == 202
    assert "owner-b" not in str(deleted.json())
    assert after == before


def test_export_and_deletion_require_the_local_owner_context() -> None:
    api = client()

    assert api.get("/v1/account/export").status_code == 401
    assert api.post("/v1/account/deletion").status_code == 401
