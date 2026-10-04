"""The production reindex command must stay small and close its driver."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "reindex_search_embeddings.py"
SPEC = importlib.util.spec_from_file_location("reindex_search_embeddings_cli", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_normal_reindex_uses_configured_owner_and_closes_driver(monkeypatch, capsys):
    calls = []
    driver = SimpleNamespace(close=lambda: calls.append("close"))
    gateway = SimpleNamespace(reindex_search_embeddings=lambda: 3)
    monkeypatch.setenv("NEBULA_LOCAL_OWNER_ID", "test-owner")
    monkeypatch.setenv("NEBULA_NEO4J_DATABASE", "neo4j")
    monkeypatch.setattr(MODULE, "create_neo4j_driver_from_env", lambda: driver)

    def compose(actual_driver, owner, *, database):
        calls.append((actual_driver, owner, database))
        return SimpleNamespace(gateway=gateway)

    monkeypatch.setattr(MODULE, "create_neo4j_graph_composition", compose)
    assert MODULE.main([]) == 0
    assert calls == [(driver, "test-owner", "neo4j"), "close"]
    assert json.loads(capsys.readouterr().out) == {"embedded_nodes": 3}


def test_driver_closes_when_reindex_fails(monkeypatch):
    closed = []
    driver = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(MODULE, "create_neo4j_driver_from_env", lambda: driver)

    def fail():
        raise RuntimeError("test failure")

    monkeypatch.setattr(
        MODULE,
        "create_neo4j_graph_composition",
        lambda actual_driver, owner, *, database: SimpleNamespace(
            gateway=SimpleNamespace(reindex_search_embeddings=fail)
        ),
    )
    with pytest.raises(RuntimeError, match="test failure"):
        MODULE.main([])
    assert closed == [True]


def test_retired_synthetic_option_is_rejected():
    with pytest.raises(SystemExit) as error:
        MODULE.main(["--synthetic-e5-base"])
    assert error.value.code == 2
