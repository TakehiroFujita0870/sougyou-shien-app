from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from dots.founder_graph_job_store import FounderGraphJobStore, JobConflictError, JobLeaseError, JobState, JobStoreError
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
        if kind == "claim_lock": return Result()
        if kind == "expire_exhausted":
            exhausted = [j for j in jobs.values() if j["owner_id"] == params["owner_id"]
                         and (params["job_id"] is None or j["id"] == params["job_id"])
                         and j["state"] == "leased" and j["lease_expires_at"] <= params["now"]
                         and j["attempt_count"] >= j["max_attempts"]]
            for j in exhausted:
                j.update(state="failed", last_error_code="attempts_exhausted",
                         updated_at=params["now"], **self.clear_lease())
            return Result({"expired": len(exhausted)})
        if kind == "claim":
            ready = []
            for job in jobs.values():
                if (job["owner_id"] != params["owner_id"]
                        or params["job_id"] is not None and job["id"] != params["job_id"]):
                    continue
                same_lease = (job["state"] == "leased" and job["lease_owner"] == params["worker_id"]
                              and job["lease_expires_at"] > params["now"])
                available = (job["attempt_count"] < job["max_attempts"]
                             and job["available_at"] <= params["now"]
                             and (job["state"] == "pending" or
                                  job["state"] == "leased" and job["lease_expires_at"] <= params["now"]))
                if same_lease or available:
                    ready.append(job)
            if not ready: return Result()
            job = min(ready, key=lambda j: (j["lease_owner"] != params["worker_id"] or j["lease_expires_at"] <= params["now"], j["available_at"], j["created_at"], j["id"]))
            same = job["state"] == "leased" and job["lease_owner"] == params["worker_id"] and job["lease_expires_at"] > params["now"]
            job.update(state="leased", attempt_count=job["attempt_count"] + (not same), lease_owner=params["worker_id"], lease_token=job["lease_token"] if same else params["lease_token"], lease_expires_at=job["lease_expires_at"] if same else params["lease_expires_at"], updated_at=job["updated_at"] if same else params["now"])
            return self.row(job)
        job = next((j for j in jobs.values() if j["id"] == params.get("job_id") and j["owner_id"] == params["owner_id"]), None)
        if kind == "get": return self.row(job) if job else Result()
        if kind == "manifest":
            empty_manifest = job["candidate_manifest_json"] is None and job["candidate_payloads_json"] is None
            same_manifest = (job["candidate_manifest_json"] == params["manifest_json"]
                             and job["candidate_payloads_json"] == params["candidate_payloads_json"])
            if (not self.live(job, params) or job["based_on_idea_id"] != params["idea_id"]
                    or job["brief_id"] != params["brief_id"] or not (empty_manifest or same_manifest)): return Result()
            job.update(candidate_manifest_json=params["manifest_json"], candidate_payloads_json=params["candidate_payloads_json"], updated_at=params["now"])
            return self.row(job)
        if kind == "payloads":
            return self.row(job) if self.live(job, params) else Result()
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
        if kind == "supersede_stale":
            active = self.live(job, params) and (
                job["brief_id"] != params["current_brief_id"] or
                job["based_on_idea_id"] != params["current_idea_id"]
            )
            replay = bool(job and job["state"] == "superseded" and
                          job["last_transition"] == "supersede" and
                          job["last_lease_token"] == params["lease_token"])
            if not active and not replay: return Result()
            if active:
                job.update(state="superseded", last_transition="supersede",
                           last_lease_token=params["lease_token"], last_error_code="stale_version",
                           updated_at=params["now"], **self.clear_lease())
            return self.row(job)
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


def _validated_manifest(*, brief_id="brief-1", idea_id="idea-r1", candidates=None, revision=3):
    quote = "PRIVATE QUOTE TEXT"
    candidate = SimpleNamespace(
        candidate_id="candidate-a",
        assertion=SimpleNamespace(
            source_id=idea_id, target_id="claim-1", source_kind="idea", target_kind="claim",
            predicate="addresses", basis="owner_hypothesis", evidence_ids=("evidence-1",),
        ),
        support=SimpleNamespace(kind="quote", char_start=0, char_end=len(quote), section_index=0, quote=quote),
    )
    return SimpleNamespace(
        idea_id=idea_id, brief_id=brief_id, brief_revision=revision,
        brief_markdown_sha256="a" * 64, candidates=tuple(candidates or (candidate,)),
    )


