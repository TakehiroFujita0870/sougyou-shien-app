"""Management MCP boundary: explicit targets, owner auth, safe output, no raw graph dumps."""
from hashlib import sha256
import json
import os

from .founder_graph_mcp import McpReadError
from .founder_graph_mcp_annotations import mcp_tool_annotations
from .founder_graph_mcp_research import _relation_candidate_manifest_schema
from .graph_admin_audit import COLLECTIONS, audit_page, safe_graph
from .graph_admin_cleanup import GraphCleanupService, retirement_impact, retire, synthetic_lineage


def validate_input(value, schema):
    """Validate this catalog's bounded JSON subset without another dependency."""
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict) or not set(schema.get("required", ())).issubset(value):
            raise ValueError("invalid object")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError("unknown fields")
        for key, item in value.items():
            if key in properties:
                validate_input(item, properties[key])
    elif kind == "array":
        if not isinstance(value, list) or not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 20):
            raise ValueError("invalid array")
        for item in value:
            validate_input(item, schema["items"])
    elif kind == "string":
        if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 200):
            raise ValueError("invalid string")
    elif kind == "integer":
        if type(value) is not int or not schema.get("minimum", 0) <= value <= schema.get("maximum", 2**31):
            raise ValueError("invalid integer")
    elif kind == "boolean" and type(value) is not bool:
        raise ValueError("invalid boolean")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("invalid enum")


def definitions():
    text = {"type": "string", "minLength": 1, "maxLength": 200}
    manifest = {"type": "object", "required": ["idea_id", "brief_id", "expected_revision", "candidates"],
        "properties": {"idea_id": text, "brief_id": text,
            "expected_revision": {"type": "integer", "minimum": 1},
            "candidates": {"type": "array", "maxItems": 20,
                           "items": _relation_candidate_manifest_schema()["properties"]["candidates"]["items"]}},
        "additionalProperties": False}
    operation = {"type": "object", "required": ["action"], "properties": {
        "action": {"type": "string", "enum": ["relation", "archive", "restore"]},
        "manifest": manifest, "candidate_id": text, "node_id": text,
        "expected_revision": {"type": "integer", "minimum": 0}}, "additionalProperties": False}
    specifications = [
        ("audit_graph", "本人の共有可能な現行グラフを全件監査。本文や非公開ノードの件数は返しません。各collectionをnext_cursorがなくなるまで取得してください。", True,
         {"collection": {"type": "string", "enum": list(COLLECTIONS)},
          "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": text}, []),
        ("propose_graph_cleanup", "監査と関係候補を確認します。既存Briefの正確な引用または章位置と根拠を指定した候補は共通評価器で検証し、根拠不足はunresolvedにします。未指定なら孤立ノードを要検討として返し、関係は捏造しません。", True,
         {"manifests": {"type": "array", "maxItems": 20, "items": manifest}}, []),
        ("apply_graph_cleanup", "明示した最大20変更をdry-runで確認。適用時はdry_run=falseとsnapshot_idと一意キーが必要。試験データの保管・復元には別途サーバー削除権限が必要。本文・共有範囲は変更せず、結果と変更前後件数を監査記録へ保存します。", False,
         {"operations": {"type": "array", "minItems": 1, "maxItems": 20, "items": operation},
          "snapshot_id": text, "idempotency_key": text, "dry_run": {"type": "boolean", "default": True}},
         ["operations", "snapshot_id", "idempotency_key"]),
    ]
    return tuple({"name": name, "description": description, "readOnly": readonly,
        "annotations": mcp_tool_annotations(read_only=readonly, destructive=not readonly),
        "inputSchema": {"type": "object", "properties": properties, "required": required,
                        "additionalProperties": False}}
        for name, description, readonly, properties, required in specifications)


