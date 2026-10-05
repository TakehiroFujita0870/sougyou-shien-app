import pytest

from nebula.graph_job_coverage import project_coverage


def test_coverage_uses_current_revision_and_restored_lineage_without_bodies():
    home = {"status": "ready", "ideas": [
        {"id": "restored", "brief_revision": 2}, {"id": "empty", "brief_revision": 1},
        {"id": "draft"},
    ]}
    payloads = {"restored": {"supersedes_id": "root", "description": "PRIVATE"},
                "root": {}, "empty": {}}
    briefs = [{"root_id": "root", "id": "old", "revision": 1},
              {"root_id": "root", "id": "new", "revision": 2},
              {"root_id": "empty", "id": "empty-brief", "revision": 1}]
    jobs = [{"brief_id": "old", "state": "succeeded", "manifest": "[]"},
            {"brief_id": "empty-brief", "state": "succeeded", "manifest": "[]"}]
    result = project_coverage(home, payloads, briefs, jobs, limit=1)
    assert result["reports_checked"] == 2 and result["truncated"]
    assert result["issues"] == [{"idea_id": "restored", "brief_id": "new",
                                 "state": "missing", "action": "missing_job",
                                 "existing_relation_count": 0}]
    assert "PRIVATE" not in str(result)
    assert jobs[1]["state"] == "succeeded"
    full = project_coverage(home, payloads, briefs, jobs)
    assert full["issues"][1]["action"] == "reviewed_without_candidates"


def test_coverage_rejects_invalid_bounds_and_unresolved_home():
    for limit in (0, 21, True):
        with pytest.raises(ValueError):
            project_coverage({"status": "ready", "ideas": []}, {}, [], [], limit=limit)
    with pytest.raises(ValueError):
        project_coverage({"status": "unavailable"}, {}, [], [])


def test_existing_manual_relations_are_not_reported_as_missing_graph_data():
    relation = {"based_on_brief_id": "current", "status": "proposed", "source_id": "idea",
                "target_id": "asset", "predicate": "REUSES", "private_quote": "PRIVATE"}
    result = project_coverage(
        {"status": "ready", "ideas": [{"id": "idea", "brief_revision": 2}]}, {"idea": {}},
        [{"root_id": "idea", "id": "current", "revision": 2}], [],
        manual_relations=(relation, relation, relation | {"status": "retracted"},
                          relation | {"based_on_brief_id": "old", "target_id": "old-asset"}),
    )
    assert result["issues"][0]["action"] == "manual_relations_without_job"
    assert result["issues"][0]["existing_relation_count"] == 1
    assert "PRIVATE" not in str(result)
