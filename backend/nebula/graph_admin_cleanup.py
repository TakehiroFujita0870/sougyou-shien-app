"""Bounded management commands reusing Brief validation and audited lifecycle writes."""
from dataclasses import asdict, replace
from datetime import datetime
from hashlib import sha256
import json

from .founder_graph import NodeType, Provenance, Source, Status
from .founder_graph_write import payload_fingerprint
from .graph_admin_audit import inventory, safe_graph, synthetic_provenance


def references(value, identifier):
    if isinstance(value, dict):
        return any(references(v, identifier) for k, v in value.items() if k not in {"id", "title", "name", "content", "text", "description", "report_markdown"})
    if isinstance(value, (tuple, list)):
        return any(references(v, identifier) for v in value)
    return value == identifier


def synthetic_lineage(payloads, identity):
    seen = set()
    while identity in payloads and identity not in seen:
        seen.add(identity)
        payload = payloads[identity]
        if synthetic_provenance(payload):
            return True
        if payload.get("provenance", {}).get("actor") != "nebula_graph_cleanup":
            return False
        identity = payload.get("supersedes_id")
    return False


def retirement_impact(payloads, structural, identifier):
    """Private references affect eligibility, but never leave the server as IDs/counts."""
    target = payloads.get(identifier)
    if not target or target.get("node_type") not in {"idea", "asset", "source"}:
        raise ValueError("unsupported retirement")
    if not synthetic_lineage(payloads, identifier):
        raise ValueError("unverified synthetic provenance")
    dependent = {identifier}
    if target["node_type"] == "source":
        dependent.update(i for i, p in payloads.items() if p.get("node_type") == "source_revision" and p.get("source_id") == identifier)
        dependent.update(i for i, p in payloads.items() if p.get("node_type") == "content_chunk" and p.get("source_revision_id") in dependent)
    for identity, payload in payloads.items():
        if identity not in dependent and any(references(payload, i) for i in dependent):
            raise ValueError("retirement unavailable")
    if any((s in dependent) != (t in dependent) for s, _, t in structural):
        raise ValueError("retirement unavailable")
    return {"node_id": identifier, "kind": target["node_type"], "revision": target.get("revision", 0),
            "action": "archive", "preserves_history": True}


def _source(payload, status):
    values = {k: v for k, v in payload.items() if k != "node_type"}
    provenance = dict(values["provenance"])
    provenance["occurred_at"] = datetime.fromisoformat(provenance["occurred_at"])
    values["provenance"] = Provenance(**provenance)
    values["created_at"] = datetime.fromisoformat(values["created_at"])
    return replace(Source(**values), status=Status(status), revision=values.get("revision", 0) + 1)


def retire(writes, identifier, revision, key, *, restore=False):
    """Lock, recheck all references, then use canonical lifecycle transaction bodies."""
    operation = "restore_synthetic" if restore else "archive_synthetic"
    gateway = getattr(writes, "gateway", None)
    def perform(tx=None):
        replay = writes.get_write_receipt(key) if tx is None else None
        if replay:
            if replay.operation != operation and replay.operation not in {("restore_" if restore else "archive_") + k for k in ("idea", "asset")}:
                raise ValueError("idempotency conflict")
            expected_target = identifier if replay.operation == operation else replay.target_type + "_" + sha256(f'{writes.owner_id}:{replay.operation}:{key}'.encode()).hexdigest()[:32]
            if replay.target_id != expected_target or replay.revision != revision + 1:
                raise ValueError("idempotency conflict")
            return dict(asdict(replay), replayed=True)
        if gateway is not None:
            row = tx.run("MATCH (n {id: $id, owner_id: $owner}) "
                         "SET n._nebula_cleanup_lock = true REMOVE n._nebula_cleanup_lock "
                         "RETURN n.node_type AS kind", id=identifier, owner=writes.owner_id).single()
            if row is None:
                raise ValueError("target unavailable")
        payloads, structural = inventory(writes, tx=tx)
        payload = payloads.get(identifier)
        if not payload or payload.get("owner_id") != writes.owner_id or payload.get("egress_policy") != "shareable":
            raise ValueError("target unavailable")
        kind = payload["node_type"]
        actual_operation = (("restore_" if restore else "archive_") + kind) if kind in {"idea", "asset"} else operation
        status = Status.ACTIVE if restore else Status.ARCHIVED
        fingerprint = (payload_fingerprint(actual_operation, identifier, revision, status.value, writes.owner_id)
                       if kind in {"idea", "asset"} else payload_fingerprint(operation, identifier, revision, writes.owner_id))
        if gateway is not None:
            replay = gateway._put_node_replay_tx(tx, operation=actual_operation, idempotency_key=key, fingerprint=fingerprint)
            if replay:
                return dict(asdict(replay), replayed=True)
        if payload.get("revision", 0) != revision or not synthetic_lineage(payloads, identifier):
            raise ValueError("stale or unverified target")
        if restore:
            if payload.get("status") != "archived":
                raise ValueError("target is not archived")
        else:
            retirement_impact(payloads, structural, identifier)
        if kind == "source":
            source = _source(payload, status)
            if gateway is None:
                receipt = writes.put_node(source, expected_revision=revision, idempotency_key=key,
                                          operation=operation, actor="nebula_graph_cleanup")
            else:
                receipt = gateway._put_node_tx(tx, source, NodeType.SOURCE, gateway.label_for(NodeType.SOURCE),
                    key, revision, operation, "nebula_graph_cleanup", fingerprint)
        elif kind in {"idea", "asset"}:
            # Preserve canonical immutable successor/revision and existing audit semantics.
            lifecycle_operation = ("restore_" if restore else "archive_") + kind
            if gateway is None:
                receipt = getattr(writes, lifecycle_operation)(identifier, expected_revision=revision,
                    idempotency_key=key, actor="nebula_graph_cleanup")
            else:
                fp = payload_fingerprint(lifecycle_operation, identifier, revision, status.value, writes.owner_id)
                successor = kind + "_" + sha256(f'{writes.owner_id}:{lifecycle_operation}:{key}'.encode()).hexdigest()[:32]
                receipt = getattr(gateway, "_transition_" + kind + "_status_tx")(
                    tx, identifier, revision, key, "nebula_graph_cleanup", lifecycle_operation, status, fp, successor)
        else:
            raise ValueError("unsupported retirement")
        return asdict(receipt)
    if gateway is None:
        with writes._lock:
            return perform()
    with gateway._session() as session:
        return gateway._execute_write(session, perform)


