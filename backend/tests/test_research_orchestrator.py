from fastapi.testclient import TestClient

from dots.main import app, orchestrator
from dots.research import DailyLimitExceeded, ResearchTimeout
from dots.research_orchestrator import FakeSource, LocatedEvidence, Source


client = TestClient(app)


def configure(**sources: FakeSource) -> None:
    orchestrator.runs.clear()
    orchestrator.sources = {source: sources.get(source.value, FakeSource()) for source in Source}


def test_selected_sources_integrate_locators() -> None:
    configure(web=FakeSource((LocatedEvidence(Source.WEB, "https://example.test", "web"),)),
              document=FakeSource((LocatedEvidence(Source.DOCUMENT, "document:doc-1#page=2", "file"),)))
    response = client.post("/v1/research-runs", headers={"X-Owner-Id": "owner-a"},
                           json={"query": "material", "selected_sources": ["web", "document"]})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert [item["locator"] for item in response.json()["evidence"]] == ["https://example.test", "document:doc-1#page=2"]


def test_partial_timeout_and_daily_limit_keep_available_evidence() -> None:
    configure(web=FakeSource((LocatedEvidence(Source.WEB, "https://example.test", "web"),)),
              patent=FakeSource(error=ResearchTimeout()), decision=FakeSource(error=DailyLimitExceeded()))
    response = client.post("/v1/research-runs", headers={"X-Owner-Id": "owner-a"},
                           json={"query": "material", "selected_sources": ["web", "patent", "decision"]})
    body = response.json()
    assert body["status"] == "partial"
    assert body["source_status"]["patent"] == "timeout: retry the source"
    assert body["source_status"]["decision"] == "limit: retry after 00:00 JST"
    assert len(body["evidence"]) == 1


def test_retry_only_failed_sources_and_preserves_evidence() -> None:
    configure(web=FakeSource((LocatedEvidence(Source.WEB, "https://example.test", "web"),)), patent=FakeSource(error=ResearchTimeout()))
    run = client.post("/v1/research-runs", headers={"X-Owner-Id": "owner-a"}, json={"query": "x", "selected_sources": ["web", "patent"]}).json()
    orchestrator.sources[Source.PATENT] = FakeSource((LocatedEvidence(Source.PATENT, "patent:JP2023-123456A", "official"),))
    retried = client.post(f"/v1/research-runs/{run['id']}/retry", headers={"X-Owner-Id": "owner-a"}).json()
    assert retried["status"] == "completed"
    assert len(retried["evidence"]) == 2


def test_owner_cannot_read_another_local_run() -> None:
    configure()
    run = client.post("/v1/research-runs", headers={"X-Owner-Id": "owner-a"}, json={"query": "x", "selected_sources": ["web"]}).json()
    assert client.get(f"/v1/research-runs/{run['id']}", headers={"X-Owner-Id": "owner-b"}).status_code == 404
