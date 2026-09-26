from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from dots.founder_graph import EgressPolicy, NodeType, Provenance, ResearchCampaign, ResearchRun, Status
from dots.founder_graph_neo4j import Neo4jGraphGateway
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService
from dots.founder_graph_write import GraphWriteError, WriteReceipt


class Result:
    def __init__(self, rows=()):
        self.rows = tuple(rows)

    def single(self, **_kwargs):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


def campaign_states(*, owner_id="owner-history", campaign_id="campaign-history"):
    now = datetime.now(timezone.utc)
    created = now - timedelta(minutes=5)
    initial = ResearchCampaign(
        id=campaign_id, owner_id=owner_id, purpose="synthetic purpose",
        scope={"target_ids": ["idea-history"], "nested": {"field": "value"}},
        questions=("question one", "question two"), target_idea_id="idea-history",
        allowed_categories=("idea.summary", "source.title"), external_sources=("https://example.test",),
        trial_budget=3, expires_at=now + timedelta(days=2), egress_policy=EgressPolicy.SHAREABLE,
        created_at=created,
        provenance=Provenance(actor="synthetic", operation="create_research_campaign", target_id=campaign_id,
                              occurred_at=created, idempotency_key="history-create"),
    )
    approved = initial.approve(approved_at=now - timedelta(minutes=4))
    registered = approved.register_run(at=now - timedelta(minutes=3))
    changed = registered.change_scope(
        {"target_ids": ["idea-history"], "nested": {"field": "changed"}},
        at=now - timedelta(minutes=2),
    )
    reapproved = changed.approve(approved_at=now - timedelta(minutes=1))
    revoked_at = now - timedelta(seconds=30)
    revoked = reapproved._transition(
        status=Status.REVOKED, authorized=False, approved_at=None,
        aggregate_revision=reapproved.aggregate_revision + 1,
        provenance=Provenance(actor="synthetic", operation="revoke_research_campaign", target_id=campaign_id,
                              occurred_at=revoked_at, idempotency_key="history-revoke"),
    )
    return initial, approved, registered, changed, reapproved, revoked


def record_for(campaign):
    from dots.founder_graph_neo4j import _node_properties

    return {
        "id": campaign.id,
        "owner_id": campaign.owner_id,
        "node_type": NodeType.RESEARCH_CAMPAIGN.value,
        "revision": campaign.aggregate_revision,
        "payload_json": _node_properties(campaign)["payload_json"],
    }


