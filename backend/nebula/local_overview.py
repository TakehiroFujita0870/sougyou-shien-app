"""Owner-scoped overview projection for the persisted Founder Graph format.

The current graph stores Idea, Person, Asset, and ReportVersion as direct nodes.
Their display fields and timestamps live in ``payload_json``; this module does
not assume the planned anchor/current-revision relationship model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Literal, Mapping, Protocol, Sequence


EntityKind = Literal["idea", "person", "asset"]
OverviewKind = Literal["idea", "person", "asset", "report_version"]
OVERVIEW_RECENT_LIMIT = 10
REPORT_DISPLAY_TITLE = "調査レポート"
COUNT_BASIS = "stored_active_records"
_NODE_TYPES: tuple[OverviewKind, ...] = ("idea", "person", "asset", "report_version")
_EXCLUDED_STATUSES = frozenset({"deleted", "archived", "superseded", "retracted", "expired", "cancelled", "revoked"})
_TITLE_FIELDS: dict[EntityKind, str] = {"idea": "title", "person": "name", "asset": "name"}


class OverviewReadError(RuntimeError):
    """Raised when persisted records do not satisfy the safe read contract."""


class OverviewDriver(Protocol):
    def session(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class StoredOverviewNode:
    id: str
    owner_id: str
    node_type: str
    status: str | None
    revision: int
    payload_json: str


class OverviewStore(Protocol):
    """Read-only storage contract returning actual persisted node records."""

    def read_overview(self, owner_id: str) -> Sequence[StoredOverviewNode]: ...


class Neo4jOverviewStore:
    """Minimal adapter for the current owner-scoped node/payload schema."""

    _QUERY = (
        "MATCH (n) WHERE n.owner_id = $owner_id AND n.node_type IN $node_types "
        "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
        "n.status AS status, n.revision AS revision, n.payload_json AS payload_json"
    )

    def __init__(self, driver: OverviewDriver, *, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    def read_overview(self, owner_id: str) -> Sequence[StoredOverviewNode]:
        with self._driver.session(database=self._database) as session:
            rows = session.run(self._QUERY, owner_id=owner_id, node_types=list(_NODE_TYPES))
            return tuple(
                StoredOverviewNode(
                    id=_row_value(row, "id"),
                    owner_id=_row_value(row, "owner_id"),
                    node_type=_row_value(row, "node_type"),
                    status=_row_value(row, "status"),
                    revision=_row_value(row, "revision", 0),
                    payload_json=_row_value(row, "payload_json"),
                )
                for row in rows
            )


@dataclass(frozen=True, slots=True)
class RecentOverviewItem:
    id: str
    kind: OverviewKind
    title: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OverviewResult:
    status: Literal["ready", "stopped", "empty", "failed"]
    count_basis: Literal["stored_active_records"]
    counts: dict[str, int]
    recent: tuple[RecentOverviewItem, ...]


def read_local_overview(
    store: OverviewStore,
    *,
    owner_id: str,
    storage_status: str = "running",
    recent_limit: int = OVERVIEW_RECENT_LIMIT,
) -> OverviewResult:
    """Return record counts and recent safe titles without exposing payloads."""

    if not isinstance(owner_id, str) or not owner_id.strip():
        raise ValueError("owner_id is required")
    if (
        not isinstance(recent_limit, int)
        or isinstance(recent_limit, bool)
        or not 0 <= recent_limit <= OVERVIEW_RECENT_LIMIT
    ):
        raise ValueError(f"recent_limit must be between 0 and {OVERVIEW_RECENT_LIMIT}")
    empty_counts = _empty_counts()
    if storage_status == "stopped":
        return OverviewResult("stopped", COUNT_BASIS, empty_counts, ())
    if storage_status != "running":
        return OverviewResult("failed", COUNT_BASIS, empty_counts, ())

    try:
        nodes = tuple(store.read_overview(owner_id))
        seen_ids: set[str] = set()
        parsed: list[tuple[StoredOverviewNode, Mapping[str, Any], datetime]] = []
        superseded_ids: set[str] = set()

        for node in nodes:
            if node.owner_id != owner_id:
                raise OverviewReadError("overview store returned another owner's node")
            if node.node_type not in _NODE_TYPES:
                raise OverviewReadError("overview store returned an unsupported node type")
            if not node.id or node.id in seen_ids:
                raise OverviewReadError("overview store returned a missing or duplicate node id")
            seen_ids.add(node.id)
            payload = _payload(node.payload_json)
            if (
                payload.get("id") != node.id
                or payload.get("owner_id") != owner_id
            ):
                raise OverviewReadError("persisted payload identity does not match node properties")
            supersedes_id = payload.get("supersedes_id")
            if supersedes_id is None:
                supersedes_id = payload.get("parent_id")
            if isinstance(supersedes_id, str) and supersedes_id.strip():
                superseded_ids.add(supersedes_id)
            timestamp_value = payload.get("updated_at") if node.node_type == "idea" else None
            if not isinstance(timestamp_value, str) or not timestamp_value.strip():
                timestamp_value = payload.get("created_at")
            parsed.append((node, payload, _parse_timestamp(timestamp_value)))

        counts = _empty_counts()
        items: list[RecentOverviewItem] = []
        for node, payload, timestamp in parsed:
            kind = node.node_type
            if node.status is not None and node.status.lower() in _EXCLUDED_STATUSES:
                continue
            # Idea and report revision chains use supersedes_id/parent_id in
            # payloads. Only leaf records are current for this record list.
            if kind in {"idea", "report_version"} and node.id in superseded_ids:
                continue
            if kind == "report_version":
                title = REPORT_DISPLAY_TITLE
            else:
                title_value = payload.get(_TITLE_FIELDS[kind])
                if not isinstance(title_value, str) or not title_value.strip():
                    raise OverviewReadError("persisted node has no safe display title")
                title = title_value.strip()
            counts[f"{kind}_records"] += 1
            items.append(RecentOverviewItem(node.id, kind, title, timestamp))

        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        recent = tuple(items[:recent_limit])
        status = "empty" if not any(counts.values()) else "ready"
        return OverviewResult(status, COUNT_BASIS, counts, recent)
    except Exception:
        # Hide driver failures and payload values from the UI response.
        return OverviewResult("failed", COUNT_BASIS, empty_counts, ())


def _empty_counts() -> dict[str, int]:
    return {f"{node_type}_records": 0 for node_type in _NODE_TYPES}


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


def _payload(raw: str) -> Mapping[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise OverviewReadError("persisted node payload is missing")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise OverviewReadError("persisted node payload is invalid") from error
    if not isinstance(value, Mapping):
        raise OverviewReadError("persisted node payload must be an object")
    return value


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OverviewReadError("persisted node timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise OverviewReadError("persisted node timestamp is invalid") from error
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
