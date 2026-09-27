"""Preview or apply the fixed-purpose schema-v2 source-edge repair."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dots.founder_graph_neo4j import Neo4jGraphGateway  # noqa: E402
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService  # noqa: E402
from dots.founder_graph_runtime import create_neo4j_driver_from_env  # noqa: E402


def _assert_synthetic_database(driver, database: str, owner_id: str) -> None:
    """Refuse apply unless every graph node uses the reserved synthetic owner ID.

    The reserved owner ID is an operator policy, not cryptographic proof that
    the records are synthetic; never reuse it for actual Founder Graph data.
    """
    with driver.session(database=database) as session:
        result = session.run(
            "MATCH (n) RETURN count(n) AS node_count, "
            "count(CASE WHEN n.owner_id = $owner_id THEN 1 END) AS synthetic_node_count",
            owner_id=owner_id,
        )
        record = result.single()
    if record is None:
        raise RuntimeError("could not verify disposable Neo4j database contents")
    node_count = record.get("node_count")
    synthetic_node_count = record.get("synthetic_node_count")
    if (
        not isinstance(node_count, int)
        or isinstance(node_count, bool)
        or node_count == 0
        or not isinstance(synthetic_node_count, int)
        or isinstance(synthetic_node_count, bool)
        or synthetic_node_count != node_count
    ):
        raise RuntimeError("selected Neo4j database is not a non-empty synthetic-only graph; refusing repair")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-id")
    parser.add_argument("--database")
    parser.add_argument("--uri", help="loopback Bolt URI; required for --apply")
    parser.add_argument("--apply", action="store_true", help="add missing edges; without this option the command only previews")
    parser.add_argument(
        "--allow-disposable-default-database",
        action="store_true",
        help="confirm this is the disposable synthetic Neo4j instance, not the ordinary local graph",
    )
    args = parser.parse_args()

    if args.apply:
        if not args.allow_disposable_default_database:
            parser.error("--apply requires --allow-disposable-default-database")
        if not all((args.uri, args.database, args.owner_id)):
            parser.error("--apply requires explicit --uri, --database, and --owner-id")
        if args.database != "neo4j" or args.owner_id != "dots-synthetic-test":
            parser.error("--apply is restricted to database neo4j and synthetic owner dots-synthetic-test")

    uri = args.uri or os.environ.get("DOTS_NEO4J_URI", "bolt://127.0.0.1:7687")
    database = args.database or os.environ.get("DOTS_NEO4J_DATABASE", "neo4j")
    owner_id = args.owner_id or os.environ.get("DOTS_LOCAL_OWNER_ID", "local-owner")
    configured_uri = os.environ.get("DOTS_NEO4J_URI", "bolt://127.0.0.1:7687").strip()
    if args.apply and uri != configured_uri:
        parser.error("--uri must match DOTS_NEO4J_URI used by the Neo4j driver")
    try:
        parsed_uri = urlparse(uri)
        host = parsed_uri.hostname
        port = parsed_uri.port
    except ValueError:
        parser.error("provide a valid direct Bolt URI")
    if parsed_uri.scheme not in {"bolt", "bolt+s", "bolt+ssc"}:
        parser.error("maintenance requires a direct Bolt URI; routing URIs are not allowed")
    if host not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("maintenance is restricted to a loopback Neo4j instance")
    if args.apply and (port or 7687) == 7687:
        parser.error("--apply refuses the default local Neo4j Bolt port; use a dedicated disposable instance")
    if not owner_id or not owner_id.strip():
        parser.error("provide --owner-id or DOTS_LOCAL_OWNER_ID")
    try:
        driver = create_neo4j_driver_from_env()
    except RuntimeError as error:
        parser.error(str(error))
    try:
        if args.apply:
            try:
                _assert_synthetic_database(driver, database, owner_id.strip())
            except RuntimeError as error:
                parser.error(str(error))
        gateway = Neo4jGraphGateway(driver, owner_id.strip(), database=database)
        report = Neo4jGraphWriteService(gateway).repair_source_structure(apply=args.apply)
    finally:
        driver.close()
    action = "applied" if report.applied else "preview"
    print(
        f"mode={action} sources={report.sources_checked} revisions={report.revisions_checked} "
        f"chunks={report.chunks_checked} expected_edges={report.expected_edges} "
        f"existing_edges={report.existing_edges} missing_edges={report.missing_edges}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
