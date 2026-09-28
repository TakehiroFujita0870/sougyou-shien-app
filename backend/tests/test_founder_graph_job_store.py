from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph_job_store import FounderGraphJobStore, JobConflictError, JobLeaseError, JobState
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion


class Result:
    def __init__(self, row=None): self.row = row
    def single(self, **_kwargs): return self.row


class Driver:
    def __init__(self): self.jobs = {}
    def session(self, *, database): return Session(self)


class Session:
    def __init__(self, driver): self.driver = driver
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def execute_read(self, callback): return callback(self)
    def execute_write(self, callback): return callback(self)

    def run(self, query, **params):
        jobs = self.driver.jobs
        kind = query.splitlines()[0].split(":")[-1]
        if kind == "enqueue":
            key = (params["owner_id"], params["brief_id"])
            jobs.setdefault(key, dict(params["properties"]))
            return self.row(jobs[key])
        if kind in {"claim_lock", "expire_exhausted"}: return Result()
        if kind == "claim":
            ready = [j for j in jobs.values() if j["owner_id"] == params["owner_id"] and (
                j["state"] == "leased" and j["lease_owner"] == params["worker_id"] and j["lease_expires_at"] > params["now"] or
                j["attempt_count"] < j["max_attempts"] and j["available_at"] <= params["now"] and
                (j["state"] == "pending" or j["state"] == "leased" and j["lease_expires_at"] <= params["now"]))]
            if not ready: return Result()
            job = min(ready, key=lambda j: (j["lease_owner"] != params["worker_id"] or j["lease_expires_at"] <= params["now"], j["available_at"], j["created_at"], j["id"]))
            same = job["state"] == "leased" and job["lease_owner"] == params["worker_id"] and job["lease_expires_at"] > params["now"]
            job.update(state="leased", attempt_count=job["attempt_count"] + (not same), lease_owner=params["worker_id"], lease_token=job["lease_token"] if same else params["lease_token"], lease_expires_at=job["lease_expires_at"] if same else params["lease_expires_at"], updated_at=job["updated_at"] if same else params["now"])
            return self.row(job)
        job = next((j for j in jobs.values() if j["id"] == params.get("job_id") and j["owner_id"] == params["owner_id"]), None)
        if kind == "get": return self.row(job) if job else Result()
        if kind == "manifest":
            if not self.live(job, params) or job["candidate_manifest_json"] not in (None, params["manifest_json"]): return Result()
            job.update(candidate_manifest_json=params["manifest_json"], updated_at=params["now"])
            return self.row(job)
        if kind in {"complete", "fail"}:
            active = self.live(job, params)
            replay = bool(job and job["last_transition"] == kind and job["last_lease_token"] == params["lease_token"] and (job["state"] == "succeeded" if kind == "complete" else job["state"] in {"pending", "failed"}))
            if not active and not replay: return Result()
            if kind == "complete":
                if active: job.update(last_transition="complete", last_lease_token=params["lease_token"])
                job.update(state="succeeded", updated_at=params["now"] if active else job["updated_at"], **self.clear_lease())
            elif active:
                job.update(state="failed" if job["attempt_count"] >= job["max_attempts"] else "pending", last_transition="fail", last_lease_token=params["lease_token"], available_at=params["retry_at"], last_error_code=params["error_code"], updated_at=params["now"], **self.clear_lease())
            return self.row(job)
        if kind == "supersede":
            stale = [j for j in jobs.values() if j["owner_id"] == params["owner_id"] and j["idea_lineage_root_id"] == params["idea_lineage_root_id"] and j["brief_id"] != params["current_brief_id"] and j["state"] in {"pending", "leased"}]
            for j in stale: j.update(state="superseded", updated_at=params["now"], **self.clear_lease())
            return Result({"count": len(stale)})
        raise AssertionError(kind)

    @staticmethod
    def row(job): return Result({"job": dict(job)})
    @staticmethod
    def clear_lease(): return dict(lease_owner=None, lease_token=None, lease_expires_at=None)
    @staticmethod
    def live(job, params): return bool(job and job["state"] == "leased" and job["lease_token"] == params["lease_token"] and job["lease_expires_at"] > params["now"])


