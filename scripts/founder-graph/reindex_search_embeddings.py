"""Backfill local search vectors, with a guarded synthetic E5-base profile."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import monotonic, sleep
from typing import Any, Mapping
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dots.founder_graph_local_models import (  # noqa: E402
    E5_BASE_DIMENSIONS,
    E5_BASE_MODEL_ID,
    E5_BASE_MODEL_REVISION,
    LocalSearchModels,
)
from dots.founder_graph_runtime import (  # noqa: E402
    create_neo4j_driver_from_env,
    create_neo4j_graph_composition,
)


SYNTHETIC_OWNER_ID = "dots-synthetic-test"
SYNTHETIC_CONTAINER = "dots-chatgpt-synthetic-db"
SYNTHETIC_VOLUME = "dots-chatgpt-synthetic-neo4j-v2"
E5_BASE_PROPERTY = "e5base_synthetic_embedding"
E5_BASE_INDEX = "dots_founder_graph_vector_e5base_synthetic"
E5_BASE_HASH_PROPERTY = "e5base_synthetic_embedding_content_hash"
E5_BASE_MODEL_PROPERTY = "e5base_synthetic_embedding_model_id"
E5_BASE_REVISION_PROPERTY = "e5base_synthetic_embedding_model_revision"
E5_BASE_DIMENSIONS_PROPERTY = "e5base_synthetic_embedding_dimensions"
SMALL_INDEX = "dots_founder_graph_vector"
BATCH_SIZE = 32

_INSPECT_FORMAT = "{{json .Mounts}}|{{json .HostConfig.PortBindings}}|{{.State.Status}}"
_OWNER_CHECK_QUERY = (
    "MATCH (node) RETURN count(node) AS node_count, "
    "sum(CASE WHEN node.owner_id = $owner_id THEN 1 ELSE 0 END) AS owner_node_count"
)
_SEARCHABLE_NODES_QUERY = (
    "MATCH (node:FounderGraphSearchable) WHERE node.owner_id = $owner_id "
    "AND node.search_text IS NOT NULL AND node.search_text <> '' "
    "RETURN node.id AS id, node.search_text AS search_text, "
    f"node.{E5_BASE_PROPERTY} AS embedding, "
    f"node.{E5_BASE_HASH_PROPERTY} AS content_hash, "
    f"node.{E5_BASE_MODEL_PROPERTY} AS model_id, "
    f"node.{E5_BASE_REVISION_PROPERTY} AS model_revision, "
    f"node.{E5_BASE_DIMENSIONS_PROPERTY} AS dimensions ORDER BY node.id"
)
_INDEX_QUERY = (
    "SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties, options "
    "WHERE name = $name RETURN name, type, state, labelsOrTypes, properties, options"
)
_GRAPH_NODE_IDS_QUERY = "MATCH (node) RETURN collect(node.id) AS ids"
_GRAPH_EDGES_QUERY = (
    "MATCH (source)-[relation]->(target) "
    "RETURN collect([source.id, type(relation), target.id, relation.id]) AS edges"
)
_CREATE_E5_BASE_INDEX = (
    f"CREATE VECTOR INDEX {E5_BASE_INDEX} IF NOT EXISTS "
    f"FOR (node:FounderGraphSearchable) ON (node.{E5_BASE_PROPERTY}) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
)


class SyntheticBackfillError(RuntimeError):
    """Raised when the synthetic-only backfill cannot prove its target is safe."""


def _record_value(record: Any, key: str) -> Any:
    try:
        return record[key]
    except (KeyError, TypeError, IndexError):
        return getattr(record, key, None)


def parse_container_inspect(output: str) -> dict[str, Any]:
    """Parse the deliberately limited, secret-free Docker inspect projection."""

    parts = output.strip().split("|", maxsplit=2)
    if len(parts) != 3:
        raise SyntheticBackfillError("synthetic Neo4j container inspection was incomplete")
    try:
        mounts = json.loads(parts[0])
        port_bindings = json.loads(parts[1])
    except json.JSONDecodeError as error:
        raise SyntheticBackfillError("synthetic Neo4j container inspection was invalid") from error
    if not isinstance(mounts, list) or not isinstance(port_bindings, dict):
        raise SyntheticBackfillError("synthetic Neo4j container inspection was invalid")
    return {"mounts": mounts, "port_bindings": port_bindings, "state": parts[2]}


def inspect_synthetic_container() -> dict[str, Any]:
    docker = shutil.which("docker.exe") or shutil.which("docker")
    if docker is None:
        raise SyntheticBackfillError("Docker CLI is required to verify the synthetic Neo4j volume")
    try:
        result = subprocess.run(
            [docker, "inspect", "--format", _INSPECT_FORMAT, SYNTHETIC_CONTAINER],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SyntheticBackfillError("the dedicated synthetic Neo4j container could not be verified") from error
    return parse_container_inspect(result.stdout)


def validate_synthetic_target(
    *,
    uri: str,
    database: str,
    owner_id: str,
    docker_identity: Mapping[str, Any],
) -> None:
    """Require the exact synthetic volume and its loopback Bolt binding."""

    if owner_id != SYNTHETIC_OWNER_ID or database != "neo4j":
        raise SyntheticBackfillError("synthetic E5-base mode requires its reserved owner and neo4j database")
    try:
        parsed_uri = urlsplit(uri)
        host = parsed_uri.hostname
        port = parsed_uri.port
    except ValueError as error:
        raise SyntheticBackfillError("synthetic E5-base mode requires a valid direct Bolt URI") from error
    if parsed_uri.scheme != "bolt" or host != "127.0.0.1" or parsed_uri.username or parsed_uri.password:
        raise SyntheticBackfillError("synthetic E5-base mode requires an unauthenticated loopback Bolt URI")
    if docker_identity.get("state") != "running":
        raise SyntheticBackfillError("the dedicated synthetic Neo4j container is not running")
    data_mounts = [
        mount for mount in docker_identity.get("mounts", [])
        if isinstance(mount, Mapping) and mount.get("Destination") == "/data"
    ]
    if len(data_mounts) != 1 or data_mounts[0].get("Type") != "volume" or data_mounts[0].get("Name") != SYNTHETIC_VOLUME:
        raise SyntheticBackfillError("the container is not mounted on the dedicated synthetic Neo4j volume")
    bolt_bindings = docker_identity.get("port_bindings", {}).get("7687/tcp")
    if not isinstance(bolt_bindings, list) or not any(
        binding.get("HostIp") == "127.0.0.1" and binding.get("HostPort") == str(port)
        for binding in bolt_bindings
        if isinstance(binding, Mapping)
    ):
        raise SyntheticBackfillError("the Bolt URI does not match the loopback port of the synthetic container")


def _run_read(session: Any, query: str, **parameters: Any) -> list[Any]:
    result = session.run(query, **parameters)
    return list(result)


def _run_write(session: Any, query: str, **parameters: Any) -> None:
    result = session.run(query, **parameters)
    consume = getattr(result, "consume", None)
    if callable(consume):
        consume()


def _database_owner_count(driver: Any, *, database: str, owner_id: str) -> int:
    with driver.session(database=database) as session:
        rows = _run_read(session, _OWNER_CHECK_QUERY, owner_id=owner_id)
    if len(rows) != 1:
        raise SyntheticBackfillError("synthetic database ownership could not be verified")
    node_count = _record_value(rows[0], "node_count")
    owner_node_count = _record_value(rows[0], "owner_node_count")
    if (
        not isinstance(node_count, int)
        or isinstance(node_count, bool)
        or node_count <= 0
        or owner_node_count != node_count
    ):
        raise SyntheticBackfillError("database nodes do not all belong to the reserved synthetic owner")
    return node_count


def _vector_index_record(session: Any, name: str) -> Any | None:
    rows = _run_read(session, _INDEX_QUERY, name=name)
    if len(rows) > 1:
        raise SyntheticBackfillError("a vector index name resolved to multiple schema entries")
    return rows[0] if rows else None


def _validate_index_record(record: Any, *, name: str, property_name: str, dimensions: int) -> str:
    options = _record_value(record, "options")
    index_config = options.get("indexConfig") if isinstance(options, Mapping) else None
    actual_dimensions = index_config.get("vector.dimensions") if isinstance(index_config, Mapping) else None
    similarity = index_config.get("vector.similarity_function") if isinstance(index_config, Mapping) else None
    if (
        _record_value(record, "name") != name
        or _record_value(record, "type") != "VECTOR"
        or _record_value(record, "labelsOrTypes") != ["FounderGraphSearchable"]
        or _record_value(record, "properties") != [property_name]
        or actual_dimensions != dimensions
        or not isinstance(similarity, str)
        or similarity.lower() != "cosine"
    ):
        actual = {
            "type": _record_value(record, "type"),
            "labels": _record_value(record, "labelsOrTypes"),
            "properties": _record_value(record, "properties"),
            "dimensions": actual_dimensions,
            "similarity": similarity,
        }
        raise SyntheticBackfillError(f"index {name} does not match its required vector configuration: {actual}")
    state = _record_value(record, "state")
    if state not in {"ONLINE", "POPULATING"}:
        raise SyntheticBackfillError(f"index {name} is not usable")
    return state


def _verify_existing_indexes(driver: Any, *, database: str) -> str:
    with driver.session(database=database) as session:
        original = _vector_index_record(session, SMALL_INDEX)
        if original is None:
            raise SyntheticBackfillError("the existing 384-dimension vector index is missing")
        state = _validate_index_record(
            original,
            name=SMALL_INDEX,
            property_name="search_embedding",
            dimensions=384,
        )
        if state != "ONLINE":
            raise SyntheticBackfillError("the preserved 384-dimension vector index is not ONLINE")
        trial = _vector_index_record(session, E5_BASE_INDEX)
        if trial is not None:
            _validate_index_record(
                trial,
                name=E5_BASE_INDEX,
                property_name=E5_BASE_PROPERTY,
                dimensions=E5_BASE_DIMENSIONS,
            )
            return _record_value(trial, "state")
        return state


def _graph_fingerprint(driver: Any, *, database: str) -> str:
    with driver.session(database=database) as session:
        node_rows = _run_read(session, _GRAPH_NODE_IDS_QUERY)
        edge_rows = _run_read(session, _GRAPH_EDGES_QUERY)
    node_ids = _record_value(node_rows[0], "ids") if len(node_rows) == 1 else None
    edges = _record_value(edge_rows[0], "edges") if len(edge_rows) == 1 else None
    if not isinstance(node_ids, list) or not isinstance(edges, list):
        raise SyntheticBackfillError("graph identity could not be snapshotted")
    snapshot = {"node_ids": sorted(node_ids), "edges": sorted(edges, key=lambda edge: json.dumps(edge, sort_keys=True))}
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _embedding_is_current(row: Any, content_hash: str) -> bool:
    vector = _record_value(row, "embedding")
    return (
        isinstance(vector, (list, tuple))
        and len(vector) == E5_BASE_DIMENSIONS
        and _record_value(row, "content_hash") == content_hash
        and _record_value(row, "model_id") == E5_BASE_MODEL_ID
        and _record_value(row, "model_revision") == E5_BASE_MODEL_REVISION
        and _record_value(row, "dimensions") == E5_BASE_DIMENSIONS
    )


def _read_searchable_nodes(driver: Any, *, database: str, owner_id: str) -> list[Any]:
    with driver.session(database=database) as session:
        rows = _run_read(session, _SEARCHABLE_NODES_QUERY, owner_id=owner_id)
    for row in rows:
        if not isinstance(_record_value(row, "id"), str) or not isinstance(_record_value(row, "search_text"), str):
            raise SyntheticBackfillError("a synthetic searchable node has invalid identity or text")
    return rows


def _write_embedding_batch(session: Any, updates: list[dict[str, Any]], *, owner_id: str) -> None:
    query = (
        f"UNWIND $updates AS item MATCH (node:FounderGraphSearchable {{id: item.id, owner_id: $owner_id}}) "
        f"SET node.{E5_BASE_PROPERTY} = item.embedding, "
        f"node.{E5_BASE_HASH_PROPERTY} = item.content_hash, "
        f"node.{E5_BASE_MODEL_PROPERTY} = $model_id, "
        f"node.{E5_BASE_REVISION_PROPERTY} = $model_revision, "
        f"node.{E5_BASE_DIMENSIONS_PROPERTY} = $dimensions "
        "RETURN count(node) AS updated_count"
    )
    result = session.run(
        query,
        updates=updates,
        owner_id=owner_id,
        model_id=E5_BASE_MODEL_ID,
        model_revision=E5_BASE_MODEL_REVISION,
        dimensions=E5_BASE_DIMENSIONS,
    )
    rows = list(result)
    if len(rows) != 1 or _record_value(rows[0], "updated_count") != len(updates):
        raise SyntheticBackfillError("synthetic embedding updates did not match the selected nodes")
    consume = getattr(result, "consume", None)
    if callable(consume):
        consume()


def _ensure_trial_index(driver: Any, *, database: str, apply: bool, timeout_seconds: int = 60) -> str:
    with driver.session(database=database) as session:
        record = _vector_index_record(session, E5_BASE_INDEX)
        if record is None:
            if not apply:
                return "not_created"
            _run_write(session, _CREATE_E5_BASE_INDEX)
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        with driver.session(database=database) as session:
            record = _vector_index_record(session, E5_BASE_INDEX)
        if record is None:
            sleep(0.25)
            continue
        state = _validate_index_record(
            record,
            name=E5_BASE_INDEX,
            property_name=E5_BASE_PROPERTY,
            dimensions=E5_BASE_DIMENSIONS,
        )
        if state == "ONLINE":
            return state
        sleep(0.25)
    raise SyntheticBackfillError("the 768-dimension synthetic vector index did not become ONLINE")


def run_synthetic_backfill(driver: Any, *, database: str, owner_id: str, apply: bool) -> dict[str, Any]:
    """Preview or idempotently add base vectors/index to a verified synthetic graph."""

    node_count = _database_owner_count(driver, database=database, owner_id=owner_id)
    original_index_state = _verify_existing_indexes(driver, database=database)
    graph_before = _graph_fingerprint(driver, database=database) if apply else None
    nodes = _read_searchable_nodes(driver, database=database, owner_id=owner_id)
    pending: list[tuple[str, str, str]] = []
    for node in nodes:
        text = _record_value(node, "search_text")
        text_hash = sha256(text.encode("utf-8")).hexdigest()
        if not _embedding_is_current(node, text_hash):
            pending.append((_record_value(node, "id"), text, text_hash))

    model = LocalSearchModels(embedding_profile="base")
    updates_written = 0
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]
        vectors = model.embed_documents([text for _node_id, text, _text_hash in batch])
        if len(vectors) != len(batch) or any(len(vector) != E5_BASE_DIMENSIONS for vector in vectors):
            raise SyntheticBackfillError("the cached E5-base model returned an invalid vector batch")
        if apply:
            updates = [
                {"id": node_id, "embedding": vector, "content_hash": content_hash}
                for (node_id, _text, content_hash), vector in zip(batch, vectors, strict=True)
            ]
            with driver.session(database=database) as session:
                _write_embedding_batch(session, updates, owner_id=owner_id)
            updates_written += len(updates)

    index_state = _ensure_trial_index(driver, database=database, apply=apply)
    graph_unchanged = None
    if apply:
        graph_unchanged = graph_before == _graph_fingerprint(driver, database=database)
        if not graph_unchanged:
            raise SyntheticBackfillError("synthetic node IDs or graph edges changed during derived-vector backfill")
    return {
        "profile": "e5-base-synthetic",
        "database": database,
        "owner_scope_verified": True,
        "graph_node_count": node_count,
        "searchable_node_count": len(nodes),
        "pending_embeddings": len(pending),
        "updated_nodes": updates_written,
        "original_384_index": original_index_state,
        "e5base_768_index": index_state,
        "graph_ids_and_edges_unchanged": graph_unchanged,
        "mode": "apply" if apply else "dry_run",
    }


def _run_synthetic_profile(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.database != "neo4j" or args.owner_id != SYNTHETIC_OWNER_ID:
        parser.error("synthetic E5-base mode requires --database neo4j and --owner-id dots-synthetic-test")
    required_environment = {
        "DOTS_GRAPH_BACKEND": "neo4j",
        "DOTS_NEO4J_URI": None,
        "DOTS_NEO4J_DATABASE": "neo4j",
        "DOTS_LOCAL_OWNER_ID": SYNTHETIC_OWNER_ID,
    }
    for name, expected in required_environment.items():
        value = os.environ.get(name, "").strip()
        if not value or (expected is not None and value != expected):
            parser.error(f"synthetic E5-base mode requires a matching {name} setting")
    if not (os.environ.get("DOTS_NEO4J_AUTH_FILE", "").strip() or os.environ.get("DOTS_NEO4J_PASSWORD", "")):
        parser.error("synthetic E5-base mode requires protected Neo4j credentials")
    try:
        identity = inspect_synthetic_container()
        validate_synthetic_target(
            uri=os.environ["DOTS_NEO4J_URI"],
            database=args.database,
            owner_id=args.owner_id,
            docker_identity=identity,
        )
    except SyntheticBackfillError as error:
        parser.error(str(error))
    try:
        driver = create_neo4j_driver_from_env()
    except RuntimeError as error:
        parser.error(str(error))
    try:
        report = run_synthetic_backfill(
            driver,
            database=args.database,
            owner_id=args.owner_id,
            apply=args.apply,
        )
    except SyntheticBackfillError as error:
        parser.error(str(error))
    finally:
        driver.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic-e5-base",
        action="store_true",
        help="preview or apply the additive 768-dimension profile to the verified synthetic volume only",
    )
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument("--dry-run", action="store_true", help="preview local embeddings without writing (default)")
    execution.add_argument("--apply", action="store_true", help="write the additive synthetic vectors and index")
    parser.add_argument("--database", help="must be neo4j in synthetic E5-base mode")
    parser.add_argument("--owner-id", help="must be dots-synthetic-test in synthetic E5-base mode")
    args = parser.parse_args()
    if args.synthetic_e5_base:
        if not args.database or not args.owner_id:
            parser.error("synthetic E5-base mode requires explicit --database and --owner-id")
        return _run_synthetic_profile(parser, args)
    if args.apply or args.dry_run or args.database or args.owner_id:
        parser.error("--dry-run, --apply, --database, and --owner-id require --synthetic-e5-base")

    owner_id = (os.environ.get("DOTS_LOCAL_OWNER_ID") or "local-owner").strip()
    database = (os.environ.get("DOTS_NEO4J_DATABASE") or "neo4j").strip()
    driver = create_neo4j_driver_from_env()
    try:
        composition = create_neo4j_graph_composition(driver, owner_id, database=database)
        count = composition.gateway.reindex_search_embeddings()
        print(json.dumps({"embedded_nodes": count}, ensure_ascii=False))
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