class GraphAdminSurface:
    def __init__(self, writes, reads, processor=None, *, allow_delete=None):
        self.writes, self.reads = writes, reads
        self.cleanup = GraphCleanupService(writes, reads, processor)
        self.allow_delete = (os.environ.get("NEBULA_MCP_ALLOW_CLEANUP_DELETE") == "1"
                             if allow_delete is None else allow_delete is True)
        self._memory_journal = {}

    def tool_definitions(self):
        return definitions()

    def call(self, name, arguments, *, owner_id):
        if owner_id != self.writes.owner_id:
            raise McpReadError("owner_mismatch", "本人限定の操作です。")
        definition = next((d for d in definitions() if d["name"] == name), None)
        if definition is None:
            raise McpReadError("unknown_tool", "管理機能が見つかりません。")
        try:
            # Validate the actual ingress, not only the host-displayed schema.
            if len(json.dumps(arguments, ensure_ascii=False).encode("utf-8")) > 65536:
                raise ValueError("input limit")
            validate_input(arguments, definition["inputSchema"])
            if name == "audit_graph":
                graph, _, _ = safe_graph(self.writes, self.reads)
                return audit_page(graph, **arguments)
            if name == "propose_graph_cleanup":
                manifests = arguments.get("manifests", [])
                if sum(len(m["candidates"]) for m in manifests) > 20:
                    raise ValueError("candidate limit")
                graph, proposals = self.cleanup.propose(manifests)
                # All unresolved nodes remain pageable through audit_graph.
                return {"snapshot_id": graph["snapshot_id"], "summary": graph["summary"],
                        "candidates": proposals or graph["collections"]["relation_candidates"][:20],
                        "candidate_total": len(proposals or graph["collections"]["relation_candidates"]),
                        "unresolved": graph["collections"]["isolated"][:20],
                        "unresolved_total": len(graph["collections"]["isolated"])}
            return self._apply(arguments)
        except McpReadError:
            raise
        except Exception:
            # Never expose provider errors, supplied quotes, private IDs or existence.
            raise McpReadError("cleanup_unavailable", "対象・版・権限を確認し、監査を取り直してください。") from None

    def _journal(self, key, fingerprint, result=None):
        gateway = getattr(self.writes, "gateway", None)
        if gateway is None:
            old = self._memory_journal.get(key)
            if old and old[0] != fingerprint:
                raise ValueError("idempotency conflict")
            if result is not None:
                self._memory_journal[key] = (fingerprint, result)
            return old[1] if old else None
        def run(tx):
            gateway._lock_assertion_families_tx(tx, {"graph-cleanup-journal"})
            row = tx.run("MATCH (a:FounderGraphCleanupAudit {owner_id: $owner, key: $key}) "
                         "RETURN a.fingerprint AS fingerprint, a.result AS result", owner=self.writes.owner_id, key=key).single()
            if row and row["fingerprint"] != fingerprint:
                raise ValueError("idempotency conflict")
            if result is not None:
                tx.run("MERGE (a:FounderGraphCleanupAudit {owner_id: $owner, key: $key}) "
                       "SET a.fingerprint=$fingerprint, a.result=$result, a.updated_at=datetime()",
                       owner=self.writes.owner_id, key=key, fingerprint=fingerprint,
                       result=json.dumps(result, sort_keys=True)).consume()
            return json.loads(row["result"]) if row else None
        with gateway._session() as session:
            return gateway._execute_write(session, run)

    def _apply(self, arguments):
        operations, dry = arguments["operations"], arguments.get("dry_run", True)
        # No caller-controlled owner/permission fields exist in this schema.
        if not dry and any(op["action"] != "relation" for op in operations) and not self.allow_delete:
            raise McpReadError("permission_denied", "試験データの削除・復元権限が設定されていません。")
        key = arguments["idempotency_key"]
        fingerprint = sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        previous = None
        if not dry:
            previous = self._journal(key, fingerprint)
            if previous and previous.get("state") == "complete":
                # Cached IDs could have become private. Return only the safe receipt marker.
                return {"replayed": True, "state": "complete", "idempotency_key": key}
        before, payloads, structural = safe_graph(self.writes, self.reads)
        if not previous and before["snapshot_id"] != arguments["snapshot_id"]:
            raise ValueError("stale audit")
        outcomes = []
        if not dry and not previous:
            self._journal(key, fingerprint, {"state": "started", "before": before["summary"]})
        for index, op in enumerate(operations):
            outcome = {"index": index, "action": op["action"]}
            saved = previous.get("results", []) if previous else []
            if index < len(saved):
                outcomes.append(dict(outcome, state=saved[index]["state"], replayed=True))
                continue
            try:
                if op["action"] == "relation":
                    if set(op) != {"action", "manifest", "candidate_id"} or len(op["manifest"]["candidates"]) != 1:
                        raise ValueError("explicit single candidate required")
                    _, proposed = self.cleanup.propose([op["manifest"]])
                    candidate = next(p for p in proposed if p.get("id") == op["candidate_id"])
                    outcome["state"] = "duplicate" if candidate["duplicate"] else "would_apply"
                    if not dry:
                        outcome.update(self.cleanup.apply_relation(op["manifest"], op["candidate_id"]))
                else:
                    if set(op) != {"action", "node_id", "expected_revision"}:
                        raise ValueError("explicit target required")
                    payload = payloads.get(op["node_id"])
                    if not payload or payload.get("egress_policy") != "shareable":
                        raise ValueError("target unavailable")
                    completed = self.writes.get_write_receipt(f'{key}:{index}') if not dry else None
                    if completed:
                        current = payloads.get(completed.target_id)
                        if not current or current.get("egress_policy") != "shareable":
                            raise ValueError("target unavailable")
                        receipt = retire(self.writes, op["node_id"], op["expected_revision"],
                                         f'{key}:{index}', restore=op["action"] == "restore")
                        outcomes.append(dict(outcome, state="applied", replayed=True,
                                             target_id=receipt["target_id"], revision=receipt["revision"]))
                        continue
                    if payload.get("revision", 0) != op["expected_revision"]:
                        raise ValueError("stale target")
                    if op["action"] == "archive":
                        outcome["impact"] = retirement_impact(payloads, structural, op["node_id"])
                    elif payload.get("status") != "archived" or not synthetic_lineage(payloads, op["node_id"]):
                        raise ValueError("restore unavailable")
                    outcome["state"] = "would_" + op["action"]
                    if not dry:
                        receipt = retire(self.writes, op["node_id"], op["expected_revision"],
                                         f'{key}:{index}', restore=op["action"] == "restore")
                        outcome.update(state="applied", target_id=receipt["target_id"], revision=receipt["revision"])
            except Exception:
                outcome = {"index": index, "action": op["action"], "state": "unresolved"}
            outcomes.append(outcome)
            if not dry:
                self._journal(key, fingerprint, {"state": "in_progress", "before": before["summary"], "results": outcomes})
        after, _, _ = safe_graph(self.writes, self.reads)
        failed = sum(o["state"] == "unresolved" for o in outcomes)
        result = {"state": "complete", "outcome": "partial" if failed else "success", "unresolved_count": failed,
                  "resumed": bool(previous),
                  "dry_run": dry, "results": outcomes,
                  "before": before["summary"], "after": after["summary"], "snapshot_id": after["snapshot_id"]}
        if not dry:
            self._journal(key, fingerprint, result)
        return result
