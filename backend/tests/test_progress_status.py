"""Progress records must not turn historical failures into current work."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("progress_status", ROOT / "scripts/validate_progress_status.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def snapshot():
    return {"updated_at": "2026-09-27T01:11:26Z", "baseline_main": "56ecf2aad992", "items": [{
        "id": "navigation", "title": "Navigation", "scope": "live-navigation",
        "implementation": "implemented", "verification": "passed", "delivery": "working_tree",
        "runtime": "active", "next_action": "integrate", "note": "Do not repair twice.",
        "evidence": [
            {"recorded_at": "2026-09-26T04:00:00Z", "scope": "live-navigation", "result": "failed", "reference": "old failure"},
            {"recorded_at": "2026-09-26T04:30:00Z", "scope": "live-navigation", "result": "passed", "reference": "new successful test"},
        ],
    }]}


def test_new_success_keeps_unmerged_fix_out_of_failure_backlog():
    data = snapshot()
    data["items"][0]["evidence"].reverse()
    MODULE.validate(data)


@pytest.mark.parametrize("field,value", [("verification", "failed"), ("next_action", "repair")])
def test_old_failure_cannot_override_new_success(field, value):
    data = snapshot()
    data["items"][0][field] = value
    with pytest.raises(ValueError):
        MODULE.validate(data)


def test_success_in_a_different_scope_is_not_a_pass():
    data = snapshot()
    data["items"][0]["evidence"][1]["scope"] = "isolated-storage"
    with pytest.raises(ValueError):
        MODULE.validate(data)


def test_unverified_cannot_erase_a_success_to_schedule_repair():
    data = snapshot()
    data["items"][0].update(verification="not_verified", next_action="repair")
    with pytest.raises(ValueError):
        MODULE.validate(data)


def test_a_new_failure_can_reopen_the_same_scope():
    data = snapshot()
    item = data["items"][0]
    item.update(verification="failed", next_action="repair")
    item["evidence"].append({"recorded_at": "2026-09-27T00:00:00Z", "scope": item["scope"], "result": "failed", "reference": "current reproduction"})
    MODULE.validate(data)


@pytest.mark.parametrize("mutation", ["unknown_state", "duplicate_id", "missing_evidence", "future_evidence"])
def test_invalid_progress_is_rejected(mutation):
    data = snapshot()
    if mutation == "unknown_state":
        data["items"][0]["delivery"] = "probably_done"
    elif mutation == "duplicate_id":
        data["items"].append(copy.deepcopy(data["items"][0]))
    elif mutation == "missing_evidence":
        data["items"][0]["evidence"] = []
    else:
        data["items"][0]["evidence"][1]["recorded_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        MODULE.validate(data)


def test_repository_snapshot_and_common_gate():
    MODULE.validate(json.loads((ROOT / "docs/operations/dots-current-status.json").read_text(encoding="utf-8")))
    for path in ["AGENTS.md", "skills/dev/finish-and-merge/SKILL.md"]:
        assert "progress-reporting.md" in (ROOT / path).read_text(encoding="utf-8")