class CampaignHistorySession:
    def __init__(self, campaign=None):
        self.campaign = record_for(campaign) if campaign is not None else None
        self.history = []
        self.audit = {}
        self.runs = {}
        self.links = []
        self.calls = []
        self.fail_after_history_write = False

    def execute_read(self, callback):
        return callback(self)

    def execute_write(self, callback):
        snapshot = deepcopy((self.campaign, self.history, self.audit, self.runs, self.links))
        try:
            return callback(self)
        except Exception:
            self.campaign, self.history, self.audit, self.runs, self.links = snapshot
            raise

    def run(self, query, **params):
        self.calls.append((query, params))
        if "_dots_revision_write_lock" in query:
            if self.campaign is None or params["id"] != self.campaign["id"] or params["owner_id"] != self.campaign["owner_id"]:
                return Result()
            return Result(({key: self.campaign[key] for key in ("id", "owner_id", "node_type", "revision")},))
        if "MATCH (a:FounderGraphAudit" in query:
            return Result((self.audit[params["idempotency_key"]],) if params["idempotency_key"] in self.audit else ())
        if "MATCH (c:ResearchCampaign" in query and "payload_json" in query:
            if self.campaign is None or params["campaign_id"] != self.campaign["id"]:
                return Result()
            if params.get("owner_id", self.campaign["owner_id"]) != self.campaign["owner_id"]:
                return Result()
            return Result((self.campaign,))
        if "MATCH (n:ResearchCampaign" in query and "payload_json" in query:
            if self.campaign is None or params["id"] != self.campaign["id"] or params["owner_id"] != self.campaign["owner_id"]:
                return Result()
            return Result((self.campaign,))
        if "MATCH (h:FounderGraphHistory" in query:
            rows = [item for item in self.history if item["target_id"] == params.get("campaign_id", params.get("target_id"))
                    and item["owner_id"] == params["owner_id"]
                    and ("revision" not in params or item["revision"] == params["revision"])]
            if "RETURN h.target_id AS id" in query:
                rows = [dict(item, id=item["target_id"], node_type=params["node_type"]) for item in rows]
            return Result(sorted(rows, key=lambda item: item["revision"]))
        if "CREATE (h:FounderGraphHistory" in query:
            self.history.append({
                "id": params["history_id"], "owner_id": params["owner_id"],
                "target_id": params["target_id"], "revision": params["revision"],
                "payload_json": params["payload_json"],
            })
            if self.fail_after_history_write:
                self.fail_after_history_write = False
                raise RuntimeError("synthetic history write failure")
            return Result()
        if "CREATE (n:ResearchCampaign) SET n = $properties" in query:
            properties = params["properties"]
            self.campaign = {key: properties[key] for key in ("id", "owner_id", "node_type", "revision", "payload_json")}
            return Result()
        if "SET n = $properties" in query and "MATCH (n:ResearchCampaign" in query:
            properties = params["properties"]
            self.campaign = {key: properties[key] for key in ("id", "owner_id", "node_type", "revision", "payload_json")}
            return Result()
        if "SET c = $properties" in query:
            properties = params["properties"]
            self.campaign = {key: properties[key] for key in ("id", "owner_id", "node_type", "revision", "payload_json")}
            return Result()
        if "MATCH (n {id: $run_id})" in query:
            return Result(({"id": params["run_id"]},) if params["run_id"] in self.runs else ())
        if "CREATE (r:ResearchRun" in query:
            self.runs[params["properties"]["id"]] = params["properties"]
            return Result()
        if "HAS_RUN" in query and "CREATE" in query:
            self.links.append((params["campaign_id"], params["run_id"]))
            return Result(({"id": params["run_id"]},))
        if "CREATE (a:FounderGraphAudit" in query:
            self.audit[params["idempotency_key"]] = {
                key: params[key] for key in ("owner_id", "idempotency_key", "operation", "target_id", "target_type", "revision", "payload_fingerprint")
            }
            return Result()
        return Result()


class Driver:
    def __init__(self, session):
        self.value = session

    def session(self, *, database):
        assert database == "neo4j"
        return self.value


def service(session):
    return Neo4jGraphWriteService(Neo4jGraphGateway(Driver(session), "owner-history"))


def test_history_resolver_roundtrips_all_fields_and_transitions_without_mutation():
    states = campaign_states()
    session = CampaignHistorySession(states[-1])
    session.history = [
        {"id": f"history-{item.aggregate_revision}", "owner_id": item.owner_id,
         "target_id": item.id, "revision": item.aggregate_revision,
         "payload_json": record_for(item)["payload_json"]}
        for item in states[:-1]
    ]
    history_before = deepcopy(session.history)
    calls_before = len(session.calls)
    gateway = Neo4jGraphGateway(Driver(session), "owner-history")

    registry = gateway._campaign_authorization_registry_tx(session, states[-1].id)

    assert registry.campaigns == states
    assert [item.aggregate_revision for item in registry.campaigns] == list(range(states[-1].aggregate_revision + 1))
    assert registry.campaigns[1].authorization_snapshot == states[1].authorization_snapshot
    assert session.history == history_before
    assert all(not any(token in query for token in ("CREATE", "SET ", "DELETE")) for query, _ in session.calls[calls_before:])


