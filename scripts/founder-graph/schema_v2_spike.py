"""Inspect a schema v1 export and print a schema v2 migration preview.

The command is deliberately offline.  It never opens a database and never
changes the input file.  Use ``--strict`` in a gate: a non-zero exit means
that a human must resolve a missing field, duplicate identity, or unresolved
reference before the real migration can write anything.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dots.founder_graph_migration import (  # noqa: E402
    build_schema_v1_spike_fixture,
    convert_schema_v1_payload,
)


def _read_payload(path: Path | None) -> dict[str, Any]:
    if path is None:
        return build_schema_v1_spike_fixture()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("input JSON must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="schema v1 JSON export; defaults to the synthetic fixture")
    parser.add_argument("--strict", action="store_true", help="return 1 when a blocking finding exists")
    parser.add_argument("--summary", action="store_true", help="print a short human-readable summary")
    args = parser.parse_args(argv)

    preview = convert_schema_v1_payload(_read_payload(args.input))
    if args.summary:
        counts = preview.counts
        print(
            "schema-v2-spike "
            f"ready={preview.is_ready_for_write} "
            f"nodes={counts['input_nodes']} relationships={counts['input_relationships']} "
            f"anchors={counts['anchors']} revisions={counts['revisions']} "
            f"assertions={counts['assertions']} blocking={counts['blocking_findings']}"
        )
        for finding in preview.findings:
            print(f"{finding.severity}: {finding.category}: {finding.location}: {finding.message}")
    else:
        print(json.dumps(preview.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.strict and not preview.is_ready_for_write else 0


if __name__ == "__main__":
    raise SystemExit(main())
