from dataclasses import replace
from types import SimpleNamespace
import json

import pytest

from nebula.founder_graph import Asset, EgressPolicy, Idea, Provenance, Source
from nebula.founder_graph_candidate_job_processor import RelationCandidateJobProcessor
from nebula.founder_graph_mcp import McpReadError
from nebula.founder_graph_read import GraphReadService
from nebula.founder_graph_write import InMemoryGraphWriteService
from nebula.graph_admin_mcp import GraphAdminSurface
from nebula.idea_brief import IdeaBriefVersion


def context(*, allow_delete=False):
    writes = InMemoryGraphWriteService("owner")
    for node in (Idea(id="idea", owner_id="owner", title="倉庫案", egress_policy=EgressPolicy.SHAREABLE),
                 Asset(id="asset", owner_id="owner", name="倉庫", egress_policy=EgressPolicy.SHAREABLE)):
        writes.put_node(node, idempotency_key=node.id)
    brief = IdeaBriefVersion(id="brief", owner_id="owner", idea_lineage_root_id="idea", based_on_idea_id="idea",
        report_markdown="## エグゼクティブサマリー\n\n所有する倉庫を活用する。", egress_policy=EgressPolicy.SHAREABLE)
    writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key="brief")
    processor = RelationCandidateJobProcessor(jobs=SimpleNamespace(owner_id="owner"), writes=writes,
                                            brief_store=writes, worker_id="admin")
    surface = GraphAdminSurface(writes, GraphReadService(writes), processor, allow_delete=allow_delete)
    return writes, brief, surface


def manifest(quote="所有する倉庫を活用する。"):
    return {"idea_id": "idea", "brief_id": "brief", "expected_revision": 1, "candidates": [{
        "source_id": "idea", "target_id": "asset", "predicate": "REUSES", "basis": "brief_hypothesis",
        "support": {"quote": quote}, "evidence_ids": []}]}


def call(surface, tool, arguments):
    return surface.call(tool, arguments, owner_id="owner")


def request(surface, operations, key="cleanup", **extra):
    return {"snapshot_id": call(surface, "audit_graph", {})["snapshot_id"],
            "operations": operations, "idempotency_key": key, **extra}


def test_grounded_proposal_apply_dryrun_duplicate_and_replay_preserve_report():
    writes, brief, surface = context()
    proposed = call(surface, "propose_graph_cleanup", {"manifests": [manifest()]})
    candidate = proposed["candidates"][0]
    assert candidate["basis"] == "brief_hypothesis" and candidate["support"]["char_start"] is not None
    op = {"action": "relation", "manifest": manifest(), "candidate_id": candidate["id"]}
    args = request(surface, [op])
    assert call(surface, "apply_graph_cleanup", args)["results"][0]["state"] == "would_apply"
    assert not [n for n in writes.nodes() if n.node_type.value == "relation_assertion"]
    args["dry_run"] = False
    result = call(surface, "apply_graph_cleanup", args)
    assert result["results"][0]["state"] == "applied"
    assert result["after"]["isolated_count"] < result["before"]["isolated_count"]
    assert call(surface, "apply_graph_cleanup", args)["replayed"]
    assert call(surface, "propose_graph_cleanup", {"manifests": [manifest()]})["candidates"][0]["duplicate"]
    assert writes.get_latest_idea_brief("idea").report_markdown == brief.report_markdown


def test_missing_support_is_unresolved_and_private_support_is_not_returned():
    writes, _, surface = context()
    proposed = call(surface, "propose_graph_cleanup", {"manifests": [manifest("存在しない引用")]})
    assert proposed["candidates"][0]["state"] == "unresolved"
    assert "存在しない引用" not in json.dumps(proposed, ensure_ascii=False)
    writes.put_node(Asset(id="hidden", owner_id="owner", name="機密"), idempotency_key="hidden")
    raw = manifest()
    raw["candidates"][0]["target_id"] = "hidden"
    with pytest.raises(McpReadError) as error:
        call(surface, "propose_graph_cleanup", {"manifests": [raw]})
    assert "hidden" not in error.value.message and "機密" not in error.value.message


def synthetic_source():
    return Source(id="synthetic", owner_id="owner", title="架空", egress_policy=EgressPolicy.SHAREABLE,
        provenance=Provenance(actor="nebula_synthetic_fixture", operation="create_synthetic_fixture",
                              rule_version="synthetic-fixture-v1"))


