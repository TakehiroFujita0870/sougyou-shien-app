"""The local graph-job checker is owner-scoped and emits safe summaries only."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dots.founder_graph_job_store import JobState


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "founder-graph" / "check_relation_candidate_jobs.py"
SPEC = importlib.util.spec_from_file_location("check_relation_candidate_jobs_cli", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _job(job_id, state, *, payload, attempts=0):
    return SimpleNamespace(
        id=job_id, owner_id="private-owner", state=state,
        attempt_count=attempts, max_attempts=5,
        candidate_payload_persisted=payload,
        report_markdown="PRIVATE REPORT TEXT", support_quote="PRIVATE QUOTE TEXT",
        connection_secret="TEST-SECRET",
    )


class FakeJobs:
    def __init__(self, jobs):
        self.jobs = jobs
        self.limits = []

    def list_inspection_jobs(self, *, limit):
        self.limits.append(limit)
        return self.jobs[:limit]


class FakeProcessor:
    def __init__(self, jobs):
        self.jobs = jobs
        self.calls = []

    def process_specific(self, job_id, *, raw_manifest):
        self.calls.append((job_id, raw_manifest))
        original = next(job for job in self.jobs.jobs if job.id == job_id)
        return _job(job_id, JobState.SUCCEEDED, payload=True, attempts=original.attempt_count + 1)


def _configure_runtime(monkeypatch, processor):
    calls = []
    driver = SimpleNamespace(close=lambda: calls.append("closed"))
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "private-owner")
    monkeypatch.setenv("DOTS_NEO4J_DATABASE", "neo4j")
    monkeypatch.setattr(MODULE, "create_neo4j_driver_from_env", lambda: (calls.append("opened") or driver))
    monkeypatch.setattr(MODULE, "create_neo4j_graph_composition", lambda *_args, **_kwargs: "composition")
    monkeypatch.setattr(MODULE, "create_relation_candidate_job_processor", lambda _composition: processor)
    return calls


def test_apply_retries_only_due_pending_jobs_with_persisted_payload(monkeypatch, capsys):
    jobs = FakeJobs([
        _job("graph-job-persisted", JobState.PENDING, payload=True),
        _job("graph-job-no-manifest", JobState.PENDING, payload=False),
        _job("graph-job-terminal", JobState.FAILED, payload=True, attempts=5),
    ])
    processor = FakeProcessor(jobs)
    calls = _configure_runtime(monkeypatch, processor)

    assert MODULE.main(["--apply"]) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert processor.calls == [("graph-job-persisted", None)]
    assert calls == ["opened", "closed"]
    assert payload["mode"] == "apply"
    assert payload["summary"] == {
        "processed": 1, "would_retry": 0, "manifest_missing": 1, "terminal_failed": 1,
    }
    assert [item["action"] for item in payload["jobs"]] == [
        "processed", "manifest_missing", "needs_review",
    ]
    assert payload["jobs"][0]["state"] == "succeeded"
    assert payload["jobs"][1]["state"] == "pending"
    assert payload["jobs"][2]["state"] == "failed"
    assert all(set(item) == {
        "job_id", "state", "attempt_count", "max_attempts",
        "candidate_payload_persisted", "action",
    } for item in payload["jobs"])
    assert "PRIVATE REPORT TEXT" not in output
    assert "PRIVATE QUOTE TEXT" not in output
    assert "private-owner" not in output


def test_default_mode_is_read_only_and_limit_is_capped_at_twenty(monkeypatch, capsys):
    jobs = FakeJobs([_job("graph-job-persisted", JobState.PENDING, payload=True)])
    processor = FakeProcessor(jobs)
    _configure_runtime(monkeypatch, processor)

    assert MODULE.main([]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "inspect"
    assert payload["jobs"][0]["action"] == "would_retry"
    assert processor.calls == []
    assert jobs.limits == [20]

    with pytest.raises(SystemExit) as error:
        MODULE.main(["--limit", "21"])
    assert error.value.code == 2


def test_applying_an_empty_inspection_set_does_not_invoke_the_processor(monkeypatch, capsys):
    jobs = FakeJobs([])
    processor = FakeProcessor(jobs)
    _configure_runtime(monkeypatch, processor)

    assert MODULE.main(["--apply"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["jobs"] == []
    assert payload["summary"]["processed"] == 0
    assert processor.calls == []


def test_cli_requires_explicit_owner_and_persistent_backend(monkeypatch, capsys):
    driver_opened = []
    monkeypatch.delenv("DOTS_LOCAL_OWNER_ID", raising=False)
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setattr(MODULE, "create_neo4j_driver_from_env", lambda: driver_opened.append(True))

    assert MODULE.main([]) == 2
    assert driver_opened == []
    assert "owner" in capsys.readouterr().err.lower()

    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "owner-1")
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "memory")
    assert MODULE.main([]) == 2
    assert driver_opened == []


def test_database_errors_do_not_leak_exception_text(monkeypatch, capsys):
    jobs = FakeJobs([])

    def fail(*, limit):
        jobs.limits.append(limit)
        raise RuntimeError("PRIVATE REPORT TEXT and credential=secret")

    jobs.list_inspection_jobs = fail
    processor = FakeProcessor(jobs)
    calls = _configure_runtime(monkeypatch, processor)

    assert MODULE.main([]) == 1

    error = capsys.readouterr().err
    assert "graph job inspection failed" in error
    assert "PRIVATE REPORT TEXT" not in error
    assert "secret" not in error
    assert calls == ["opened", "closed"]
