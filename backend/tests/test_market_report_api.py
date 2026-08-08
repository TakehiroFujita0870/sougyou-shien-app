from fastapi.testclient import TestClient

from kadode_api.main import create_app
from kadode_api.market_report import InMemoryMarketReportRepository


def client() -> TestClient:
    return TestClient(create_app(market_report_repository=InMemoryMarketReportRepository()))


def report_payload() -> dict[str, object]:
    return {
        "idea_id": "idea-repair-log",
        "idea_title": "設備保全の記録支援",
        "evidence": [
            {"id": "web-1", "locator": "https://example.test/need", "excerpt": "記録作業の負担が課題", "classification": "supporting"},
            {"id": "web-2", "locator": "https://example.test/risk", "excerpt": "導入コストが懸念", "classification": "counter"},
            {"id": "web-3", "locator": "https://example.test/unknown", "excerpt": "対象社数は未調査", "classification": "unverified"},
        ],
        "past_decisions": [
            {"decision": "現場の入力負担を下げる", "rationale": "既存ツールとの差別化に必要", "status": "active"}
        ],
    }


def test_generates_separated_deterministic_report_without_framework_headings() -> None:
    api = client()
    first = api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=report_payload())
    second = api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=report_payload())

    assert first.status_code == 201
    body = first.json()
    assert body["market_outlook"]["heading"] == "市場の見込み"
    assert body["competitive_difference"]["heading"] == "競合との違い"
    assert body["opportunity_focus"]["heading"] == "攻めどころの特定"
    assert "SWOT" not in str(body)
    assert [item["id"] for item in body["supporting_evidence"]] == ["web-1"]
    assert [item["id"] for item in body["counter_evidence"]] == ["web-2"]
    assert body["unverified_items"] == ["対象社数は未調査"]
    assert body["card_update"]["status"] == "proposed"
    assert second.json()["market_outlook"] == body["market_outlook"]


def test_card_update_is_observable_before_and_after_owner_approval() -> None:
    api = client()
    created = api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=report_payload()).json()

    before = api.get(f"/v1/market-reports/{created['id']}", headers={"X-Local-Owner-Id": "owner-a"})
    approved = api.post(f"/v1/market-reports/{created['id']}/card-update/approve", headers={"X-Local-Owner-Id": "owner-a"})
    after = api.get(f"/v1/market-reports/{created['id']}", headers={"X-Local-Owner-Id": "owner-a"})

    assert before.json()["card_update"]["status"] == "proposed"
    assert approved.json()["card_update"]["status"] == "approved"
    assert after.json()["card_update"]["approved_at"] is not None


def test_other_owner_cannot_read_or_approve_report() -> None:
    api = client()
    created = api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=report_payload()).json()

    read = api.get(f"/v1/market-reports/{created['id']}", headers={"X-Local-Owner-Id": "owner-b"})
    approve = api.post(f"/v1/market-reports/{created['id']}/card-update/approve", headers={"X-Local-Owner-Id": "owner-b"})

    assert read.status_code == 404
    assert read.json()["detail"] == {"code": "market_report_not_found"}
    assert approve.status_code == 404