def _time(minutes=0):
    return datetime(2026, 9, 29, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _brief(owner="owner-1", brief_id="brief-1", root="idea-root", idea_id="idea-r1"):
    return IdeaBriefVersion(owner_id=owner, idea_lineage_root_id=root, based_on_idea_id=idea_id, id=brief_id,
        sections=(IdeaBriefSection(index=0, content="PRIVATE REPORT TEXT"),), report_markdown="PRIVATE REPORT TEXT", egress_policy="shareable")


def _store(driver=None, owner="owner-1"):
    return FounderGraphJobStore(driver or Driver(), owner_id=owner)


def test_enqueue_is_idempotent_owner_scoped_and_does_not_copy_report_text():
    driver = Driver(); store = _store(driver)
    first, replay = store.enqueue(_brief(), now=_time()), store.enqueue(_brief(), now=_time(1))
    transaction_hook = store.enqueue_tx(Session(driver), _brief(), owner_id="owner-1", now=_time(2))
    other_owner = _store(driver, owner="owner-2").enqueue(_brief("owner-2"), now=_time())

    assert first.id == replay.id == transaction_hook.id and first.brief_id == "brief-1"
    assert other_owner.id != first.id and len(driver.jobs) == 2
    stored = str(driver.jobs[("owner-1", "brief-1")])
    assert "PRIVATE REPORT TEXT" not in stored
    assert "report_markdown" not in stored and "content" not in stored


def test_expired_lease_is_reclaimed_after_store_restart_and_fences_old_worker():
    driver = Driver()
    first_store = _store(driver)
    first_store.enqueue(_brief(), now=_time())
    first_lease = first_store.claim(worker_id="worker-a", lease_seconds=30, now=_time())
    assert first_lease is not None and first_lease.attempt_count == 1
    replayed_claim = first_store.claim(worker_id="worker-a", lease_seconds=30, now=_time())
    assert replayed_claim.lease_token == first_lease.lease_token and replayed_claim.attempt_count == 1

    restarted_store = _store(driver)
    second_lease = restarted_store.claim(worker_id="worker-b", lease_seconds=30, now=_time(1))
    assert second_lease is not None and second_lease.attempt_count == 2
    assert second_lease.lease_token != first_lease.lease_token
    with pytest.raises(JobLeaseError):
        restarted_store.complete(first_lease.id, first_lease.lease_token, now=_time(1))
    completed = restarted_store.complete(second_lease.id, second_lease.lease_token, now=_time(1))
    assert completed.state is JobState.SUCCEEDED and restarted_store.complete(
        second_lease.id, second_lease.lease_token, now=_time(2),
    ) == completed


def test_failure_retries_only_when_due_and_becomes_terminal_at_attempt_limit():
    driver = Driver(); store = _store(driver)
    store.enqueue(_brief(), now=_time(), max_attempts=2)
    lease = store.claim(worker_id="worker-a", lease_seconds=30, now=_time())
    assert lease is not None
    retry = store.fail(lease.id, lease.lease_token, error_code="temporary", retry_after_seconds=5, now=_time())
    assert retry.state is JobState.PENDING and retry.available_at == _time() + timedelta(seconds=5)
    assert store.fail(lease.id, lease.lease_token, error_code="ignored", retry_after_seconds=99, now=_time()) == retry
    assert store.claim(worker_id="worker-b", lease_seconds=30, now=_time()) is None
    lease = store.claim(worker_id="worker-b", lease_seconds=30, now=_time(1))
    assert lease is not None and lease.attempt_count == 2
    assert store.fail(lease.id, lease.lease_token, error_code="temporary", retry_after_seconds=5, now=_time(1)).state is JobState.FAILED


def test_candidate_manifest_is_immutable_and_new_brief_supersedes_old_job():
    driver = Driver(); store = _store(driver)
    old_job = store.enqueue(_brief(), now=_time())
    lease = store.claim(worker_id="worker-a", lease_seconds=30, now=_time())
    assert lease is not None
    manifested = store.persist_candidate_manifest(lease.id, lease.lease_token, ("candidate-a", "candidate-b"), now=_time())
    assert manifested.candidate_ids == ("candidate-a", "candidate-b")
    with pytest.raises(JobConflictError):
        store.persist_candidate_manifest(lease.id, lease.lease_token, ("candidate-c",), now=_time())

    store.enqueue(_brief(brief_id="brief-2", idea_id="idea-r2"), now=_time(1))
    assert store.mark_superseded_tx(Session(driver), owner_id="owner-1", idea_lineage_root_id="idea-root",
                                    current_brief_id="brief-2", now=_time(1)) == 1
    assert store.get(old_job.id).state is JobState.SUPERSEDED
