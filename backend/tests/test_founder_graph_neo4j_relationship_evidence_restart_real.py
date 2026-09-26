"""Opt-in stdio-to-real-Neo4j persistence proof across a container restart."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from dots.founder_graph_neo4j import Neo4jGraphGateway
from neo4j_disposable_harness import DisposableNeo4j, HarnessError, fixed_docker, is_opted_in, IMAGE


OPT_IN = "DOTS_NEO4J_RELATIONSHIP_EVIDENCE_RESTART_REAL"
ROLE = "neo4j-relationship-restart"
NAME_PREFIX = "dots-relrestart"


def _poll_until_ready(driver, timeout_seconds: float = 90) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            driver.verify_connectivity()
            with driver.session(database="neo4j") as session:
                if session.run("RETURN 1 AS ready").single()["ready"] == 1:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


class _StdioClient:
    """A fresh module subprocess speaking newline-delimited JSON-RPC."""

    def __init__(self, env: dict[str, str]):
        self.process = subprocess.Popen([sys.executable, "-m", "dots.founder_graph_mcp_stdio"],
            cwd=Path(__file__).resolve().parents[1], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self._selector = selectors.DefaultSelector()
        assert self.process.stdout is not None
        self._selector.register(self.process.stdout, selectors.EVENT_READ)
        self._request_id = 0
        self.responses: list[dict[str, object]] = []
        self.read_responses: list[dict[str, object]] = []

    def call(self, tool: str, arguments: dict[str, object]) -> dict[str, object]:
        self._request_id += 1
        request = {"jsonrpc": "2.0", "id": self._request_id, "method": "tools/call",
                   "params": {"name": tool, "arguments": arguments}}
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        assert self._selector.select(20), f"stdio {tool} response timed out"
        assert self.process.stdout is not None
        response = json.loads(self.process.stdout.readline())
        self.responses.append(response)
        if tool in {"search", "fetch"}: self.read_responses.append(response)
        assert response.get("id") == self._request_id
        assert "error" not in response, response.get("error")
        return response["result"]["structuredContent"]

    def close(self) -> None:
        self._selector.close()
        if self.process.stdin is not None:
            self.process.stdin.close()
        try: self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate(); self.process.wait(timeout=5)
        if self.process.returncode:
            assert self.process.stderr is not None
            diagnostic = self.process.stderr.read()
            raise AssertionError(f"stdio child exited with {self.process.returncode}: {diagnostic}")


def _assert_safe_artifact(artifact: object, *, private_values: tuple[str, ...]) -> str:
    encoded = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
    forbidden_keys = {"source_text", "excerpt", "locator", "source_revision_id", "content_chunk_id",
        "revision_id", "claim_id", "material_id", "owner_id", "payload_json", "provenance"}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(artifact)
    assert all(value not in encoded for value in private_values if value)
    return encoded


def _assert_responses_redact_source(
    responses: list[dict[str, object]], *, private_values: tuple[str, ...]
) -> None:
    forbidden_keys = {"source_text", "excerpt", "locator", "text_hash", "payload_json"}
    encoded = json.dumps(responses, ensure_ascii=False, sort_keys=True)

    def visit(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(responses)
    assert all(value not in encoded for value in private_values if value)


def test_stdio_relationship_evidence_survives_same_neo4j_restart_without_private_lineage():
    if not is_opted_in(os.environ, OPT_IN): pytest.skip(f"set {OPT_IN}=1 only for the synthetic disposable Neo4j proof")
    docker = fixed_docker()
    if docker is None: pytest.skip("supported Docker CLI is unavailable; no container created")
    try:
        docker.call("version", "--format", "{{.Server.Version}}")
        docker.call("image", "inspect", IMAGE)
    except HarnessError:
        pytest.skip("Docker daemon or preloaded Neo4j image unavailable; no pull attempted")

    run_id = uuid4().hex
    password = f"dots-test-{run_id}"
    disposable = DisposableNeo4j(docker, run_id, role=ROLE, name_prefix=NAME_PREFIX)
    driver = None
    client = None
    try:
        port = disposable.start(auth=f"neo4j/{password}")
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(f"bolt://127.0.0.1:{port}", auth=("neo4j", password))
        assert _poll_until_ready(driver), "disposable Neo4j did not pass bounded readiness queries"
        owner = f"owner-{run_id[:12]}"
        Neo4jGraphGateway(driver, owner).migrate()
        env = os.environ.copy()
        env.update({
            "DOTS_GRAPH_BACKEND": "neo4j",
            "DOTS_LOCAL_OWNER_ID": owner,
            "DOTS_NEO4J_URI": f"bolt://127.0.0.1:{port}",
            "DOTS_NEO4J_USERNAME": "neo4j",
            "DOTS_NEO4J_PASSWORD": password,
        })
        marker = f"PRIVATE-SOURCE-BODY-{run_id[:12]}"
        search_query = f"needle-{run_id[:8]}"
        idea_title = f"Synthetic restart idea {run_id[:8]}"
        claim_text = f"Synthetic restart claim {search_query}"
        target_text = "Synthetic restart target"
        client = _StdioClient(env)
        idea = client.call("capture_idea", {"title": idea_title, "summary": "Synthetic shareable idea", "egress_policy": "shareable", "source_text": marker, "idempotency_key": f"idea-{run_id}"})
        source = client.call("capture_source", {"url": f"https://example.test/{run_id}", "title": f"Private source {run_id[:8]}", "summary": marker, "idempotency_key": f"source-{run_id}"})
        claim = client.call("append_claim", {"text": claim_text, "egress_policy": "shareable", "idempotency_key": f"claim-{run_id}"})
        target = client.call("append_claim", {"text": target_text, "egress_policy": "shareable", "idempotency_key": f"target-{run_id}"})
        evidence = client.call("capture_evidence", {"claim_id": claim["target_id"], "content_chunk_id": source["content_chunk_ids"][0], "egress_policy": "shareable", "idempotency_key": f"evidence-{run_id}"})
        assertion = client.call("link_entities", {"source_id": claim["target_id"], "target_id": target["target_id"], "relation": "DERIVED_FROM", "evidence_ids": [evidence["target_id"]], "egress_policy": "shareable", "confidence": 0.9, "idempotency_key": f"assertion-{run_id}"})
        before_search = client.call("search", {"query": search_query, "limit": 20})
        before_idea = client.call("fetch", {"id": idea["target_id"]})
        before_path_hit = next(hit for hit in before_search["results"] if hit["id"] == target["target_id"])
        assert before_path_hit["semantic_relation_path"][0]["relation_assertion_id"] == assertion["target_id"]
        assert before_path_hit["semantic_relation_path"][0]["evidence_ids"] == [evidence["target_id"]]
        before_relation = client.call("fetch", {"id": assertion["target_id"]})
        before_evidence = client.call("fetch", {"id": evidence["target_id"]})
        assert before_relation["path"] == [claim["target_id"], "DERIVED_FROM", target["target_id"]]
        assert before_relation["evidence_ids"] == [evidence["target_id"]]
        assert before_evidence["id"] == evidence["target_id"]
        source_secrets = (marker, f"https://example.test/{run_id}", f"chars:0-{len(marker)}")
        private_values = (*source_secrets, source["target_id"], source["source_revision_id"], source["content_chunk_ids"][0])
        _assert_responses_redact_source(client.responses, private_values=source_secrets)
        for artifact in (before_search, before_idea, before_relation, before_evidence):
            _assert_safe_artifact(artifact, private_values=private_values)
        before_read_responses = list(client.read_responses)
        for response in before_read_responses:
            _assert_safe_artifact(response["result"]["structuredContent"], private_values=private_values)
        before_lineage_json = json.dumps(before_read_responses, ensure_ascii=False)
        assert all(value not in before_lineage_json for value in (source["target_id"], source["source_revision_id"], source["content_chunk_ids"][0]))
        original_container_id = disposable.container_id
        original_volumes = set(disposable.volume_names.values())
        client.close()
        client = None
        driver.close()
        driver = None

        restarted_port = disposable.restart()
        assert disposable.container_id == original_container_id
        assert set(disposable.volume_names.values()) == original_volumes
        driver = GraphDatabase.driver(f"bolt://127.0.0.1:{restarted_port}", auth=("neo4j", password))
        assert _poll_until_ready(driver), "same-volume Neo4j did not pass bounded post-restart readiness"
        env["DOTS_NEO4J_URI"] = f"bolt://127.0.0.1:{restarted_port}"
        client = _StdioClient(env)
        searched = client.call("search", {"query": search_query, "limit": 20})
        idea_result = client.call("fetch", {"id": idea["target_id"]})
        relation_result = client.call("fetch", {"id": assertion["target_id"]})
        evidence_result = client.call("fetch", {"id": evidence["target_id"]})

        hits = searched["results"]
        assert any(hit["id"] == claim["target_id"] for hit in hits)
        path_hit = next(hit for hit in hits if hit["id"] == target["target_id"])
        assert path_hit["semantic_relation_path"][0]["relation_assertion_id"] == assertion["target_id"]
        assert path_hit["semantic_relation_path"][0]["source_id"] == claim["target_id"]
        assert path_hit["semantic_relation_path"][0]["target_id"] == target["target_id"]
        assert path_hit["semantic_relation_path"][0]["evidence_ids"] == [evidence["target_id"]]
        assert idea_result["id"] == idea["target_id"]
        assert relation_result["id"] == assertion["target_id"]
        assert relation_result["path"] == [claim["target_id"], "DERIVED_FROM", target["target_id"]]
        assert relation_result["evidence_ids"] == [evidence["target_id"]]
        assert evidence_result["id"] == evidence["target_id"]
        read_lineage_values = (
            source["target_id"], source["source_revision_id"], source["content_chunk_ids"][0],
        )
        for artifact in (searched, idea_result, relation_result, evidence_result):
            _assert_safe_artifact(artifact, private_values=(*source_secrets, *read_lineage_values))
        _assert_responses_redact_source(client.responses, private_values=source_secrets)
        for response in client.responses:
            if response in client.read_responses:
                read_artifact = response["result"]["structuredContent"]
                _assert_safe_artifact(read_artifact, private_values=read_lineage_values)
        read_responses_json = json.dumps(client.read_responses, ensure_ascii=False)
        assert all(value not in read_responses_json for value in read_lineage_values)
        assert searched == before_search
        assert idea_result == before_idea
        assert relation_result == before_relation
        assert evidence_result == before_evidence
    finally:
        original_error = sys.exc_info()[1]
        cleanup_errors: list[Exception] = []
        for resource, close in ((client, lambda: client.close()), (driver, lambda: driver.close())):
            if resource is not None:
                try:
                    close()
                except Exception as error:
                    cleanup_errors.append(error)
        try:
            disposable.close()
        except Exception as error:
            cleanup_errors.append(error)
        if cleanup_errors:
            detail = "; ".join(f"{type(error).__name__}: {error}" for error in cleanup_errors)
            if original_error is not None:
                original_error.add_note(f"best-effort cleanup errors: {detail}")
            else:
                raise ExceptionGroup("disposable Neo4j test cleanup failed", cleanup_errors)
