"""Owner-local inventory; only the shareable induced graph leaves this module."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json

from .founder_graph_neo4j_codec import json_value
from .founder_graph_read import GraphReadNotFoundError

EXCLUDED = {"archived", "deleted", "superseded", "retracted", "expired", "cancelled", "revoked"}
MANAGEMENT = {"SUPERSEDES", "HAS_REVISION", "HAS_SOURCE_REVISION", "CURRENT_SOURCE_REVISION", "HAS_RUN", "PRODUCED",
              "ASSERTION_SOURCE", "ASSERTION_TARGET", "BASED_ON_BRIEF", "BASED_ON_IDEA"}
MANAGEMENT.update({"ASSERTS_FROM", "ASSERTS_TO"})
GROUNDING = {"CITES", "SUPPORTED_BY", "CONTRADICTED_BY", "BASED_ON", "HAS_CHUNK", "EVIDENCED_BY", "EVIDENCE_FROM"}
COLLECTIONS = ("nodes", "edges", "isolated", "semantic_isolated", "low_degree", "components", "component_members", "invalid_relations", "test_candidates", "relation_candidates")


def inventory(writes, *, tx=None):
    """Read without the visual browser's 500-node ceiling. Payloads stay internal."""
    gateway = getattr(writes, "gateway", None)
    if gateway is None:
        snapshot = writes.read_snapshot()
        nodes = {n.id: dict(json_value(n), node_type=n.node_type.value) for n in snapshot.nodes}
        nodes.update({b.id: dict(json_value(b), node_type="idea_brief_version") for b in snapshot.idea_briefs})
        edges = [(s, r, t) for s, r, t in writes.structural_edges()]
        return nodes, edges

    def read(tx):
        nodes, after = {}, ""
        while True:
            rows = list(tx.run(
                "MATCH (n {owner_id: $owner}) WHERE n.node_type IS NOT NULL AND n.id > $after "
                "RETURN n.id AS id, n.node_type AS kind, n.payload_json AS payload "
                "ORDER BY n.id LIMIT 1000", owner=writes.owner_id, after=after))
            for row in rows:
                payload = json.loads(row["payload"])
                if payload.get("id") != row["id"] or payload.get("owner_id") != writes.owner_id:
                    raise ValueError("invalid inventory")
                nodes[row["id"]] = dict(payload, node_type=row["kind"])
            if len(rows) < 1000:
                break
            after = rows[-1]["id"]
        edges, after = [], ""
        while True:
            rows = list(tx.run(
                "MATCH (a {owner_id: $owner})-[r]->(b {owner_id: $owner}) "
                "WHERE (r.owner_id IS NULL OR r.owner_id = $owner) AND elementId(r) > $after "
                "RETURN elementId(r) AS id, a.id AS source, type(r) AS relation, b.id AS target "
                "ORDER BY id LIMIT 1000", owner=writes.owner_id, after=after))
            edges.extend((r["source"], r["relation"], r["target"]) for r in rows)
            if len(rows) < 1000:
                break
            after = rows[-1]["id"]
        return nodes, edges
    if tx is not None:
        return read(tx)
    with gateway.read_session() as session:
        return gateway.execute_read(session, read)


def synthetic_provenance(payload):
    """Never infer test provenance from the title, name, or arbitrary note text."""
    provenance = payload.get("provenance", {})
    return (isinstance(provenance, dict)
            and provenance.get("actor") in {"nebula_synthetic_fixture", "dots_synthetic_fixture"}
            and provenance.get("operation") == "create_synthetic_fixture"
            and provenance.get("rule_version") == "synthetic-fixture-v1")


def legacy_relations(writes):
    gateway = getattr(writes, "gateway", None)
    if gateway is None:
        return [json_value(r) for r in writes.read_snapshot().relations]
    def read(tx):
        rows, after = [], ""
        while True:
            page = list(tx.run(
                "MATCH (a {owner_id:$owner})-[r]->(b {owner_id:$owner}) "
                "WHERE r.owner_id=$owner AND r.status IS NOT NULL AND elementId(r)>$after "
                "RETURN elementId(r) AS id, a.id AS source_id, b.id AS target_id, "
                "type(r) AS relation, r.status AS status, r.expires_at AS expires_at, "
                "r.evidence_ids_json AS evidence ORDER BY id LIMIT 1000", owner=writes.owner_id, after=after))
            rows.extend(dict(r, evidence_ids=json.loads(r["evidence"] or "[]")) for r in page)
            if len(page) < 1000:
                return rows
            after = page[-1]["id"]
    with gateway.read_session() as session:
        return gateway.execute_read(session, read)


