from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from dots.founder_graph import EgressPolicy, Idea, NodeType, Provenance, ResearchCampaign, ResearchRun, Status
from dots.founder_graph_neo4j import Neo4jGraphGateway, Neo4jUnavailableError, _node_properties
from dots.founder_graph_neo4j_idea_brief import _serialize_persisted_idea_brief
from dots.founder_graph_neo4j_write import Neo4jIdeaBriefStore
from dots.founder_graph_write import GraphWriteError, IdempotencyConflictError, RevisionConflictError
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion


class Result:
    def __init__(self, rows=()):
        self.rows = tuple(rows)

    def single(self, **_kwargs):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class BriefTx:
    def __init__(self, idea):
        self.nodes = {idea.id: _node_properties(idea)}
        self.briefs = {}
        self.audits = {}
        self.run_record = None
        self.run_audit = None
        self.run_campaign = None
        self.campaign_history = ()
        self.calls = []
        self.fail_after_write = False
        self.fail_recovery_read = False
        self.receipt_revision_override = None

    def run(self, query, **params):
        self.calls.append((query, params))
        if "operation: 'record_research_run'" in query:
            return Result((self.run_audit,) if self.run_audit else ())
        if "MATCH (a:FounderGraphAudit" in query:
            key = params.get("idempotency_key", params.get("key"))
            return Result((self.audits[key],) if key in self.audits else ())
        if "_dots_idea_write_lock" in query:
            node = self.nodes.get(params["id"])
            return Result((self._metadata(node),) if node else ())
        if "_dots_revision_write_lock" in query:
            if self.run_campaign and params.get("id") == self.run_campaign["id"]:
                return Result((self._metadata(self.run_campaign),))
            return Result()
        if "MATCH (h:FounderGraphHistory" in query:
            return Result(row for row in self.campaign_history
                          if row["owner_id"] == params["owner_id"]
                          and row["target_id"] == params["campaign_id"])
        if "HAS_RUN" in query:
            return Result(({"campaign_id": self.run_record["campaign_id"],
                            "owner_id": self.run_record["owner_id"]},) if self.run_record else ())
        if "MATCH (c:ResearchCampaign" in query:
            return Result((self.run_campaign,) if self.run_campaign
                          and self.run_campaign["id"] == params["campaign_id"]
                          and self.run_campaign["owner_id"] == params["owner_id"] else ())
        if "MATCH (r:ResearchRun" in query:
            if self.run_record and self.run_record["id"] == params["id"] and self.run_record["owner_id"] == params["owner_id"]:
                fields = ("id", "owner_id", "node_type", "revision", "payload_json")
                return Result(({name: self.run_record[name] for name in fields},))
            return Result()
        if "idea_lineage_root_id: $root_id" in query:
            return Result(row for row in self.briefs.values()
                          if row["owner_id"] == params["owner_id"]
                          and row["idea_lineage_root_id"] == params["root_id"])
        if "MATCH (b:IdeaBriefVersion" in query and "payload_json" in query:
            row = self.briefs.get(params.get("id", params.get("brief_id")))
            if row and row["owner_id"] == params["owner_id"]:
                return Result((row,))
            return Result()
        if "MATCH (i:Idea" in query and "payload_json" in query:
            rows = (node for node in self.nodes.values() if node["owner_id"] == params["owner_id"])
            if "supersedes_id: $parent_id" in query:
                rows = (node for node in rows if json.loads(node["payload_json"])["supersedes_id"] == params["parent_id"])
            return Result(self._record(node) for node in rows)
        if "MATCH (n) WHERE n.id = $id" in query:
            row = self.nodes.get(params["id"]) or self.briefs.get(params["id"])
            return Result(({"id": params["id"]},) if row else ())
        if "CREATE (b:IdeaBriefVersion" in query:
            row = dict(params["properties"])
            self.briefs[row["id"]] = row
        elif "CREATE (a:FounderGraphAudit" in query:
            self.audits[params.get("idempotency_key", params.get("key"))] = {
                "operation": params["operation"], "payload_fingerprint": params.get("fingerprint", params.get("payload_fingerprint")),
                "target_id": params["target_id"], "target_type": params["target_type"], "revision": params["revision"],
            }
        return Result()

    @staticmethod
    def _metadata(node):
        return {name: node[name] for name in ("id", "owner_id", "node_type", "revision")}

    @staticmethod
    def _record(node):
        return {name: node[name] for name in ("id", "owner_id", "node_type", "revision", "payload_json")}


