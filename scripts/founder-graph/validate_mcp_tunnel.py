"""Validate the Founder Graph Secure MCP Tunnel contract without networking.

The validator reads repository text only. It never starts tunnel-client, opens a
socket, resolves DNS, invokes Docker, or reads a credential.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


RUNBOOK = Path("docs/operations/founder-graph-mcp-tunnel.md")
PLAN = Path("docs/plans/founder-graph-mcp-tunnel.md")
MAIN = Path("backend/dots/main.py")
READ_MCP = Path("backend/dots/founder_graph_mcp.py")
WRITE_MCP = Path("backend/dots/founder_graph_mcp_write.py")
STDIO_MCP = Path("backend/dots/founder_graph_mcp_stdio.py")

REQUIRED_RUNBOOK_TOKENS = (
    "Secure MCP Tunnel",
    "127.0.0.1",
    "tunnel-client init",
    "tunnel-client doctor",
    "tunnel-client run",
    "--mcp-command",
    "<tunnel_id>",
    "<runtime-api-key>",
    "developer-mode",
    "Connectionに **Tunnel**",
    "Read + Use",
    "unavailable",
    "503",
    "失効",
    "founder_graph_mcp_stdio",
    "tools/list",
    "tools/call",
    "2025-06-18",
    "実機gate未実施",
)
REQUIRED_PLAN_TOKENS = (
    "Given:",
    "When:",
    "Then:",
    "## スコープ外",
    "## ADR",
    "SP-TUNNEL-01",
    "T-STDIO-01",
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\btunnel_[0-9a-f]{16,}\b", re.IGNORECASE),
)
PUBLIC_BIND_PATTERNS = (
    re.compile(r"\b0\.0\.0\.0(?::\d+)?\b"),
    re.compile(r"\b公网\b"),
)


def _missing(text: str, tokens: tuple[str, ...], label: str) -> list[str]:
    return [f"{label} is missing {token!r}" for token in tokens if token not in text]


def scan_text(text: str, label: str) -> list[str]:
    issues: list[str] = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            issues.append(f"{label} contains a non-placeholder credential or tunnel id")
    for line in text.splitlines():
        if any(pattern.search(line) for pattern in PUBLIC_BIND_PATTERNS):
            # A runbook may name a forbidden bind while explicitly rejecting it.
            if any(marker in line for marker in ("追加しない", "使わない", "拒否", "禁止")):
                continue
            issues.append(f"{label} contains a public bind")
    return issues


def validate(root: Path) -> list[str]:
    issues: list[str] = []
    paths = (RUNBOOK, PLAN, MAIN, READ_MCP, WRITE_MCP, STDIO_MCP)
    for relative in paths:
        if not (root / relative).is_file():
            issues.append(f"missing required file: {relative}")
    if issues:
        return issues

    runbook = (root / RUNBOOK).read_text(encoding="utf-8")
    plan = (root / PLAN).read_text(encoding="utf-8")
    main = (root / MAIN).read_text(encoding="utf-8")
    read_mcp = (root / READ_MCP).read_text(encoding="utf-8")
    write_mcp = (root / WRITE_MCP).read_text(encoding="utf-8")
    stdio_mcp = (root / STDIO_MCP).read_text(encoding="utf-8")

    issues.extend(_missing(runbook, REQUIRED_RUNBOOK_TOKENS, "MCP tunnel runbook"))
    issues.extend(_missing(plan, REQUIRED_PLAN_TOKENS, "MCP tunnel plan"))
    issues.extend(scan_text(runbook, "MCP tunnel runbook"))
    issues.extend(scan_text(plan, "MCP tunnel plan"))
    if "FOUNDER_GRAPH_NEO4J_PASSWORD" in runbook:
        issues.append("MCP tunnel runbook must not document a Neo4j password variable")
    if "--mcp-server-url https://" in runbook:
        issues.append("MCP tunnel runbook must not hand a private HTTP URL directly to ChatGPT")

    for label, source in (("FastAPI composition", main), ("read MCP", read_mcp), ("write MCP", write_mcp), ("stdio MCP", stdio_mcp)):
        if "Mcp" not in source:
            issues.append(f"{label} must expose an explicit MCP adapter symbol")
    for token in ("initialize", "tools/list", "tools/call", "run_stdio", "-32600", "-32700"):
        if token not in stdio_mcp:
            issues.append(f"stdio MCP is missing {token!r}")
    if "unavailable" not in main or "SERVICE_UNAVAILABLE" not in main:
        issues.append("FastAPI composition must preserve unavailable / HTTP 503 mapping")
    if "arbitrary" in write_mcp.lower() and "cypher" not in write_mcp.lower():
        issues.append("write MCP source does not document the arbitrary-query boundary")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    issues = validate(args.root.resolve())
    if issues:
        print("Founder Graph MCP tunnel contract: FAIL")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Founder Graph MCP tunnel contract: PASS (static, network-free)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