def safe_graph(writes, reads):
    payloads, structural = inventory(writes)
    owner = writes.owner_id
    safe, invalid, public_briefs = {}, [], set()
    # Canonical fetch enforces current lifecycle, source lineage and egress policy.
    for identity, payload in sorted(payloads.items()):
        if payload.get("owner_id") != owner or payload.get("egress_policy") != "shareable":
            continue
        if payload.get("node_type") in {"relation_assertion", "idea_brief_version"}:
            continue
        try:
            view = reads.fetch(identity, owner_id=owner)
        except GraphReadNotFoundError:
            continue
        if view.fields.get("egress_policy") != "shareable" or payload.get("status") in EXCLUDED:
            continue
        safe[identity] = {"id": identity, "kind": view.node_type,
                          "revision": payload.get("revision", 0)}
    # A source body/revision is never exposed independently of its current parent.
    for identity in list(safe):
        payload = payloads[identity]
        parent = payload.get("source_id") if payload.get("node_type") == "source_revision" else payload.get("source_revision_id") if payload.get("node_type") == "content_chunk" else None
        if parent is not None and (parent not in safe or (payload.get("node_type") == "source_revision" and payloads[parent].get("current_revision_id") != identity)):
            safe.pop(identity, None)
    for identity in list(safe):
        payload = payloads[identity]
        if payload.get("node_type") == "content_chunk" and payload.get("source_revision_id") not in safe:
            safe.pop(identity, None)
        if payload.get("node_type") == "idea":
            try:
                public_briefs.add(reads.fetch_idea_brief(identity, owner_id=owner)["brief_id"])
            except GraphReadNotFoundError:
                pass
    for identity in sorted(public_briefs):
        payload = payloads.get(identity)
        if payload and payload.get("egress_policy") == "shareable" and payload.get("based_on_idea_id") in safe:
            safe[identity] = {"id": identity, "kind": "idea_brief_version", "revision": payload["revision"]}
    # Strip indirect references to private/obsolete source material to a fixed point.
    changed = True
    while changed:
        changed = False
        for identity in list(safe):
            payload = payloads[identity]
            dependencies = ([payload[k] for k in ("claim_id", "material_id") if payload.get(k)]
                            if payload.get("node_type") == "evidence" else payload.get("evidence_ids", ()) if payload.get("node_type") == "claim" else ())
            invalid_source = False
            if payload.get("node_type") == "evidence" and payload.get("source_revision_id"):
                revision = payloads.get(payload["source_revision_id"], {})
                source_id = revision.get("source_id")
                invalid_source = source_id not in safe or payloads[source_id].get("current_revision_id") != revision.get("id")
            # Evidence may explicitly share citation metadata without sharing the
            # underlying chunk/body. Those private support IDs never leave here.
            if invalid_source or any(d not in safe for d in dependencies):
                safe.pop(identity)
                changed = True
    edges = set()
    for identity in public_briefs:
        if identity in safe:
            idea_id = payloads[identity]["based_on_idea_id"]
            edges.add((identity, "BASED_ON_IDEA", idea_id, "management"))
    for identity, payload in sorted(payloads.items()):
        if payload.get("node_type") != "relation_assertion" or payload.get("egress_policy") != "shareable":
            continue
        source, target = payload.get("source_id"), payload.get("target_id")
        # Do not expose invalid relationships to hidden endpoints or hidden support.
        if source not in safe or target not in safe or any(e not in safe for e in payload.get("evidence_ids", ())):
            continue
        if payload.get("based_on_brief_id") and payload["based_on_brief_id"] not in public_briefs:
            continue
        try:
            step = reads.fetch_relation_assertion(identity, owner_id=owner)
        except GraphReadNotFoundError:
            state = payload.get("status") if payload.get("status") in EXCLUDED else "invalid_support_or_lineage"
            expiry = payload.get("expires_at")
            if expiry and datetime.fromisoformat(expiry) <= datetime.now(timezone.utc):
                state = "expired"
            invalid.append({"id": identity, "state": state, "source_id": source, "target_id": target})
            continue
        if step.source_id not in safe or step.target_id not in safe:
            continue
        edges.add((step.source_id, step.predicate, step.target_id, "semantic"))
        safe[identity] = {"id": identity, "kind": "relation_assertion", "revision": payload.get("revision", 0)}
    for relation in legacy_relations(writes):
        source, target = relation["source_id"], relation["target_id"]
        if source not in safe or target not in safe or any(e not in safe for e in relation.get("evidence_ids", ())):
            continue
        expiry = relation.get("expires_at")
        expired = bool(expiry and datetime.fromisoformat(str(expiry)) <= datetime.now(timezone.utc))
        if relation.get("status") not in {"proposed", "inferred", "confirmed"} or expired or not relation.get("evidence_ids"):
            invalid.append({"source_id": source, "target_id": target, "relation": relation["relation"],
                            "state": "expired" if expired else "inactive_or_unsubstantiated"})
        else:
            edges.add((source, relation["relation"], target, "semantic"))
    for source, relation, target in structural:
        if source in safe and target in safe:
            if relation in MANAGEMENT or relation in GROUNDING:
                category = "management" if relation in MANAGEMENT else "grounding"
                edges.add((source, relation, target, category))
    projected_edges = [{"source_id": s, "relation": r, "target_id": t, "category": c}
                       for s, r, t, c in sorted(edges)]
    degree, incoming, outgoing, categories = Counter(), Counter(), Counter(), Counter()
    adjacency = {identity: set() for identity in safe}
    for s, _, t, category in edges:
        degree[s] += 1
        degree[t] += 1
        outgoing[s] += 1
        incoming[t] += 1
        categories[s, category] += 1
        categories[t, category] += 1
        adjacency[s].add(t)
        adjacency[t].add(s)
    nodes = [dict(n, degree=degree[identity], in_degree=incoming[identity], out_degree=outgoing[identity],
                  degree_by_category={c: categories[identity, c] for c in ("semantic", "grounding", "management")})
             for identity, n in safe.items()]
    components, seen = [], set()
    for identity in safe:
        if identity in seen:
            continue
        pending, members = [identity], set()
        while pending:
            item = pending.pop()
            if item in members:
                continue
            members.add(item)
            pending.extend(adjacency[item] - members)
        seen.update(members)
        components.append({"id": min(members), "node_ids": sorted(members), "size": len(members)})
    # Component members are a separate pageable collection; no unbounded ID array.
    component_members = [{"component_id": c["id"], "node_id": i} for c in components for i in c["node_ids"]]
    component_summaries = [{"id": c["id"], "size": c["size"]} for c in components]
    # Shared classifications are investigation hints, never proof of REUSES.
    classifications = {}
    for s, r, t, _ in edges:
        if r == "CLASSIFIED_AS":
            classifications.setdefault(t, set()).add(s)
    relation_candidates = []
    for facet, members in sorted(classifications.items()):
        for source in sorted(members):
            if safe[source]["kind"] != "idea":
                continue
            for target in sorted(members - {source}):
                if safe[target]["kind"] not in {"asset", "idea"}:
                    continue
                relation_candidates.append({"source_id": source, "target_id": target,
                    "relation": "REUSES", "basis": "ai_inference", "confidence": None,
                    "support": {"facet_id": facet, "existing_relations": ["CLASSIFIED_AS"]},
                    "duplicate": (source, "REUSES", target, "semantic") in edges,
                    "state": "unresolved", "recommended_action": "find_exact_brief_or_evidence_support"})
    collections = {"nodes": nodes, "edges": projected_edges,
                   "isolated": [n for n in nodes if n["degree"] == 0],
                   "semantic_isolated": [n for n in nodes if n["degree_by_category"]["semantic"] == 0],
                   "low_degree": [n for n in nodes if 0 < n["degree"] <= 2],
                   "components": component_summaries, "component_members": component_members,
                   "invalid_relations": invalid, "relation_candidates": relation_candidates,
                   "test_candidates": [n for n in nodes if synthetic_provenance(payloads[n["id"]])]}
    summary = {"node_count": len(nodes), "edge_count": len(edges),
               "node_types": dict(sorted(Counter(n["kind"] for n in nodes).items())),
               "edge_categories": dict(sorted(Counter(c for *_, c in edges).items())),
               "isolated_count": len(collections["isolated"]), "component_count": len(components)}
    summary["isolated_node_types"] = dict(sorted(Counter(n["kind"] for n in collections["isolated"]).items()))
    summary["edge_count_kind"] = "distinct_current_projected_relations"
    digest = sha256(json.dumps(collections, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"scope": "current_shareable_graph", "snapshot_id": digest, "summary": summary,
            "collections": collections}, payloads, structural


def audit_page(graph, *, collection="nodes", limit=50, cursor=None):
    if collection not in COLLECTIONS or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid audit page")
    offset = 0
    if cursor is not None:
        if not isinstance(cursor, str) or len(cursor) > 150:
            raise ValueError("invalid audit cursor")
        parts = cursor.split(":")
        if len(parts) != 3 or parts[:2] != [graph["snapshot_id"], collection]:
            raise ValueError("audit changed; restart pagination")
        if not parts[2].isdigit():
            raise ValueError("invalid audit cursor")
        offset = int(parts[2])
    items = graph["collections"][collection]
    if offset > len(items):
        raise ValueError("invalid audit cursor")
    end = offset + limit
    return {k: graph[k] for k in ("scope", "snapshot_id", "summary")} | {
        "collection": collection, "total": len(items), "results": items[offset:end],
        "next_cursor": f'{graph["snapshot_id"]}:{collection}:{end}' if end < len(items) else None}
