from __future__ import annotations

from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.founder_graph_mcp import McpReadSurface
from dots.founder_graph_neo4j_idea_brief import _serialize_persisted_idea_brief
from dots.local_home import read_local_home
from dots.source_citations import citation_metadata, researched_evidence_ids


def test_citation_metadata_keeps_public_query_and_fragment_but_rejects_credentials_and_secret_params():
    assert citation_metadata({"locator": "https://example.test/article?id=7#overview", "title": " Public title "}) == {
        "url": "https://example.test/article?id=7#overview", "title": "Public title",
    }
    assert citation_metadata({"locator": "https://user:pass@example.test/article", "title": "Title"}) is None
    assert citation_metadata({"locator": "https://example.test/article?access_token=secret", "title": "Title"}) is None
    assert citation_metadata({"locator": "https://example.test/article?refresh_token=secret", "title": "Title"}) is None
    assert citation_metadata({"locator": "https://example.test/article?X-Amz-Signature=secret", "title": "Title"}) is None
    assert citation_metadata({"locator": "https://example.test/share?rlkey=secret", "title": "Title"}) is None
    assert citation_metadata({"locator": "https://example.test/article", "title": "   "}) is None


def test_researched_evidence_ids_requires_eight_sections_and_collects_unique_refs():
    sections = tuple(
        IdeaBriefSection(index=index, content=f"Synthetic section {index}", evidence_ids=(("ev-1",) if index == 0 else ()))
        for index in range(8)
    )
    assert researched_evidence_ids(sections) == ("ev-1",)
    assert researched_evidence_ids(sections[:7]) == ()
    assert researched_evidence_ids(tuple(IdeaBriefSection(index=i, content="x") for i in range(8))) == ()


def test_mcp_fetch_projects_only_citation_contract_fields():
    citation = {
        "url": "https://example.test/source?id=1#overview", "title": "Synthetic source",
        "source_id": "source-1", "evidence_id": "evidence-1", "excerpt": "MUST NOT LEAK",
    }

    class Reader:
        def fetch_idea_brief(self, idea_id, *, owner_id):
            assert owner_id == "owner-1"
            return {
                "brief_id": "brief-1", "idea_id": idea_id,
                "sections": [
                    {"index": index, "content": f"Synthetic section {index}", "evidence_ids": ["evidence-1"] if index == 0 else [], "citations": [citation] if index == 0 else []}
                    for index in range(8)
                ],
                "brief_citations": [[citation], *([[] for _ in range(7)])],
            }

    result = McpReadSurface(Reader()).call("fetch_idea_brief", {"idea_id": "idea-1"}, owner_id="owner-1")
    assert result["brief_citations"][0] == [{
        "url": citation["url"], "title": citation["title"],
        "source_id": "source-1", "evidence_id": "evidence-1",
    }]
    assert result["sections"][0]["evidence_ids"] == ["evidence-1"]
    assert "MUST NOT LEAK" not in str(result)


class HomeStore:
    def __init__(self, brief: IdeaBriefVersion, citation_map):
        self.brief = brief
        self.citation_map = citation_map

    def read_home(self, owner_id):
        return ({
            "id": "idea-1", "owner_id": owner_id, "node_type": "idea", "status": "draft",
            "payload_json": '{"id":"idea-1","owner_id":"owner-1","title":"Synthetic","status":"draft","created_at":"2026-09-27T00:00:00Z"}',
        },)

    def read_briefs(self, _owner_id):
        record = _serialize_persisted_idea_brief(self.brief)
        return ({
            "id": self.brief.id, "owner_id": self.brief.owner_id,
            "root_id": self.brief.idea_lineage_root_id, "revision": self.brief.revision,
            "supersedes_id": self.brief.supersedes_id, "payload_json": record["payload_json"],
        },)

    def read_citations(self, _owner_id, evidence_ids):
        return {key: self.citation_map[key] for key in evidence_ids if key in self.citation_map}


def test_home_projects_eight_chapter_citations_and_distinguishes_missing_sources():
    sections = tuple(
        IdeaBriefSection(index=index, content=f"Synthetic section {index}", evidence_ids=(("ev-1",) if index == 0 else ()))
        for index in range(8)
    )
    brief = IdeaBriefVersion(
        owner_id="owner-1", idea_lineage_root_id="idea-1", based_on_idea_id="idea-1",
        sections=sections, research_run_ids=("run-synthetic",), id="brief-synthetic",
    )
    public = {"ev-1": {"url": "https://example.test/source?id=1", "title": "Synthetic source"}}

    result = read_local_home(HomeStore(brief, public), owner_id="owner-1")

    assert result["ideas"][0]["research_status"] == "researched"
    assert len(result["ideas"][0]["brief_citations"]) == 8
    assert result["ideas"][0]["brief_citations"][0] == [public["ev-1"]]
    assert result["ideas"][0]["brief_citations"][1:] == [[] for _ in range(7)]

    missing = read_local_home(HomeStore(brief, {}), owner_id="owner-1")
    assert missing["ideas"][0]["research_status"] == "research_sources_missing"