class Session(BriefTx):
    def __init__(self, state):
        self.__dict__ = state.__dict__
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self):
        return None

    def execute_write(self, callback):
        result = callback(self)
        if self.state.fail_after_write:
            self.state.fail_after_write = False
            if self.state.receipt_revision_override is not None:
                key = next(reversed(self.state.audits))
                self.state.audits[key]["revision"] = self.state.receipt_revision_override
                self.state.receipt_revision_override = None
            raise Neo4jUnavailableError("Neo4j operation failed")
        return result

    def execute_read(self, callback):
        if self.state.fail_recovery_read:
            self.state.fail_recovery_read = False
            raise Neo4jUnavailableError("Neo4j operation failed")
        return callback(self)


class Driver:
    def __init__(self, state):
        self.state = state

    def session(self, *, database):
        assert database == "neo4j"
        return Session(self.state)


def fixtures():
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    idea = Idea(
        id="idea-root", owner_id="owner-brief-store", title="synthetic",
        status=Status.ACTIVE, revision=0,
        provenance=Provenance(actor="synthetic", operation="create", target_id="idea-root",
                              occurred_at=now, idempotency_key="idea-root-key"),
    )
    brief = IdeaBriefVersion(
        owner_id=idea.owner_id, idea_lineage_root_id=idea.id, based_on_idea_id=idea.id,
        id="brief-one", revision=1, created_at=now,
        sections=tuple(IdeaBriefSection(index=index, content=f"synthetic {index}") for index in range(8)),
    )
    state = BriefTx(idea)
    store = Neo4jIdeaBriefStore(Neo4jGraphGateway(Driver(state), idea.owner_id))
    return idea, brief, state, store


def test_store_saves_reads_latest_and_keeps_brief_payload_out_of_node_properties():
    idea, brief, state, store = fixtures()

    receipt = store.save(brief, expected_latest_revision=None, idempotency_key="brief-key")

    assert receipt.target_id == brief.id and receipt.target_type == "idea_brief_version"
    assert store.get(brief.id) == brief
    assert store.get_latest(idea.id) == brief
    assert set(state.briefs[brief.id]) == {
        "id", "owner_id", "node_type", "revision", "idea_lineage_root_id", "supersedes_id", "payload_json",
    }
    assert "synthetic 0" not in state.briefs[brief.id].get("search_text", "")
    assert len(state.audits) == 1


def test_store_replay_is_idempotent_and_changed_intent_conflicts_without_mutation():
    _idea, brief, state, store = fixtures()
    first = store.save(brief, expected_latest_revision=None, idempotency_key="brief-key")
    replay = store.save(brief, expected_latest_revision=None, idempotency_key="brief-key")
    assert replay == first.__class__(first.operation, first.target_id, first.target_type, first.revision,
                                     first.idempotency_key, replayed=True)
    changed = IdeaBriefVersion(
        owner_id=brief.owner_id, idea_lineage_root_id=brief.idea_lineage_root_id,
        based_on_idea_id=brief.based_on_idea_id, id=brief.id, created_at=brief.created_at,
        sections=tuple(IdeaBriefSection(index=i, content="changed" if i == 0 else f"synthetic {i}") for i in range(8)),
    )
    with pytest.raises(GraphWriteError):
        store.save(changed, expected_latest_revision=None, idempotency_key="brief-key")
    assert len(state.briefs) == len(state.audits) == 1


def test_store_rejects_stale_latest_revision_without_mutation():
    idea, brief, state, store = fixtures()
    store.save(brief, expected_latest_revision=None, idempotency_key="brief-key")
    revised = brief.revise(sections=(IdeaBriefSection(index=0, content="new"),))
    with pytest.raises(RevisionConflictError):
        store.save(revised, expected_latest_revision=2, idempotency_key="stale-key")
    assert store.get_latest(idea.id) == brief
    assert len(state.briefs) == len(state.audits) == 1


def test_store_appends_exact_successor_revision_and_reads_it_as_latest():
    idea, brief, state, store = fixtures()
    store.save(brief, expected_latest_revision=None, idempotency_key="brief-key")
    revised = brief.revise(sections=(IdeaBriefSection(index=0, content="revised synthetic"),))

    receipt = store.save(revised, expected_latest_revision=1, idempotency_key="brief-revision")

    assert receipt.revision == 2
    assert store.get(brief.id) == brief
    assert store.get_latest(idea.id) == revised
    assert len(state.briefs) == 2 and len(state.audits) == 2


def test_store_rejects_researched_brief_until_registered_run_and_campaign_proof_exists():
    idea, brief, state, store = fixtures()
    researched = IdeaBriefVersion(
        owner_id=brief.owner_id, idea_lineage_root_id=brief.idea_lineage_root_id,
        based_on_idea_id=brief.based_on_idea_id, id=brief.id, created_at=brief.created_at,
        research_run_ids=("missing-run",),
        sections=tuple(IdeaBriefSection(index=i, content=f"synthetic {i}") for i in range(8)),
    )
    with pytest.raises(GraphWriteError):
        store.save(researched, expected_latest_revision=None, idempotency_key="researched-key")
    assert not state.briefs and not state.audits


