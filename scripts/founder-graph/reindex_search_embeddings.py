"""Rebuild the current owner's derived local search vectors."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dots.founder_graph_runtime import (  # noqa: E402
    create_neo4j_driver_from_env,
    create_neo4j_graph_composition,
)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
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
