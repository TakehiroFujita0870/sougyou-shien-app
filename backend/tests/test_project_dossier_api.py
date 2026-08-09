from fastapi.testclient import TestClient

from kadode_api.main import create_app
from kadode_api.market_report import InMemoryMarketReportRepository


def client() -> TestClient:
    return TestClient(create_app(market_report_repository=InMemoryMarketReportRepository()))


def market_payload() -> dict[str, object]:
    return {
        "idea_id": "project-1",
        "idea_title": "記録支援",
        "evidence": [
            {"id": "e-support", "locator": "local:research#1", "excerpt": "記録作業の負担", "classification": "supporting"},
            {"id": "e-counter", "locator": "local:research#2", "excerpt": "導入費用の懸念", "classification": "counter"},
        ],
        "past_decisions": [{"decision": "入力を短縮する", "rationale": "負担を下げる", "status": "active"}],
        "competitors": [{"id": "direct", "name": "既存製品", "category": "direct", "comparison_axis": "入力速度", "evidence_ids": ["e-support"]}],
        "owner_judgments": [{"kind": "winning_move", "statement": "現場入力を短縮する", "evidence_ids": ["e-support"]}],
    }


def dossier_payload(report_id: str | None) -> dict[str, object]:
    return {
        "project_id": "project-1",
        "business_definition": {
            "facts": [{"source_id": "idea-1", "locator": "local:idea-1", "summary": "設備保全の記録を支援する"}],
            "ai_inference": ["記録負担を検証する仮説"],
            "owner_decisions": [{"statement": "小規模工場から始める", "source_ids": ["idea-1"]}],
        },
        "market_report_id": report_id,
        "unit_economics_scenarios": [
            {"name": name, "price": {"amount": "1000", "currency": "JPY"}, "variable_cost": {"amount": "400", "currency": "JPY"}, "cac": {"amount": "300", "currency": "JPY"}, "fixed_cost": {"amount": "6000", "currency": "JPY"}, "sales_units": units, "capacity_units": 30, "retention_periods": 4, "period_months": 1}
            for name, units in (("base", 20), ("upside", 25), ("downside", 10))
        ],
        "execution_plan": {"weekly_hours_limit": "8", "weekly_hours_committed": "4", "household_fund_limit": "30000", "planned_spend": "10000", "currency": "JPY", "constraint_categories": ["employee", "weekend_only"], "small_experiment": {"title": "週末検証", "weekly_hours": "2", "spend": "5000", "reversible": True}, "withdrawal_condition": "上限で停止", "required_resources": ["prototype"], "roadmap_steps": ["validate"], "unit_economics_operating_profit": "6000"},
    }


def test_assembles_five_questions_with_separated_evidence_and_existing_calculations() -> None:
    api = client()
    report = api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=market_payload()).json()
    response = api.post("/v1/projects/project-1/dossier", headers={"X-Local-Owner-Id": "owner-a"}, json=dossier_payload(report["id"]))
    repeated = api.post("/v1/projects/project-1/dossier", headers={"X-Local-Owner-Id": "owner-a"}, json=dossier_payload(report["id"]))

    assert response.status_code == 200, response.text
    assert repeated.json() == response.json()
    body = response.json()
    assert [section["question"] for section in body["sections"]] == ["どんな事業", "市場はある", "競合は誰", "利益はでる", "実現できる"]
    assert body["sections"][1]["facts"][0]["locator"] == "local:research#1"
    assert body["sections"][2]["owner_decisions"] == [{"statement": "現場入力を短縮する", "source_ids": ["e-support"]}]
    assert body["contradictory_evidence"] == [{"source_id": "e-counter", "locator": "local:research#2", "summary": "導入費用の懸念"}]
    assert body["sections"][3]["facts"][0]["source_id"] == "unit-economics:base"
    assert body["sections"][4]["facts"][0]["source_id"] == "execution-plan"
    assert body["source_freshness"]["market_report"] == {"status": "unconfirmed", "source_ids": ["e-support", "e-counter"], "reason": "source_update_time_unavailable"}
    assert body["source_freshness"]["unit_economics"]["source_ids"] == ["unit-economics:base", "unit-economics:upside", "unit-economics:downside"]
    assert "bank" not in str(body).lower()


def test_marks_missing_sections_unconfirmed_without_fabricating_values() -> None:
    api = client()
    response = api.post("/v1/projects/project-1/dossier", headers={"X-Local-Owner-Id": "owner-a"}, json={"project_id": "project-1"})

    assert response.status_code == 200
    body = response.json()
    assert [section["status"] for section in body["sections"]] == ["unconfirmed"] * 5
    assert body["source_freshness"]["market_report"] == {"status": "missing", "source_ids": [], "reason": "market_report_missing"}
    assert body["sections"][1]["missing_reasons"] == ["market_report_missing"]


def test_rejects_cross_owner_market_report_and_missing_principal() -> None:
    api = client()
    report = api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=market_payload()).json()
    foreign = api.post("/v1/projects/project-1/dossier", headers={"X-Local-Owner-Id": "owner-b"}, json=dossier_payload(report["id"]))
    anonymous = api.post("/v1/projects/project-1/dossier", json=dossier_payload(None))

    assert foreign.status_code == 404
    assert foreign.json()["detail"] == {"code": "market_report_not_found"}
    assert "e-support" not in foreign.text
    assert anonymous.status_code == 401


def test_rejects_same_owner_report_from_a_different_project() -> None:
    api = client()
    report = api.post("/v1/market-reports", headers={"X-Local-Owner-Id": "owner-a"}, json=market_payload()).json()
    payload = dossier_payload(report["id"])
    payload["project_id"] = "project-2"
    response = api.post("/v1/projects/project-2/dossier", headers={"X-Local-Owner-Id": "owner-a"}, json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "market_report_not_found"}
    assert "e-support" not in response.text


def test_rejects_path_project_id_mismatch() -> None:
    response = client().post("/v1/projects/project-a/dossier", headers={"X-Local-Owner-Id": "owner-a"}, json={"project_id": "project-b"})
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "project_id_mismatch"}