def test_canonical_job_id_is_public_and_bound_to_owner_and_brief():
    store = _store()
    job = store.enqueue(_brief(), now=_time())

    assert FounderGraphJobStore.job_id_for(job.owner_id, job.brief_id) == job.id
    assert FounderGraphJobStore.job_id_for("another-owner", job.brief_id) != job.id
    with pytest.raises(JobStoreError):
        FounderGraphJobStore.job_id_for("owner-1", "")


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
    manifest = _validated_manifest(candidates=(
        _validated_manifest().candidates[0],
        SimpleNamespace(candidate_id="candidate-b", assertion=_validated_manifest().candidates[0].assertion,
                        support=_validated_manifest().candidates[0].support),
    ))
    manifested = store.persist_candidate_manifest(lease.id, lease.lease_token, manifest, now=_time())
    assert manifested.candidate_ids == ("candidate-a", "candidate-b")
    with pytest.raises(JobConflictError):
        changed = _validated_manifest(candidates=(SimpleNamespace(
            candidate_id="candidate-c", assertion=manifest.candidates[0].assertion,
            support=manifest.candidates[0].support),))
        store.persist_candidate_manifest(lease.id, lease.lease_token, changed, now=_time())

    store.enqueue(_brief(brief_id="brief-2", idea_id="idea-r2"), now=_time(1))
    assert store.mark_superseded_tx(Session(driver), owner_id="owner-1", idea_lineage_root_id="idea-root",
                                    current_brief_id="brief-2", now=_time(1)) == 1
    assert store.get(old_job.id).state is JobState.SUPERSEDED


def test_legacy_id_only_manifest_cannot_be_upgraded_without_atomic_payload():
    driver = Driver(); store = _store(driver)
    store.enqueue(_brief(), now=_time())
    lease = store.claim(worker_id="worker-a", lease_seconds=30, now=_time())
    assert lease is not None
    driver.jobs[("owner-1", "brief-1")]["candidate_manifest_json"] = '["candidate-a"]'

    with pytest.raises(JobConflictError):
        store.persist_candidate_manifest(lease.id, lease.lease_token, _validated_manifest(), now=_time())
    assert driver.jobs[("owner-1", "brief-1")]["candidate_payloads_json"] is None


def test_candidate_payload_is_canonical_immutable_and_omits_report_and_quote_text():
    driver = Driver(); store = _store(driver)
    store.enqueue(_brief(), now=_time())
    lease = store.claim(worker_id="worker-a", lease_seconds=30, now=_time())
    assert lease is not None
    base = _validated_manifest().candidates[0]
    manifest = _validated_manifest(candidates=(base, SimpleNamespace(
        candidate_id="candidate-section", assertion=base.assertion,
        support=SimpleNamespace(kind="section", section_index=2),
    )))

    saved = store.persist_candidate_manifest(lease.id, lease.lease_token, manifest, now=_time())
    replay = store.persist_candidate_manifest(lease.id, lease.lease_token, manifest, now=_time())
    payload = store.get_candidate_payloads(lease.id, lease.lease_token, now=_time())

    assert saved == replay and saved.candidate_ids == ("candidate-a", "candidate-section")
    assert payload is not None and payload.brief_id == "brief-1" and payload.brief_revision == 3
    assert payload.candidates[0].support.char_start == 0
    assert payload.candidates[1].support.section_index == 2 and payload.candidates[1].support.char_start is None
    persisted = driver.jobs[("owner-1", "brief-1")]["candidate_payloads_json"]
    assert driver.jobs[("owner-1", "brief-1")]["candidate_manifest_json"] == '["candidate-a","candidate-section"]'
    assert "PRIVATE REPORT TEXT" not in persisted and "PRIVATE QUOTE TEXT" not in persisted
    assert '"quote":"PRIVATE' not in persisted and "report_markdown" not in persisted


def test_candidate_payload_survives_retry_restart_and_rejects_old_lease():
    driver = Driver(); first_store = _store(driver)
    first_store.enqueue(_brief(), now=_time())
    first_lease = first_store.claim(worker_id="worker-a", lease_seconds=30, now=_time())
    assert first_lease is not None
    first_store.persist_candidate_manifest(first_lease.id, first_lease.lease_token, _validated_manifest(), now=_time())
    first_store.fail(first_lease.id, first_lease.lease_token, error_code="partial_apply", now=_time())

    restarted_store = _store(driver)
    second_lease = restarted_store.claim(worker_id="worker-b", lease_seconds=30, now=_time(1))
    assert second_lease is not None and second_lease.attempt_count == 2
    assert restarted_store.get_candidate_payloads(second_lease.id, second_lease.lease_token, now=_time(1)) is not None
    with pytest.raises(JobLeaseError):
        restarted_store.get_candidate_payloads(first_lease.id, first_lease.lease_token, now=_time(1))
    with pytest.raises(JobLeaseError):
        restarted_store.persist_candidate_manifest(first_lease.id, first_lease.lease_token, _validated_manifest(), now=_time(1))


def test_candidate_payload_is_owner_and_brief_bound_and_superseded_lease_cannot_read():
    driver = Driver(); store = _store(driver)
    store.enqueue(_brief(), now=_time())
    lease = store.claim(worker_id="worker-a", lease_seconds=30, now=_time())
    assert lease is not None
    with pytest.raises(JobConflictError):
        store.persist_candidate_manifest(lease.id, lease.lease_token, _validated_manifest(idea_id="other-idea"), now=_time())
    store.persist_candidate_manifest(lease.id, lease.lease_token, _validated_manifest(), now=_time())

    other_owner = _store(driver, owner="owner-2")
    with pytest.raises(JobLeaseError):
        other_owner.get_candidate_payloads(lease.id, lease.lease_token, now=_time())

    store.enqueue(_brief(brief_id="brief-2", idea_id="idea-r2"), now=_time(1))
    store.mark_superseded_tx(Session(driver), owner_id="owner-1", idea_lineage_root_id="idea-root",
                             current_brief_id="brief-2", now=_time(1))
    with pytest.raises(JobLeaseError):
        store.get_candidate_payloads(lease.id, lease.lease_token, now=_time(1))


