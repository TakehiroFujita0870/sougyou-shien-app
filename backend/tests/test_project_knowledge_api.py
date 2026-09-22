from fastapi.testclient import TestClient

from dots.main import create_app
from dots.project_knowledge import InMemoryProjectKnowledgeRepository


def client() -> TestClient:
    return TestClient(create_app(project_knowledge_repository=InMemoryProjectKnowledgeRepository()))


def headers(owner_id: str) -> dict[str, str]:
    return {"X-Local-Owner-Id": owner_id}


def create_knowledge(api: TestClient, owner_id: str = "owner-a") -> dict[str, object]:
    response = api.post(
        "/v1/project-knowledge",
        headers=headers(owner_id),
        json={
            "source_project_id": "project-source",
            "source_type": "anonymized_customer_interview_derivative",
            "source_id": "derived-interview-1",
            "anonymized_content": "工場の保全記録を短時間で共有したいという需要。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def grant(api: TestClient, knowledge_id: str, owner_id: str = "owner-a") -> dict[str, object]:
    response = api.post(
        "/v1/project-knowledge/grants",
        headers=headers(owner_id),
        json={
            "knowledge_id": knowledge_id,
            "source_project_id": "project-source",
            "target_project_id": "project-target",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_only_anonymized_derivatives_can_be_granted_and_candidates_exclude_other_owners() -> None:
    api = client()
    knowledge = create_knowledge(api)
    grant(api, knowledge["id"])

    candidates = api.get("/v1/project-knowledge/candidates", headers=headers("owner-a"), params={"target_project_id": "project-target"})
    assert candidates.status_code == 200
    assert candidates.json()["candidates"] == [{
        "knowledge_id": knowledge["id"],
        "source_project_id": "project-source",
        "target_project_id": "project-target",
        "content": "工場の保全記録を短時間で共有したいという需要。",
    }]

    other_owner = api.get("/v1/project-knowledge/candidates", headers=headers("owner-b"), params={"target_project_id": "project-target"})
    assert other_owner.status_code == 200
    assert other_owner.json() == {"candidates": []}

    raw = api.post(
        "/v1/project-knowledge",
        headers=headers("owner-a"),
        json={"source_project_id": "project-source", "source_type": "raw_customer_interview", "source_id": "raw-1", "anonymized_content": "氏名を含む原文"},
    )
    assert raw.status_code == 422


def test_revoke_and_delete_exclude_new_candidates_and_mark_existing_references_unavailable() -> None:
    api = client()
    knowledge = create_knowledge(api)
    granted = grant(api, knowledge["id"])

    revoked = api.post(f"/v1/project-knowledge/grants/{granted['id']}/revoke", headers=headers("owner-a"))
    assert revoked.status_code == 200
    assert api.get("/v1/project-knowledge/candidates", headers=headers("owner-a"), params={"target_project_id": "project-target"}).json() == {"candidates": []}
    assert api.get(f"/v1/project-knowledge/references/{knowledge['id']}", headers=headers("owner-a"), params={"target_project_id": "project-target"}).json() == {"status": "unavailable"}

    second_grant = grant(api, knowledge["id"])
    assert second_grant["revoked_at"] is None
    deleted = api.delete(f"/v1/project-knowledge/{knowledge['id']}", headers=headers("owner-a"))
    assert deleted.status_code == 204
    assert api.get("/v1/project-knowledge/candidates", headers=headers("owner-a"), params={"target_project_id": "project-target"}).json() == {"candidates": []}
    assert api.get(f"/v1/project-knowledge/references/{knowledge['id']}", headers=headers("owner-a"), params={"target_project_id": "project-target"}).json() == {"status": "unavailable"}


def test_owner_is_authenticated_and_not_accepted_from_the_request_body() -> None:
    api = client()
    knowledge = create_knowledge(api, "owner-a")
    stolen = api.post(
        "/v1/project-knowledge/grants",
        headers=headers("owner-b"),
        json={
            "owner_id": "owner-a",
            "knowledge_id": knowledge["id"],
            "source_project_id": "project-source",
            "target_project_id": "project-target",
        },
    )
    assert stolen.status_code == 404
    assert "owner_id" not in knowledge
