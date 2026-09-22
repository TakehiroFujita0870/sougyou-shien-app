"""Network-free checks for the Secure MCP Tunnel runbook contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "founder-graph" / "validate_mcp_tunnel.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("founder_graph_mcp_tunnel_validator", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secure_tunnel_contract_passes_without_network() -> None:
    validator = load_validator()
    assert validator.validate(ROOT) == []


def test_secret_and_public_bind_scans_are_fail_closed() -> None:
    validator = load_validator()
    assert validator.scan_text("CONTROL_PLANE_API_KEY=sk-real-secret-value", "fixture")
    assert validator.scan_text("tunnel_0123456789abcdef0123456789abcdef", "fixture")
    assert validator.scan_text("--host 0.0.0.0 --port 8000", "fixture")


def test_placeholder_values_are_allowed() -> None:
    validator = load_validator()
    assert validator.scan_text("<runtime-api-key> <tunnel_id> 127.0.0.1", "fixture") == []


def test_runbook_records_transport_gap_and_stop_contract() -> None:
    runbook = (ROOT / "docs" / "operations" / "founder-graph-mcp-tunnel.md").read_text(encoding="utf-8")
    assert "founder_graph_mcp_stdio.py" in runbook
    assert "--mcp-command" in runbook
    assert "unavailable" in runbook
    assert "Connectionに **Tunnel**" in runbook
