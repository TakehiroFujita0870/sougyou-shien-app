"""Check progress-record consistency; never infer execution or product completion."""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

STATES = {
    "implementation": {"implemented", "not_started"},
    "verification": {"passed", "partial", "failed", "not_verified"},
    "delivery": {"main", "working_tree", "mixed"},
    "runtime": {"active", "not_deployed", "not_applicable"},
    "next_action": {"integrate", "verify", "repair", "implement", "none"},
}


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("evidence timestamps need a timezone")
    return result


def validate(data):
    updated = instant(data["updated_at"])
    if not re.fullmatch(r"[0-9a-f]{12}", data["baseline_main"]):
        raise ValueError("baseline_main must be a 12-character Git reference")
    if not data["items"]:
        raise ValueError("a snapshot needs items")
    seen = set()
    for item in data["items"]:
        key = item["id"]
        if not key or key in seen:
            raise ValueError("empty or duplicate progress ID")
        seen.add(key)
        for field in ("title", "scope", "note"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise ValueError(f"{key}: missing {field}")
        for field, allowed in STATES.items():
            if item[field] not in allowed:
                raise ValueError(f"{key}: unknown {field}")
        matching = []
        for entry in item["evidence"]:
            recorded = instant(entry["recorded_at"])
            if recorded > updated or entry["result"] not in {"passed", "partial", "failed"}:
                raise ValueError(f"{key}: invalid evidence")
            if not entry["reference"] or not entry["scope"]:
                raise ValueError(f"{key}: missing evidence reference/scope")
            if entry["scope"] == item["scope"]:
                matching.append((recorded, entry["result"]))
        if item["verification"] == "not_verified" and matching:
            raise ValueError(f"{key}: existing same-scope evidence cannot be forgotten")
        if item["verification"] != "not_verified":
            if not matching:
                raise ValueError(f"{key}: verified without matching evidence")
            latest = max(date for date, _ in matching)
            results = {result for date, result in matching if date == latest}
            if results != {item["verification"]}:
                raise ValueError(f"{key}: contradicts latest same-scope evidence")
        if item["verification"] == "passed" and item["next_action"] in {"repair", "implement"}:
            raise ValueError(f"{key}: a passed condition cannot require repair")
        if item["next_action"] == "repair" and item["verification"] != "failed":
            raise ValueError(f"{key}: repair needs current same-scope failure evidence")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs/operations/dots-current-status.json"
    validate(json.loads(target.read_text(encoding="utf-8")))
    print("Progress record consistency: PASS (not an execution or completion proof)")