class GraphCleanupService:
    def __init__(self, writes, reads, processor):
        self.writes, self.reads, self.processor = writes, reads, processor

    def propose(self, manifests):
        graph, payloads, _ = safe_graph(self.writes, self.reads)
        visible = {n["id"] for n in graph["collections"]["nodes"]}
        existing = {(e["source_id"], e["relation"], e["target_id"]) for e in graph["collections"]["edges"]}
        proposals = []
        for item in manifests:
            idea_id = item["idea_id"]
            if idea_id not in visible:
                raise ValueError("target unavailable")
            if self.processor is None:
                raise ValueError("candidate processor unavailable")
            # Canonical read forbids returning support locators for private Briefs.
            public = self.reads.fetch_idea_brief(idea_id, owner_id=self.writes.owner_id)
            brief = self.processor._latest_brief(self._root(idea_id, payloads))
            if brief is None or public.get("brief_id") != brief.id or item["brief_id"] != brief.id or item["expected_revision"] != brief.revision:
                raise ValueError("stale Brief")
            for raw in item["candidates"]:
                if raw.get("source_id") not in visible or raw.get("target_id") not in visible or any(e not in visible for e in raw.get("evidence_ids", ())):
                    raise ValueError("candidate unavailable")
                try:
                    manifest = {"version": 1, "idea_id": idea_id, "candidates": [raw]}
                    validated = self.processor._validate_raw(manifest, brief, idea_id)
                except ValueError:
                    proposals.append({"source_id": raw.get("source_id"), "target_id": raw.get("target_id"),
                                      "relation": raw.get("predicate"), "basis": raw.get("basis"),
                                      "brief_id": brief.id, "brief_revision": brief.revision,
                                      "evidence_ids": list(raw.get("evidence_ids", ())), "confidence": None,
                                      "duplicate": (raw.get("source_id"), raw.get("predicate"), raw.get("target_id")) in existing,
                                      "state": "unresolved", "recommended_action": "supply_grounded_support"})
                    continue
                candidate = validated.candidates[0]
                assertion = candidate.assertion
                duplicate = (assertion.source_id, assertion.predicate.value, assertion.target_id) in existing
                proposals.append({"id": candidate.candidate_id, "source_id": assertion.source_id,
                    "target_id": assertion.target_id, "relation": assertion.predicate.value,
                    "brief_id": brief.id, "brief_revision": brief.revision,
                    "evidence_ids": list(assertion.evidence_ids), "basis": assertion.basis.value,
                    "claim_ids": sorted({payloads[e]["claim_id"] for e in assertion.evidence_ids if payloads[e].get("claim_id")}),
                    "support": {"char_start": candidate.support.char_start, "char_end": candidate.support.char_end,
                                "section_index": candidate.support.section_index},
                    "confidence": assertion.confidence, "duplicate": duplicate,
                    "state": "duplicate" if duplicate else "proposed",
                    "recommended_action": "skip" if duplicate else "apply_after_review"})
        return graph, proposals

    @staticmethod
    def _root(identity, payloads):
        seen = set()
        while payloads[identity].get("supersedes_id"):
            if identity in seen:
                raise ValueError("invalid lineage")
            seen.add(identity)
            identity = payloads[identity]["supersedes_id"]
        return identity

    def apply_relation(self, item, candidate_id):
        _, proposals = self.propose([item])
        proposal = next((p for p in proposals if p.get("id") == candidate_id), None)
        if proposal is None:
            raise ValueError("candidate unavailable")
        if proposal["duplicate"]:
            return {"id": candidate_id, "state": "duplicate"}
        payloads, _ = inventory(self.writes)
        brief = self.processor._latest_brief(self._root(item["idea_id"], payloads))
        validated = self.processor._validate_raw({"version": 1, "idea_id": item["idea_id"], "candidates": item["candidates"]}, brief, item["idea_id"])
        candidate = next(c for c in validated.candidates if c.candidate_id == candidate_id)
        self.processor._apply_assertion(candidate.assertion)
        return {"id": candidate_id, "state": "applied"}
