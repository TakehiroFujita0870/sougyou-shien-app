"""Apply an explicitly versioned Founder Graph schema migration to local Neo4j."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dots.founder_graph_neo4j import Neo4jGraphGateway  # noqa: E402
from dots.founder_graph_runtime import create_neo4j_driver_from_env  # noqa: E402
from dots.founder_graph_schema import SCHEMA_VERSION  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-version", type=int, required=True)
    parser.add_argument("--target-version", type=int, default=SCHEMA_VERSION)
    args = parser.parse_args(argv)
    owner_id = (os.environ.get("DOTS_LOCAL_OWNER_ID") or "local-owner").strip()
    database = (os.environ.get("DOTS_NEO4J_DATABASE") or "neo4j").strip()
    driver = create_neo4j_driver_from_env()
    try:
        gateway = Neo4jGraphGateway(driver, owner_id, database=database)
        applied = gateway.migrate(current_version=args.current_version, target_version=args.target_version)
        print(json.dumps({
            "migration": "applied",
            "from_version": args.current_version,
            "to_version": args.target_version,
            "queries_applied": applied,
        }, ensure_ascii=False))
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