def test_candidate_payload_bounds_reject_oversized_quotes_and_manifests_before_write():
    driver = Driver(); store = _store(driver)
    store.enqueue(_brief(), now=_time())
    lease = store.claim(worker_id="worker-a", lease_seconds=30, now=_time())
    assert lease is not None
    base = _validated_manifest().candidates[0]
    long_quote = SimpleNamespace(kind="quote", char_start=0, char_end=1201, section_index=0, quote="x" * 1201)
    with pytest.raises(JobStoreError):
        store.persist_candidate_manifest(lease.id, lease.lease_token, _validated_manifest(candidates=(
            SimpleNamespace(candidate_id="candidate-a", assertion=base.assertion, support=long_quote),
        )), now=_time())

    too_many = tuple(SimpleNamespace(candidate_id=f"candidate-{index}", assertion=base.assertion,
                                     support=SimpleNamespace(kind="section", section_index=0))
                     for index in range(65))
    with pytest.raises(JobStoreError):
        store.persist_candidate_manifest(lease.id, lease.lease_token,
                                         _validated_manifest(candidates=too_many), now=_time())

    evidence_ids = tuple(f"evidence-{i:02d}-" + "x" * 180 for i in range(32))
    large_candidates = tuple(SimpleNamespace(
        candidate_id=f"candidate-{index}",
        assertion=SimpleNamespace(source_id="idea-r1", target_id="claim-1", source_kind="idea",
                                  target_kind="claim", predicate="addresses", basis="external_evidence",
                                  evidence_ids=evidence_ids),
        support=SimpleNamespace(kind="section", section_index=0),
    ) for index in range(64))
    with pytest.raises(JobStoreError, match="64 KiB"):
        store.persist_candidate_manifest(lease.id, lease.lease_token,
                                         _validated_manifest(candidates=large_candidates), now=_time())
    stored = driver.jobs[("owner-1", "brief-1")]
    assert stored["candidate_manifest_json"] is None and stored["candidate_payloads_json"] is None


def test_claim_specific_targets_saved_brief_without_stealing_older_work():
    driver = Driver()
    store = _store(driver)
    older = store.enqueue(_brief(brief_id="brief-old"), now=_time())
    target = store.enqueue(_brief(brief_id="brief-saved"), now=_time(1))
    driver.jobs[(older.owner_id, older.brief_id)].update(
        state="leased", lease_owner="abandoned-worker", lease_token="old-token",
        lease_expires_at=_time().isoformat().replace("+00:00", "Z"),
        attempt_count=5, max_attempts=5,
    )

    lease = store.claim_specific(target.id, worker_id="inline-worker", now=_time(1))

    assert lease is not None and lease.id == target.id and lease.attempt_count == 1
    untouched = store.get(older.id)
    assert untouched.state is JobState.LEASED and untouched.lease_token == "old-token"
    retry = store.claim_specific(target.id, worker_id="inline-worker", now=_time(1))
    assert retry is not None and retry.lease_token == lease.lease_token and retry.attempt_count == 1
    assert store.claim_specific(target.id, worker_id="other-worker", now=_time(1)) is None


def test_stale_supersede_is_lease_fenced_and_replayable():
    store = _store()
    job = store.enqueue(_brief(), now=_time())
    first_lease = store.claim_specific(job.id, worker_id="worker-a", lease_seconds=30, now=_time())
    assert first_lease is not None

    with pytest.raises(JobLeaseError):
        store.supersede_stale(
            job.id, first_lease.lease_token, current_brief_id=job.brief_id,
            current_idea_id=job.based_on_idea_id, now=_time(),
        )
    with pytest.raises(JobLeaseError):
        store.supersede_stale(
            job.id, first_lease.lease_token, current_brief_id="brief-new",
            current_idea_id="idea-r2", now=_time(1),
        )

    second_lease = store.claim_specific(job.id, worker_id="worker-b", lease_seconds=30, now=_time(1))
    assert second_lease is not None and second_lease.lease_token != first_lease.lease_token
    with pytest.raises(JobLeaseError):
        store.supersede_stale(
            job.id, first_lease.lease_token, current_brief_id="brief-new",
            current_idea_id="idea-r2", now=_time(1),
        )

    stale = store.supersede_stale(
        job.id, second_lease.lease_token, current_brief_id="brief-new",
        current_idea_id="idea-r2", now=_time(1),
    )
    assert stale.state is JobState.SUPERSEDED and stale.last_error_code == "stale_version"
    assert stale.lease_token is None and stale.last_transition == "supersede"
    assert store.supersede_stale(
        job.id, second_lease.lease_token, current_brief_id="brief-new",
        current_idea_id="idea-r2", now=_time(2),
    ) == stale
