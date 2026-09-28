"""Owner-scoped, field-limited projection for the local three-tab home."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Mapping, Protocol, Sequence

from .founder_graph_neo4j_idea_brief import _decode_persisted_idea_brief
from .founder_graph_neo4j import Neo4jGraphGateway
from .founder_graph_neo4j_read import Neo4jGraphReadService
from .founder_graph_neo4j_idea import decode_persisted_idea
from .founder_graph_lifecycle_resolver import resolve_restored_idea_reference
from .founder_graph_write import GraphWritePort, WriteReceipt
from .founder_graph import AssetKind
from .idea_brief_read_projection import project_idea_brief_for_read


_KINDS = ("idea", "asset", "owner_profile")
_EXCLUDED = frozenset({"deleted", "archived", "superseded", "retracted", "expired", "cancelled", "revoked"})
_EMPTY = {"status": "empty", "ideas": [], "assets": [], "profile": None}


class HomeStore(Protocol):
    def read_home(self, owner_id: str) -> Sequence[Mapping[str, Any]]: ...


class Neo4jHomeStore:
    _QUERY = (
        "MATCH (n) WHERE n.owner_id = $owner_id AND n.node_type IN $node_types "
        "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
        "n.status AS status, n.payload_json AS payload_json"
    )
    _BRIEFS = (
        "MATCH (b:IdeaBriefVersion {owner_id: $owner_id}) "
        "RETURN b.id AS id, b.owner_id AS owner_id, b.idea_lineage_root_id AS root_id, "
        "b.revision AS revision, b.supersedes_id AS supersedes_id, b.payload_json AS payload_json "
        "ORDER BY b.idea_lineage_root_id, b.revision DESC LIMIT 501"
    )

    def __init__(self, driver: Any, *, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    def read_home(self, owner_id: str) -> Sequence[Mapping[str, Any]]:
        with self._driver.session(database=self._database) as session:
            return tuple(dict(row) for row in session.run(self._QUERY, owner_id=owner_id, node_types=list(_KINDS)))

    def read_briefs(self, owner_id: str) -> Sequence[Mapping[str, Any]]:
        with self._driver.session(database=self._database) as session:
            return tuple(dict(row) for row in session.run(self._BRIEFS, owner_id=owner_id))

    def read_citations(self, owner_id: str, evidence_ids: Sequence[str]) -> Mapping[str, Mapping[str, str]]:
        """Project only current, owner-bound, shareable source URL/title metadata."""
        service = Neo4jGraphReadService(Neo4jGraphGateway(self._driver, owner_id, database=self._database))
        result = {}
        for evidence_id in dict.fromkeys(evidence_ids):
            citation = service.project_evidence_citation(evidence_id, owner_id=owner_id)
            if citation is not None:
                result[evidence_id] = citation
        return result


class LocalAssetWriter:
    """Owner-scoped edit seam for the common Asset card form."""

    def __init__(self, writes: GraphWritePort) -> None:
        if not callable(getattr(writes, "revise_asset", None)):
            raise TypeError("asset writer must support canonical revisions")
        self._writes = writes

    def save(
        self,
        asset_id: str,
        *,
        name: str,
        description: str,
        expected_revision: int,
        idempotency_key: str,
        kind: AssetKind | None = None,
    ) -> WriteReceipt:
        arguments = dict(
            asset_id=asset_id,
            name=name,
            description=description,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )
        if kind is not None:
            arguments["kind"] = kind
        return self._writes.revise_asset(**arguments)


class LocalIdeaWriter:
    """Owner-scoped title/description revisions for the selected Idea."""

    def __init__(self, writes: Any) -> None:
        if not callable(getattr(writes, "revise_idea", None)):
            raise TypeError("idea writer must support canonical revisions")
        self._writes = writes

    def save(
        self, idea_id: str, *, title: str, description: str,
        expected_revision: int, idempotency_key: str,
    ) -> WriteReceipt:
        return self._writes.revise_idea(
            idea_id=idea_id, title=title, description=description,
            expected_revision=expected_revision, idempotency_key=idempotency_key,
        )


def _text(value: Any, *, required: bool = False) -> str:
    if not isinstance(value, str):
        if required:
            raise ValueError("required display field is missing")
        return ""
    text = value.strip()
    if required and not text:
        raise ValueError("required display field is empty")
    return text


def _timestamp(payload: Mapping[str, Any]) -> datetime:
    raw = payload.get("updated_at") or payload.get("created_at")
    if not isinstance(raw, str):
        raise ValueError("timestamp is missing")
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _research_status(payload: Mapping[str, Any], row_status: Any) -> str:
    payload_status = payload.get("status")
    if isinstance(payload_status, str) and isinstance(row_status, str):
        if payload_status.strip().casefold() != row_status.strip().casefold():
            return "unknown"
    raw_status = payload_status if isinstance(payload_status, str) else row_status
    if isinstance(raw_status, str) and raw_status.strip().casefold() == "draft":
        return "unresearched"
    return "unknown"


def _decode_home_brief_row(row: Mapping[str, Any], *, owner_id: str):
    """Adapt the home query projection to the canonical persisted Brief decoder."""
    payload = json.loads(row["payload_json"])
    return _decode_persisted_idea_brief({
        "id": row["id"],
        "owner_id": row["owner_id"],
        "node_type": "idea_brief_version",
        "revision": row["revision"],
        "idea_lineage_root_id": row["root_id"],
        "supersedes_id": row.get("supersedes_id", payload.get("supersedes_id")),
        "payload_json": row["payload_json"],
    }, owner_id=owner_id, legacy_label_checked=True)


def _idea_lifecycle_aliases(ideas: Mapping[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for idea in ideas.values():
        chain = [idea]
        seen = {idea.id}
        while chain[-1].supersedes_id is not None:
            parent = ideas.get(chain[-1].supersedes_id)
            if parent is None or parent.id in seen:
                break
            chain.append(parent)
            seen.add(parent.id)
        else:
            chain.reverse()
            current = chain[-1]
            while True:
                children = [candidate for candidate in ideas.values() if candidate.supersedes_id == current.id]
                if len(children) > 1:
                    break
                if not children:
                    for candidate in chain:
                        resolved = resolve_restored_idea_reference(candidate.id, chain)
                        if resolved is not None:
                            aliases[candidate.id] = resolved.id
                    break
                child = children[0]
                if child.revision != current.revision + 1:
                    break
                chain.append(child)
                seen.add(child.id)
                current = child
    return aliases


def _decode_lifecycle_idea_families(
    payloads: Mapping[str, Mapping[str, Any]], *, owner_id: str,
) -> dict[str, Any]:
    markers = {
        identity for identity, payload in payloads.items()
        if isinstance(payload.get("provenance"), Mapping)
        and payload["provenance"].get("operation") in {"archive_idea", "restore_idea", "revise_idea"}
    }
    if not markers:
        return {}
    family_ids: set[str] = set()
    for marker in markers:
        current = marker
        seen = set()
        while current in payloads and current not in seen:
            seen.add(current)
            family_ids.add(current)
            parent = payloads[current].get("supersedes_id")
            if not isinstance(parent, str):
                break
            current = parent
        pending = [marker]
        while pending:
            parent_id = pending.pop()
            children = [
                identity for identity, payload in payloads.items()
                if payload.get("supersedes_id") == parent_id and identity not in family_ids
            ]
            family_ids.update(children)
            pending.extend(children)
    decoded = {}
    for identity in family_ids:
        payload = payloads.get(identity)
        if payload is None:
            continue
        persisted_payload = dict(payload)
        persisted_payload.pop("node_type", None)
        try:
            decoded[identity] = decode_persisted_idea({
                "id": identity,
                "owner_id": owner_id,
                "node_type": "idea",
                "revision": payload.get("revision"),
                "payload_json": json.dumps(persisted_payload, ensure_ascii=False),
            }, owner_id=owner_id, expected_id=identity)
        except (TypeError, ValueError):
            return {}
    return decoded


def read_local_home(store: HomeStore, *, owner_id: str, storage_status: str = "running") -> dict[str, Any]:
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise ValueError("owner_id is required")
    if storage_status == "stopped":
        return {**_EMPTY, "status": "stopped"}
    if storage_status != "running":
        return {**_EMPTY, "status": "failed"}

    try:
        records = []
        ids = set()
        idea_payloads: dict[str, Mapping[str, Any]] = {}
        idea_nodes: dict[str, Any] = {}
        idea_statuses: dict[str, Any] = {}
        superseded = set()
        superseded_assets = set()
        for row in store.read_home(owner_id):
            identity = row["id"]
            kind = row["node_type"]
            if row["owner_id"] != owner_id or kind not in _KINDS or not isinstance(identity, str) or not identity or identity in ids:
                raise ValueError("unexpected node identity")
            ids.add(identity)
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict) or payload.get("id") != identity or payload.get("owner_id") != owner_id:
                raise ValueError("unexpected payload identity")
            if kind == "idea":
                idea_payloads[identity] = payload
                idea_statuses[identity] = row.get("status")
            if kind == "idea" and isinstance(payload.get("supersedes_id"), str):
                superseded.add(payload["supersedes_id"])
            if kind == "asset" and isinstance(payload.get("supersedes_id"), str):
                superseded_assets.add(payload["supersedes_id"])
            if kind == "asset" and payload.get("name") == "自己紹介" and isinstance(payload.get("details"), dict):
                prior = payload["details"].get("supersedes_id")
                if isinstance(prior, str):
                    superseded_assets.add(prior)
            if str(row.get("status") or "").lower() in _EXCLUDED:
                continue
            records.append((identity, kind, payload, _timestamp(payload)))

        idea_nodes = _decode_lifecycle_idea_families(idea_payloads, owner_id=owner_id)
        idea_aliases = _idea_lifecycle_aliases(idea_nodes)

        briefs_by_root = {}
        read_briefs = getattr(store, "read_briefs", None)
        if callable(read_briefs):
            brief_rows = tuple(read_briefs(owner_id))
            if len(brief_rows) > 500:
                raise ValueError("brief display limit exceeded")
            for row in brief_rows:
                if row.get("owner_id") != owner_id or not isinstance(row.get("root_id"), str):
                    raise ValueError("unexpected brief identity")
                brief = _decode_home_brief_row(row, owner_id=owner_id)
                previous = briefs_by_root.get(brief.idea_lineage_root_id)
                if previous is None or brief.revision > previous.revision:
                    briefs_by_root[brief.idea_lineage_root_id] = brief
                elif brief.revision == previous.revision and brief.id != previous.id:
                    raise ValueError("duplicate latest brief revision")

        def idea_root(identity: str) -> str:
            current = identity
            seen = set()
            for _ in range(32):
                if current in seen:
                    raise ValueError("idea lineage cycle")
                seen.add(current)
                payload = idea_payloads.get(current)
                if payload is None:
                    raise ValueError("idea lineage is incomplete")
                parent = payload.get("supersedes_id")
                if not parent:
                    return current
                if not isinstance(parent, str):
                    raise ValueError("idea lineage is invalid")
                current = parent
            raise ValueError("idea lineage exceeds display limit")

        ideas = []
        assets = []
        profile = None
        for identity, kind, payload, timestamp in sorted(records, key=lambda item: (item[3], item[0]), reverse=True):
            if kind == "idea":
                if identity in superseded:
                    continue
                revision = payload.get("revision", 0)
                if type(revision) is not int or revision < 0:
                    raise ValueError("unexpected Idea revision")
                display = {
                    "id": identity,
                    "title": _text(payload.get("title"), required=True),
                    "summary": _text(payload.get("summary")),
                    "description": _text(payload.get("description")),
                    "revision": revision,
                    "research_status": _research_status(payload, idea_statuses.get(identity)),
                }
                brief = briefs_by_root.get(idea_root(identity)) if briefs_by_root else None
                if brief is not None and idea_aliases.get(brief.based_on_idea_id, brief.based_on_idea_id) == identity:
                    report_projection = project_idea_brief_for_read(brief.report_markdown, brief.sections)
                    display["brief_sections"] = list(report_projection.section_contents)
                    display["brief_revision"] = brief.revision
                    if brief.report_markdown is not None:
                        display["report_markdown"] = brief.report_markdown
                        display["report_projection"] = report_projection.metadata
                    if brief.origin is not None:
                        display["brief_origin"] = brief.origin
                    evidence_ids = tuple(dict.fromkeys(
                        evidence_id for section in brief.sections for evidence_id in section.evidence_ids
                    ))
                    read_citations = getattr(store, "read_citations", None)
                    citation_map = read_citations(owner_id, evidence_ids) if callable(read_citations) else {}
                    chapter_citations: list[list[dict[str, str]]] = [[] for _ in range(8)]
                    for section in brief.sections:
                        if 0 <= section.index < 8:
                            chapter_citations[section.index] = [
                                {key: citation_map[evidence_id][key] for key in ("url", "title")}
                                for evidence_id in section.evidence_ids
                                if evidence_id in citation_map
                            ]
                    display["brief_citations"] = chapter_citations
                    # Run references alone are not evidence of completed research.
                    has_citations = any(display["brief_citations"])
                    # Only the gated researched-save route retains Run references.
                    # Ordinary draft edits clear them; expiry does not erase history.
                    if brief.research_run_ids and all(content.strip() for content in report_projection.section_contents):
                        display["research_status"] = "researched" if has_citations else "research_sources_missing"
                    elif brief.origin == "prior_research_import":
                        display["research_status"] = "prior_research_import" if has_citations else "prior_research_sources_missing"
                elif brief is not None and isinstance(payload.get("provenance"), Mapping) and payload["provenance"].get("operation") == "revise_idea":
                    # Research for the prior content remains in history, not current.
                    display["research_status"] = "unresearched"
                ideas.append((timestamp, display))
            elif kind == "asset":
                if identity in superseded_assets:
                    continue
                assets.append((timestamp, {
                    "id": identity,
                    "name": _text(payload.get("name"), required=True),
                    "kind": _text(payload.get("kind")),
                    "description": _text(payload.get("description")),
                    "revision": payload.get("revision", 1),
                    "egress_policy": _text(payload.get("egress_policy")) or "local_only",
                }))
            elif profile is None:
                profile = {"display_name": _text(payload.get("display_name"))}

        return {
            "status": "ready" if ideas or assets or profile else "empty",
            "ideas": [item for _, item in ideas],
            "assets": [item for _, item in assets],
            "profile": profile,
        }
    except Exception:
        return {**_EMPTY, "status": "failed"}
