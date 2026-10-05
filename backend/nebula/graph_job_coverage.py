"""Read-only coverage audit; never creates candidates or changes job state."""
from __future__ import annotations

import json
from types import SimpleNamespace

from .local_home import Neo4jHomeStore, read_local_home


def project_coverage(home, idea_payloads, briefs, jobs, *, limit=20, manual_relations=()):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("coverage limit must be between 1 and 20")
    if home.get("status") not in {"ready", "empty"}:
        raise ValueError("current home cannot be resolved")
    latest = {}
    for brief in briefs:
        root = brief["root_id"]
        if root not in latest or brief["revision"] > latest[root]["revision"]:
            latest[root] = brief
    by_brief = {job["brief_id"]: job for job in jobs}
    relations_by_brief = {}
    for relation in manual_relations:
        if relation.get("status") in {"active", "proposed"}:
            brief_id = relation.get("based_on_brief_id")
            relations_by_brief.setdefault(brief_id, set()).add((
                relation.get("source_id"), relation.get("predicate"), relation.get("target_id"),
            ))
    issues = []
    checked = 0
    for idea in home["ideas"]:
        if "brief_revision" not in idea:
            continue
        root, seen = idea["id"], set()
        while True:
            if root in seen or root not in idea_payloads:
                raise ValueError("current Idea lineage cannot be resolved")
            seen.add(root)
            parent = idea_payloads[root].get("supersedes_id")
            if not parent:
                break
            root = parent
        brief = latest[root]
        if brief["revision"] != idea["brief_revision"]:
            raise ValueError("current Brief revision differs")
        checked += 1
        job = by_brief.get(brief["id"])
        relation_count = len(relations_by_brief.get(brief["id"], ()))
        action = None
        if job is None:
            action = "manual_relations_without_job" if relation_count else "missing_job"
        elif job["state"] == "succeeded" and job.get("manifest") == "[]":
            action = "reviewed_without_candidates"
        if action:
            issues.append({"idea_id": idea["id"], "brief_id": brief["id"],
                           "state": job["state"] if job else "missing", "action": action,
                           "existing_relation_count": relation_count})
    return {"reports_checked": checked, "issues": issues[:limit],
            "truncated": len(issues) > limit}


def read_coverage(driver, *, owner_id, database="neo4j", limit=20):
    store = Neo4jHomeStore(driver, database=database)
    rows, briefs = store.read_home(owner_id), store.read_briefs(owner_id)
    snapshot = SimpleNamespace(read_home=lambda _: rows, read_briefs=lambda _: briefs,
                               read_citations=lambda *_: {})
    home = read_local_home(snapshot, owner_id=owner_id)
    payloads = {r["id"]: json.loads(r["payload_json"]) for r in rows
                if r["node_type"] == "idea" and r["owner_id"] == owner_id}
    with driver.session(database=database) as session:
        jobs = session.execute_read(lambda tx: tuple(dict(row) for row in tx.run(
            "MATCH (j:FounderGraphJob {owner_id: $owner}) RETURN j.brief_id AS brief_id, "
            "j.state AS state, j.candidate_manifest_json AS manifest", owner=owner_id)))
        relations = session.execute_read(lambda tx: tuple(json.loads(row["payload"]) for row in tx.run(
            "MATCH (r {owner_id: $owner, node_type: 'relation_assertion'}) "
            "RETURN r.payload_json AS payload", owner=owner_id)))
    return project_coverage(home, payloads, briefs, jobs, limit=limit, manual_relations=relations)