def test_generic_campaign_create_and_approve_persist_only_full_prior_revision_and_replay_is_noop():
    initial = campaign_states()[0]
    approved = initial.approve(approved_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    session = CampaignHistorySession()
    writes = service(session)

    create_receipt = writes.put_node(initial, idempotency_key="create-history", expected_revision=0,
                                     operation="create_research_campaign")
    assert create_receipt.revision == 0
    assert session.history == []
    approve_receipt = writes.put_node(approved, idempotency_key="approve-history", expected_revision=0,
                                      operation="approve_research_campaign")

    assert approve_receipt.revision == approved.aggregate_revision
    assert len(session.history) == 1
    assert json.loads(session.history[0]["payload_json"]) == json.loads(record_for(initial)["payload_json"])
    assert session.history[0]["revision"] == initial.aggregate_revision
    assert writes.put_node(approved, idempotency_key="approve-history", expected_revision=0,
                           operation="approve_research_campaign").replayed
    assert len(session.history) == 1
    assert Neo4jGraphGateway(Driver(session), "owner-history")._campaign_authorization_registry_tx(session, initial.id).campaigns == (initial, approved)


def test_create_approve_run_scope_reapprove_and_revoke_form_one_complete_revision_chain():
    from dots.founder_graph_neo4j_campaign import decode_persisted_research_campaign

    initial = campaign_states()[0]
    approved = initial.approve(approved_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    session = CampaignHistorySession()
    writes = service(session)
    writes.put_node(initial, idempotency_key="flow-create", expected_revision=0,
                    operation="create_research_campaign")
    writes.put_node(approved, idempotency_key="flow-approve", expected_revision=0,
                    operation="approve_research_campaign")

    now = datetime.now(timezone.utc)
    run = ResearchRun(
        id="flow-run", owner_id=approved.owner_id, campaign_id=approved.id,
        authorization_snapshot_id=approved.authorization_snapshot_id,
        authorization_revision=approved.authorization_revision,
        input_snapshot={"question": "synthetic"}, model_snapshot="synthetic@1",
        sources=("source-history",), evidence_ids=("evidence-history",), results={"summary": "synthetic"},
        status=Status.COMPLETED, egress_policy=EgressPolicy.SHAREABLE,
        started_at=now - timedelta(seconds=20), finished_at=now - timedelta(seconds=10),
        provenance=Provenance(actor="synthetic", operation="record_research_run", target_id="flow-run",
                              occurred_at=now, idempotency_key="flow-run-key"),
    )
    writes.record_research_run(run, expected_campaign_revision=approved.aggregate_revision,
                               idempotency_key="flow-run-key")
    registered = decode_persisted_research_campaign(session.campaign, owner_id="owner-history")
    changed_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    changed = registered.change_scope({"target_ids": ["idea-history"], "nested": {"scope": "changed"}}, at=changed_at)
    writes.put_node(changed, idempotency_key="flow-scope", expected_revision=registered.aggregate_revision,
                    operation="change_campaign_scope")
    reapproved = changed.approve(approved_at=changed_at + timedelta(seconds=1))
    writes.put_node(reapproved, idempotency_key="flow-reapprove", expected_revision=changed.aggregate_revision,
                    operation="approve_research_campaign")
    revoked_at = changed_at + timedelta(seconds=2)
    revoked = reapproved._transition(
        status=Status.REVOKED, authorized=False, approved_at=None,
        aggregate_revision=reapproved.aggregate_revision + 1,
        provenance=Provenance(actor="synthetic", operation="revoke_research_campaign", target_id=initial.id,
                              occurred_at=revoked_at, idempotency_key="flow-revoke"),
    )
    writes.put_node(revoked, idempotency_key="flow-revoke", expected_revision=reapproved.aggregate_revision,
                    operation="revoke_research_campaign")

    history = Neo4jGraphGateway(Driver(session), "owner-history")._campaign_authorization_registry_tx(session, initial.id).campaigns

    assert [item.aggregate_revision for item in history] == list(range(6))
    assert history[:2] == (initial, approved)
    assert history[2].run_count == 1 and history[2].status is Status.RUNNING
    assert history[3:] == (changed, reapproved, revoked)


def test_run_write_preserves_full_old_campaign_and_same_key_replay_does_not_extend_history():
    initial, approved, *_ = campaign_states()
    session = CampaignHistorySession(approved)
    session.history = [{
        "id": "history-0", "owner_id": initial.owner_id, "target_id": initial.id,
        "revision": initial.aggregate_revision, "payload_json": record_for(initial)["payload_json"],
    }]
    now = datetime.now(timezone.utc)
    run = ResearchRun(
        id="history-run", owner_id=approved.owner_id, campaign_id=approved.id,
        authorization_snapshot_id=approved.authorization_snapshot_id,
        authorization_revision=approved.authorization_revision,
        input_snapshot={"question": "synthetic"}, model_snapshot="synthetic@1",
        sources=("source-history",), evidence_ids=("evidence-history",),
        results={"summary": "synthetic"}, status=Status.COMPLETED,
        egress_policy=EgressPolicy.SHAREABLE,
        started_at=now - timedelta(minutes=2), finished_at=now - timedelta(minutes=1),
        provenance=Provenance(actor="synthetic", operation="record_research_run", target_id="history-run",
                              occurred_at=now, idempotency_key="history-run-key"),
    )
    writes = service(session)

    receipt = writes.record_research_run(run, expected_campaign_revision=approved.aggregate_revision,
                                         idempotency_key="history-run-key")
    history_after_first = deepcopy(session.history)
    replay = writes.record_research_run(run, expected_campaign_revision=approved.aggregate_revision,
                                        idempotency_key="history-run-key")

    assert isinstance(receipt, WriteReceipt) and receipt.replayed is False
    assert replay.replayed is True
    assert len(history_after_first) == 2
    assert json.loads(history_after_first[-1]["payload_json"]) == json.loads(record_for(approved)["payload_json"])
    assert session.history == history_after_first
    registry = Neo4jGraphGateway(Driver(session), "owner-history")._campaign_authorization_registry_tx(session, approved.id)
    assert registry.campaigns[:2] == (initial, approved)
    assert registry.campaigns[2].aggregate_revision == approved.aggregate_revision + 1
    assert registry.campaigns[2].run_count == approved.run_count + 1
    assert registry.campaigns[2].status is Status.RUNNING


@pytest.mark.parametrize(
    "corruption",
    [
        "gap", "duplicate", "sparse", "record_revision", "malformed_json",
        "payload_revision", "payload_owner", "payload_type", "revision_gt_zero_create",
    ],
)
def test_history_resolver_fails_closed_on_incomplete_or_foreign_history(corruption):
    initial, approved, registered, *_ = campaign_states()
    current = registered
    session = CampaignHistorySession(current)
    full = [
        {"id": f"h-{state.aggregate_revision}", "owner_id": state.owner_id,
         "target_id": state.id, "revision": state.aggregate_revision,
         "payload_json": record_for(state)["payload_json"]}
        for state in (initial, approved)
    ]
    if corruption == "gap":
        session.history = [full[0]]
    elif corruption == "duplicate":
        session.history = [full[0], full[1], dict(full[1], id="duplicate-history")]
    elif corruption == "sparse":
        session.history = [dict(full[0], payload_json=json.dumps({"id": initial.id, "node_type": "research_campaign", "revision": 0})), full[1]]
    elif corruption == "record_revision":
        session.history = [dict(full[0], revision=9), full[1]]
    elif corruption == "malformed_json":
        session.history = [dict(full[0], payload_json="{not-json"), full[1]]
    elif corruption == "payload_revision":
        session.history = [dict(full[0], payload_json=json.dumps({**json.loads(full[0]["payload_json"]), "aggregate_revision": 9})), full[1]]
    elif corruption == "payload_owner":
        session.history = [dict(full[0], payload_json=json.dumps({**json.loads(full[0]["payload_json"]), "owner_id": "other-owner"})), full[1]]
    elif corruption == "payload_type":
        session.history = [dict(full[0], payload_json=json.dumps({**json.loads(full[0]["payload_json"]), "node_type": "source"})), full[1]]
    else:
        current = current._transition(aggregate_revision=9)
        session = CampaignHistorySession(current)

    gateway = Neo4jGraphGateway(Driver(session), "owner-history")
    with pytest.raises(GraphWriteError):
        gateway._campaign_authorization_registry_tx(session, current.id)


def test_generic_create_with_revision_above_zero_is_preserved_but_never_given_fabricated_history():
    initial = campaign_states()[0]._transition(aggregate_revision=4)
    session = CampaignHistorySession()
    receipt = service(session).put_node(initial, idempotency_key="imported-campaign", expected_revision=0,
                                        operation="put_node")

    assert receipt.revision == 4
    assert session.campaign["revision"] == 4
    assert session.history == []
    with pytest.raises(GraphWriteError):
        Neo4jGraphGateway(Driver(session), "owner-history")._campaign_authorization_registry_tx(session, initial.id)


def test_failed_history_write_rolls_back_prior_snapshot_and_campaign_update_in_fake_transaction():
    initial = campaign_states()[0]
    session = CampaignHistorySession(initial)
    next_campaign = initial.approve(approved_at=datetime.now(timezone.utc))
    before = (deepcopy(session.campaign), deepcopy(session.history), deepcopy(session.audit))
    session.fail_after_history_write = True

    from dots.founder_graph_neo4j import Neo4jUnavailableError

    with pytest.raises(Neo4jUnavailableError, match="Neo4j operation failed"):
        service(session).put_node(next_campaign, idempotency_key="fail-history", expected_revision=0,
                                 operation="approve_research_campaign")

    assert (session.campaign, session.history, session.audit) == before
