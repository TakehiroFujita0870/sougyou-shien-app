"""Owner-scoped lifecycle commands and deleted-record projection for local UI."""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .founder_graph_write import GraphWritePort, WriteReceipt
from .local_home import HomeStore, _timestamp, _text


class LocalRecordLifecycleWriter:
    """Expose only the four fixed Idea/Asset archive and restore commands."""

    _COMMANDS = {
        ("idea", "archive"): "archive_idea",
        ("idea", "restore"): "restore_idea",
        ("asset", "archive"): "archive_asset",
        ("asset", "restore"): "restore_asset",
    }

    def __init__(self, writes: GraphWritePort) -> None:
        if any(not callable(getattr(writes, name, None)) for name in self._COMMANDS.values()):
            raise TypeError("record lifecycle writer must support archive and restore commands")
        self._writes = writes

    def transition(
        self, kind: str, action: str, record_id: str, *,
        expected_revision: int, idempotency_key: str,
    ) -> WriteReceipt:
        method_name = self._COMMANDS.get((kind, action))
        if method_name is None:
            raise ValueError("unsupported record lifecycle command")
        method = getattr(self._writes, method_name)
        return method(
            record_id, expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )


def read_local_deleted_records(
    store: HomeStore,
    *,
    owner_id: str,
    storage_status: str = "running",
) -> dict[str, Any]:
    """Project only current archived Ideas and Assets through the local-home boundary."""
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise ValueError("owner_id is required")
    if storage_status == "stopped":
        return {"status": "stopped", "records": []}
    if storage_status != "running":
        return {"status": "failed", "records": []}
    try:
        rows = tuple(store.read_home(owner_id))
        by_id: dict[str, tuple[str, Mapping[str, Any], str]] = {}
        successors: set[str] = set()
        for row in rows:
            identity = row.get("id")
            kind = row.get("node_type")
            if (
                row.get("owner_id") != owner_id
                or not isinstance(identity, str) or not identity
                or identity in by_id
                or kind not in {"idea", "asset", "owner_profile"}
            ):
                raise ValueError("unexpected node identity")
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict) or payload.get("id") != identity or payload.get("owner_id") != owner_id:
                raise ValueError("unexpected node payload")
            row_status = row.get("status")
            payload_status = payload.get("status")
            if payload_status is not None and payload_status != row_status:
                raise ValueError("unexpected node status")
            status = str(row_status or "").casefold()
            by_id[identity] = (kind, payload, status)
            parent = payload.get("supersedes_id")
            if kind in {"idea", "asset"} and isinstance(parent, str):
                successors.add(parent)

        records = []
        for identity, (kind, payload, status) in by_id.items():
            if kind not in {"idea", "asset"} or status != "archived" or identity in successors:
                continue
            revision = payload.get("revision", 0 if kind == "idea" else 1)
            if type(revision) is not int or revision < (0 if kind == "idea" else 1):
                raise ValueError("unexpected record revision")
            title = _text(payload.get("title" if kind == "idea" else "name"), required=True)
            description = _text(payload.get("description"))
            records.append({
                "id": identity,
                "kind": kind,
                "title": title,
                "description": description,
                "revision": revision,
                "_sort": _timestamp(payload),
            })
        records.sort(key=lambda record: (record.pop("_sort"), record["id"]), reverse=True)
        return {"status": "ready" if records else "empty", "records": records}
    except Exception:
        return {"status": "failed", "records": []}
