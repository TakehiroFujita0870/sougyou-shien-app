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


def test_separates_three_competitor_categories_potential_risk_and_owner_judgments() -> None:
    api = client()
    payload = report_payload()
    payload.update({
        "competitors": [
            {"id": "direct-1", "name": "直接社", "category": "direct", "comparison_axis": "導入速度", "evidence_ids": ["web-1"]},
            {"id": "indirect-1", "name": "代替予算社", "category": "indirect", "comparison_axis": "費用", "evidence_ids": ["web-2"]},
            {"id": "alternative-1", "name": "手作業", "category": "alternative", "comparison_axis": "運用負担", "evidence_ids": ["web-3"]},
        ],
        "potential_entrant_risks": [{"description": "大手参入", "evidence_ids": ["web-2"]}],
        "owner_judgments": [{"kind": "winning_move", "statement": "現場入力を最短化する", "evidence_ids": ["web-1"]}, {"kind": "opportunity", "statement": "小規模工場から始める", "evidence_ids": []}],
    })
    response = api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert [item["category"] for item in body["competitors"]] == ["direct", "indirect", "alternative"]
    assert body["potential_entrant_risks"][0]["description"] == "大手参入"
    assert [item["kind"] for item in body["owner_judgments"]] == ["winning_move", "opportunity"]
    assert body["evidence"] == body["supporting_evidence"] + body["counter_evidence"] + [{"id": "web-3", "locator": "https://example.test/unknown", "excerpt": "対象社数は未調査", "classification": "unverified"}]
    assert all("owner_judgments" not in item for item in body["evidence"])


def test_rejects_potential_competitor_category_and_unknown_evidence_reference() -> None:
    api = client()
    payload = report_payload()
    payload["competitors"] = [{"id": "bad", "name": "潜在", "category": "potential", "comparison_axis": "参入", "evidence_ids": []}]
    assert api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=payload).status_code == 422
    payload["competitors"] = [{"id": "direct", "name": "直接", "category": "direct", "comparison_axis": "価格", "evidence_ids": ["missing"]}]
    assert api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=payload).status_code == 422