def test_store_accepts_researched_brief_with_registered_run_and_complete_campaign_history():
    idea, brief, state, store = fixtures()
    created_at = brief.created_at - timedelta(minutes=10)
    campaign = ResearchCampaign(
        id="campaign-brief", owner_id=brief.owner_id, purpose="synthetic purpose",
        scope={"target_ids": [idea.id]}, target_idea_id=idea.id,
        allowed_categories=("idea.summary",), trial_budget=2,
        expires_at=brief.created_at + timedelta(hours=1),
        egress_policy=EgressPolicy.SHAREABLE, created_at=created_at,
        provenance=Provenance(actor="synthetic", operation="create", target_id="campaign-brief",
                              occurred_at=created_at, idempotency_key="campaign-create"),
    )
    approved = campaign.approve(approved_at=brief.created_at - timedelta(minutes=5))
    started = approved.approved_at + timedelta(minutes=1)
    run = ResearchRun(
        id="run-brief", owner_id=brief.owner_id, campaign_id=approved.id,
        input_snapshot={"question": "synthetic"}, model_snapshot="synthetic@1",
        sources=("source-synthetic",), evidence_ids=("evidence-synthetic",),
        results={"summary": "synthetic"}, status=Status.COMPLETED,
        egress_policy=approved.egress_policy,
        authorization_snapshot_id=approved.authorization_snapshot_id,
        authorization_revision=approved.authorization_revision,
        started_at=started, finished_at=started + timedelta(minutes=1),
        provenance=Provenance(actor="synthetic", operation="record_research_run", target_id="run-brief",
                              occurred_at=started + timedelta(minutes=1), idempotency_key="run-key"),
    )
    registered = approved.register_run(
        at=run.finished_at,
        provenance=Provenance(actor="synthetic", operation="record_research_run", target_id=approved.id,
                              occurred_at=run.finished_at, idempotency_key="campaign-run-key"),
    )
    state.run_campaign = {
        "id": registered.id, "owner_id": registered.owner_id, "node_type": NodeType.RESEARCH_CAMPAIGN.value,
        "revision": registered.aggregate_revision, "payload_json": _node_properties(registered)["payload_json"],
    }
    state.campaign_history = tuple({
        "id": item.id, "target_id": item.id, "owner_id": item.owner_id,
        "node_type": NodeType.RESEARCH_CAMPAIGN.value,
        "revision": item.aggregate_revision, "payload_json": _node_properties(item)["payload_json"],
    } for item in (campaign, approved))
    properties = _node_properties(run)
    state.run_record = {
        "id": run.id, "owner_id": run.owner_id, "node_type": NodeType.RESEARCH_RUN.value,
        "revision": 0, "payload_json": properties["payload_json"], "campaign_id": run.campaign_id,
    }
    state.run_audit = {
        "idempotency_key": "run-key", "target_type": NodeType.RESEARCH_RUN.value,
        "revision": 0, "payload_fingerprint": "fingerprint",
    }
    researched = IdeaBriefVersion(
        owner_id=brief.owner_id, idea_lineage_root_id=brief.idea_lineage_root_id,
        based_on_idea_id=brief.based_on_idea_id, id=brief.id, created_at=brief.created_at,
        research_run_ids=(run.id,),
        sections=tuple(IdeaBriefSection(index=i, content=f"synthetic section {i}") for i in range(8)),
    )

    receipt = store.save(researched, expected_latest_revision=None, idempotency_key="researched-key")

    assert receipt.revision == 1
    assert store.get_latest(idea.id) == researched
    assert len(state.briefs) == len(state.audits) == 1


def test_unknown_commit_recovers_only_exact_receipt_and_revision():
    _idea, brief, state, store = fixtures()
    state.fail_after_write = True

    receipt = store.save(brief, expected_latest_revision=None, idempotency_key="unknown-commit")

    assert receipt.replayed is True
    assert receipt.revision == brief.revision
    assert len(state.briefs) == len(state.audits) == 1

    _idea2, brief2, state2, store2 = fixtures()
    state2.fail_after_write = True
    state2.receipt_revision_override = brief2.revision + 1
    with pytest.raises(IdempotencyConflictError):
        store2.save(brief2, expected_latest_revision=None, idempotency_key="wrong-revision")
    assert len(state2.briefs) == len(state2.audits) == 1


def test_unknown_commit_recovery_lookup_failure_returns_fixed_unavailable_error():
    _idea, brief, state, store = fixtures()
    state.fail_after_write = True
    state.fail_recovery_read = True

    with pytest.raises(Neo4jUnavailableError, match="^Neo4j operation failed$"):
        store.save(brief, expected_latest_revision=None, idempotency_key="unreadable-receipt")
