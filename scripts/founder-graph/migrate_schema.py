"""Print or validate the idempotent Neo4j Founder Graph schema plan.

The default mode is Docker-free. Applying queries to a live database is a
separate adapter so this script cannot accidentally mutate a live volume.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from dots.founder_graph_schema import migration_queries, schema_manifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-version", type=int, default=0)
    parser.add_argument("--target-version", type=int, default=1)
    parser.add_argument("--print-cypher", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    queries = migration_queries(args.current_version, args.target_version)
    if args.print_cypher:
        print(";\n".join(queries) + (";" if queries else ""))
    else:
        print(json.dumps({**schema_manifest(), "planned_queries": len(queries), "validate_only": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
