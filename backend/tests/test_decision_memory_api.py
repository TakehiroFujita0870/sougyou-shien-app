from fastapi.testclient import TestClient

from kadode_api.decision_memory import InMemoryDecisionRepository
from kadode_api.main import create_app


def client() -> TestClient:
    return TestClient(create_app(InMemoryDecisionRepository()))


def owner_headers(owner_id: str) -> dict[str, str]:
    return {"X-Local-Owner-Id": owner_id}


def create_decision(client: TestClient, owner_id: str, **overrides: object) -> dict[str, object]:
    payload = {
        "idea_id": "idea-maintenance",
        "decision": "設備保全の記録を継続する",
        "rationale": "復旧時間を短縮するため、故障記録を残す。",
        "valid_from": "2026-08-01T00:00:00Z",
        "status": "active",
        "observations": [
            {
                "observation": "保全担当者は記録の検索に時間を使っている。",
                "disposition": "accepted",
                "evidence_id": "evidence-maintenance",
            }
        ],
    }
    payload.update(overrides)
    response = client.post("/v1/decisions", headers=owner_headers(owner_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_saves_and_searches_a_previous_decision_with_its_reason_and_evidence() -> None:
    api = client()
    saved = create_decision(api, "owner-a")

    response = api.get(
        "/v1/decisions/search",
        headers=owner_headers("owner-a"),
        params={"idea_id": "idea-maintenance", "query": "復旧時間"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "decisions": [
            {
                **saved,
                "observations": [
                    {
                        "observation": "保全担当者は記録の検索に時間を使っている。",
                        "disposition": "accepted",
                        "evidence_id": "evidence-maintenance",
                    }
                ],
            }
        ]
    }
    assert "owner_id" not in saved


def test_search_keeps_new_evidence_for_reconsideration_visible() -> None:
    api = client()
    create_decision(
        api,
        "owner-a",
        observations=[
            {
                "observation": "新しい故障率の計測結果が前提を変えた。",
                "disposition": "reconsider",
                "evidence_id": "evidence-new-failure-rate",
            }
        ],
    )

    response = api.get(
        "/v1/decisions/search",
        headers=owner_headers("owner-a"),
        params={"idea_id": "idea-maintenance", "query": "故障率"},
    )

    assert response.status_code == 200
    observation = response.json()["decisions"][0]["observations"][0]
    assert observation["disposition"] == "reconsider"
    assert observation["evidence_id"] == "evidence-new-failure-rate"


def test_search_returns_expired_decisions_instead_of_hiding_them() -> None:
    api = client()
    create_decision(
        api,
        "owner-a",
        decision="旧価格で提供する",
        rationale="旧価格は初期顧客への検証に使った。",
        status="expired",
    )

    response = api.get(
        "/v1/decisions/search",
        headers=owner_headers("owner-a"),
        params={"idea_id": "idea-maintenance", "query": "旧価格"},
    )

    assert response.status_code == 200
    assert response.json()["decisions"][0]["status"] == "expired"


def test_saves_a_successor_link_for_the_same_owner_and_idea() -> None:
    api = client()
    previous = create_decision(api, "owner-a")
    successor = create_decision(
        api,
        "owner-a",
        decision="記録対象を更新する",
        rationale="前回判断を残し、計測対象を追加する。",
        supersedes_id=previous["id"],
    )

    assert successor["supersedes_id"] == previous["id"]


def test_rejects_cross_owner_search_and_supersession_without_revealing_the_record() -> None:
    api = client()
    owner_a_decision = create_decision(api, "owner-a")

    search = api.get(
        "/v1/decisions/search",
        headers=owner_headers("owner-b"),
        params={"idea_id": "idea-maintenance", "query": "復旧時間"},
    )
    assert search.status_code == 200
    assert search.json() == {"decisions": []}

    payload = {
        "idea_id": "idea-maintenance",
        "decision": "別の判断を保存する",
        "rationale": "別ユーザーの記録へ後継関係を作らない。",
        "valid_from": "2026-08-02T00:00:00Z",
        "status": "active",
        "supersedes_id": owner_a_decision["id"],
        "observations": [],
    }
    supersession = api.post("/v1/decisions", headers=owner_headers("owner-b"), json=payload)
    assert supersession.status_code == 404
    assert supersession.json() == {"detail": {"code": "decision_not_found"}}


def test_requires_the_local_owner_context() -> None:
    response = client().get("/v1/decisions/search", params={"idea_id": "idea-maintenance", "query": "復旧時間"})

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "local_owner_required"}}