def test_synthetic_source_archive_restore_permissions_revision_and_idempotency():
    writes, _, surface = context(allow_delete=True)
    source = synthetic_source()
    writes.put_node(source, idempotency_key="fixture")
    op = {"action": "archive", "node_id": source.id, "expected_revision": 0}
    args = request(surface, [op])
    preview = call(surface, "apply_graph_cleanup", args)
    assert preview["results"][0]["impact"]["preserves_history"]
    assert writes.get_node(source.id).status.value == "active"
    args["dry_run"] = False
    applied = call(surface, "apply_graph_cleanup", args)
    assert applied["outcome"] == "success"
    assert writes.get_node(source.id).status.value == "archived"
    assert call(surface, "apply_graph_cleanup", args)["replayed"]
    restored = call(surface, "apply_graph_cleanup", request(surface,
        [{"action": "restore", "node_id": source.id, "expected_revision": 1}], key="restore", dry_run=False))
    assert restored["outcome"] == "success" and writes.get_node(source.id).revision == 2
    assert writes.get_node(source.id).egress_policy is EgressPolicy.SHAREABLE
    surface.allow_delete = False
    with pytest.raises(McpReadError, match="権限"):
        call(surface, "apply_graph_cleanup", request(surface, [op], key="denied", dry_run=False))


def test_production_reference_and_name_only_test_refuse_archive():
    writes, _, surface = context(allow_delete=True)
    source = synthetic_source()
    writes.put_node(source, idempotency_key="fixture")
    # A private reference must block deletion, but never expose its identity.
    writes._structural_edges.append(("private-production", "CITES", source.id))
    result = call(surface, "apply_graph_cleanup", request(surface,
        [{"action": "archive", "node_id": source.id, "expected_revision": 0}], dry_run=False))
    assert result["outcome"] == "partial" and result["unresolved_count"] == 1
    assert "private-production" not in json.dumps(result)
    assert writes.get_node(source.id).status.value == "active"
    ordinary = replace(source, id="ordinary", title="テスト試験", provenance=Provenance())
    writes.put_node(ordinary, idempotency_key="ordinary")
    result = call(surface, "apply_graph_cleanup", request(surface,
        [{"action": "archive", "node_id": ordinary.id, "expected_revision": 0}], key="ordinary", dry_run=False))
    assert result["unresolved_count"] == 1


def test_owner_wrong_fields_limits_and_stale_snapshot_fail_closed():
    _, _, surface = context()
    with pytest.raises(McpReadError, match="本人"):
        surface.call("audit_graph", {}, owner_id="other")
    for arguments in ({"owner_id": "owner"}, {"limit": True}, {"limit": 101}):
        with pytest.raises(McpReadError):
            call(surface, "audit_graph", arguments)
    args = request(surface, [{"action": "archive", "node_id": "idea", "expected_revision": 0}])
    args["snapshot_id"] = "stale"
    with pytest.raises(McpReadError):
        call(surface, "apply_graph_cleanup", args)
    args["operations"] *= 21
    with pytest.raises(McpReadError):
        call(surface, "apply_graph_cleanup", args)


def test_partial_batch_and_reused_key_changed_intent_are_distinct():
    writes, _, surface = context(allow_delete=True)
    writes.put_node(synthetic_source(), idempotency_key="fixture")
    args = request(surface, [{"action": "archive", "node_id": "synthetic", "expected_revision": 0},
                             {"action": "archive", "node_id": "asset", "expected_revision": 1}], dry_run=False)
    result = call(surface, "apply_graph_cleanup", args)
    assert result["outcome"] == "partial" and result["unresolved_count"] == 1
    assert [r["state"] for r in result["results"]] == ["applied", "unresolved"]
    assert call(surface, "apply_graph_cleanup", args)["replayed"]
    changed = dict(args, operations=[{"action": "restore", "node_id": "synthetic", "expected_revision": 1}])
    with pytest.raises(McpReadError):
        call(surface, "apply_graph_cleanup", changed)
    assert writes.get_node("synthetic").status.value == "archived"


def test_synthetic_idea_and_asset_preserve_immutable_history_and_restore():
    from nebula.graph_admin_cleanup import retire
    writes, _, _ = context(allow_delete=True)
    provenance = synthetic_source().provenance
    for node in (Idea(id="fixture-idea", owner_id="owner", title="架空", provenance=provenance, egress_policy=EgressPolicy.SHAREABLE),
                 Asset(id="fixture-asset", owner_id="owner", name="架空", provenance=provenance, egress_policy=EgressPolicy.SHAREABLE)):
        writes.put_node(node, idempotency_key=node.id)
        archived = retire(writes, node.id, node.revision, "archive-" + node.id)
        assert archived["target_id"] != node.id
        restored = retire(writes, archived["target_id"], archived["revision"], "restore-" + node.id, restore=True)
        assert writes.get_node(restored["target_id"]).supersedes_id == archived["target_id"]
        assert writes.get_node(restored["target_id"]).egress_policy is EgressPolicy.SHAREABLE
