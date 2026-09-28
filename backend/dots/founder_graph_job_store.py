"""Durable owner-scoped Brief queue; stores no report text."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import re
from secrets import token_urlsafe
from typing import Any

from .idea_brief import IdeaBriefVersion


class JobStoreError(ValueError):
    pass


class JobLeaseError(JobStoreError):
    pass


class JobConflictError(JobStoreError):
    pass


class JobState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class GraphJob:
    id: str
    owner_id: str
    brief_id: str
    idea_lineage_root_id: str
    based_on_idea_id: str
    state: JobState
    attempt_count: int
    max_attempts: int
    available_at: datetime
    lease_owner: str | None
    lease_token: str | None
    lease_expires_at: datetime | None
    last_transition: str | None
    last_lease_token: str | None
    candidate_ids: tuple[str, ...] | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


_JOB_ID_PREFIX = "graph-job_"
_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,63}$")
_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9:_-]{1,200}$")

_ENQUEUE = """// graph_job:enqueue
MERGE (job:FounderGraphJob {owner_id: $owner_id, brief_id: $brief_id})
ON CREATE SET job = $properties RETURN properties(job) AS job"""
_CLAIM_LOCK = """// graph_job:claim_lock
MERGE (lock:FounderGraphJobQueueLock {owner_id: $owner_id}) ON CREATE SET lock.version = 0
SET lock.version = lock.version + 1 RETURN lock.version AS version"""
_EXPIRE_EXHAUSTED = """// graph_job:expire_exhausted
MATCH (job:FounderGraphJob {owner_id: $owner_id})
WHERE job.state = 'leased' AND job.lease_expires_at <= $now AND job.attempt_count >= job.max_attempts
SET job.state = 'failed', job.last_error_code = 'attempts_exhausted', job.lease_owner = null,
    job.lease_token = null, job.lease_expires_at = null, job.updated_at = $now RETURN count(job) AS expired"""
_CLAIM = """// graph_job:claim
MATCH (job:FounderGraphJob {owner_id: $owner_id})
WHERE (job.state = 'leased' AND job.lease_owner = $worker_id AND job.lease_expires_at > $now)
  OR (job.available_at <= $now AND job.attempt_count < job.max_attempts AND
      (job.state = 'pending' OR (job.state = 'leased' AND job.lease_expires_at <= $now)))
WITH job, (job.state = 'leased' AND job.lease_owner = $worker_id AND job.lease_expires_at > $now) AS same_lease
ORDER BY CASE WHEN same_lease THEN 0 ELSE 1 END, job.available_at, job.created_at, job.id LIMIT 1
SET job.state = 'leased', job.attempt_count = job.attempt_count + CASE WHEN same_lease THEN 0 ELSE 1 END,
    job.lease_owner = $worker_id, job.lease_token = CASE WHEN same_lease THEN job.lease_token ELSE $lease_token END,
    job.lease_expires_at = CASE WHEN same_lease THEN job.lease_expires_at ELSE $lease_expires_at END,
    job.updated_at = CASE WHEN same_lease THEN job.updated_at ELSE $now END
RETURN properties(job) AS job"""
_GET = """// graph_job:get
MATCH (job:FounderGraphJob {owner_id: $owner_id, id: $job_id}) RETURN properties(job) AS job"""
_MANIFEST = """// graph_job:manifest
MATCH (job:FounderGraphJob {owner_id: $owner_id, id: $job_id})
WHERE job.state = 'leased' AND job.lease_token = $lease_token AND job.lease_expires_at > $now
  AND (job.candidate_manifest_json IS NULL OR job.candidate_manifest_json = $manifest_json)
SET job.candidate_manifest_json = $manifest_json, job.updated_at = $now
RETURN properties(job) AS job"""
_COMPLETE = """// graph_job:complete
MATCH (job:FounderGraphJob {owner_id: $owner_id, id: $job_id})
WHERE (job.state = 'leased' AND job.lease_token = $lease_token AND job.lease_expires_at > $now) OR
      (job.state = 'succeeded' AND job.last_transition = 'complete' AND job.last_lease_token = $lease_token)
WITH job, job.state = 'leased' AS active
SET job.last_transition = CASE WHEN active THEN 'complete' ELSE job.last_transition END,
    job.last_lease_token = CASE WHEN active THEN $lease_token ELSE job.last_lease_token END,
    job.state = 'succeeded', job.lease_owner = null, job.lease_token = null,
    job.lease_expires_at = null, job.updated_at = CASE WHEN active THEN $now ELSE job.updated_at END
RETURN properties(job) AS job"""
_FAIL = """// graph_job:fail
MATCH (job:FounderGraphJob {owner_id: $owner_id, id: $job_id})
WHERE (job.state = 'leased' AND job.lease_token = $lease_token AND job.lease_expires_at > $now) OR
      (job.state IN ['pending', 'failed'] AND job.last_transition = 'fail' AND job.last_lease_token = $lease_token)
WITH job, job.state = 'leased' AS active
SET job.state = CASE WHEN active AND job.attempt_count >= job.max_attempts THEN 'failed'
                     WHEN active THEN 'pending' ELSE job.state END,
    job.last_transition = CASE WHEN active THEN 'fail' ELSE job.last_transition END,
    job.last_lease_token = CASE WHEN active THEN $lease_token ELSE job.last_lease_token END,
    job.available_at = CASE WHEN active THEN $retry_at ELSE job.available_at END,
    job.last_error_code = CASE WHEN active THEN $error_code ELSE job.last_error_code END,
    job.lease_owner = null,
    job.lease_token = null, job.lease_expires_at = null,
    job.updated_at = CASE WHEN active THEN $now ELSE job.updated_at END
RETURN properties(job) AS job"""
_SUPERSEDE = """// graph_job:supersede
MATCH (job:FounderGraphJob {owner_id: $owner_id, idea_lineage_root_id: $idea_lineage_root_id})
WHERE job.brief_id <> $current_brief_id AND job.state IN ['pending', 'leased']
SET job.state = 'superseded', job.lease_owner = null, job.lease_token = null,
    job.lease_expires_at = null, job.updated_at = $now RETURN count(job) AS count"""


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200: raise JobStoreError(f"{name} must be a non-empty short identifier")
    return value.strip()


def _time(value: datetime | None) -> datetime:
    parsed = value or datetime.now(timezone.utc)
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None: raise JobStoreError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stored_time(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parsed_time(value: Any) -> datetime:
    if not isinstance(value, str): raise ValueError("persisted job timestamp is invalid")
    return _time(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _job_id(owner_id: str, brief_id: str) -> str:
    return f"{_JOB_ID_PREFIX}{hashlib.sha256(f'{owner_id}\0{brief_id}'.encode()).hexdigest()[:32]}"


def _job_from_row(row: Any) -> GraphJob | None:
    if row is None:
        return None
    try:
        props = dict(row["job"])
        candidates = props.pop("candidate_manifest_json")
        candidates = None if candidates is None else json.loads(candidates)
        if candidates is not None and (not isinstance(candidates, list) or
            any(not isinstance(item, str) or not _CANDIDATE_ID.fullmatch(item) for item in candidates) or
            len(candidates) != len(set(candidates))): raise ValueError
        props["candidate_ids"], props["state"] = None if candidates is None else tuple(candidates), JobState(props["state"])
        for key in ("available_at", "created_at", "updated_at", "lease_expires_at"):
            if props.get(key) is not None: props[key] = _parsed_time(props[key])
        job = GraphJob(**props)
        if job.id != _job_id(job.owner_id, job.brief_id) or type(job.attempt_count) is not int or type(job.max_attempts) is not int or not 0 <= job.attempt_count <= job.max_attempts:
            raise ValueError
        return job
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise JobStoreError("persisted job fields are invalid") from None


class FounderGraphJobStore:
    def __init__(self, driver: Any, *, owner_id: str, database: str = "neo4j") -> None:
        if driver is None:
            raise JobStoreError("a Neo4j driver is required")
        self.driver = driver
        self.owner_id = _identifier(owner_id, "owner_id")
        self.database = _identifier(database, "database")

    def enqueue(self, brief: IdeaBriefVersion, *, now: datetime | None = None,
                max_attempts: int = 5) -> GraphJob:
        with self.driver.session(database=self.database) as session:
            return session.execute_write(lambda tx: self.enqueue_tx(
                tx, brief, owner_id=self.owner_id, now=now, max_attempts=max_attempts,
            ))

    @staticmethod
    def enqueue_tx(tx: Any, brief: IdeaBriefVersion, *, owner_id: str,
                   now: datetime | None = None, max_attempts: int = 5) -> GraphJob:
        """Enqueue in a caller's transaction; only Brief identity is copied."""
        owner = _identifier(owner_id, "owner_id")
        if not isinstance(brief, IdeaBriefVersion) or brief.owner_id != owner:
            raise JobStoreError("Brief owner does not match the queue owner")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
            raise JobStoreError("max_attempts must be between 1 and 100")
        instant = _time(now)
        identity = _job_id(owner, brief.id)
        at = _stored_time(instant)
        properties = {
            "id": identity, "owner_id": owner, "brief_id": brief.id,
            "idea_lineage_root_id": brief.idea_lineage_root_id,
            "based_on_idea_id": brief.based_on_idea_id, "state": JobState.PENDING.value,
            "attempt_count": 0, "max_attempts": max_attempts,
            "available_at": at, "lease_owner": None, "lease_token": None,
            "lease_expires_at": None, "last_transition": None, "last_lease_token": None,
            "candidate_manifest_json": None,
            "last_error_code": None, "created_at": at, "updated_at": at,
        }
        row = tx.run(_ENQUEUE, owner_id=owner, brief_id=brief.id, properties=properties).single()
        job = _job_from_row(row)
        if job is None:
            raise JobStoreError("job enqueue did not return a record")
        return job

    def claim(self, *, worker_id: str, lease_seconds: int = 60,
              now: datetime | None = None) -> GraphJob | None:
        worker = _identifier(worker_id, "worker_id")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise JobStoreError("lease_seconds must be between 1 and 3600")
        instant = _time(now)
        expiry = _stored_time(instant + timedelta(seconds=lease_seconds))
        token = token_urlsafe(32)

        def claim_tx(tx: Any) -> GraphJob | None:
            tx.run(_CLAIM_LOCK, owner_id=self.owner_id).single()
            tx.run(_EXPIRE_EXHAUSTED, owner_id=self.owner_id, now=_stored_time(instant))
            row = tx.run(
                _CLAIM, owner_id=self.owner_id, worker_id=worker, lease_token=token,
                lease_expires_at=expiry, now=_stored_time(instant),
            ).single()
            return _job_from_row(row)

        with self.driver.session(database=self.database) as session:
            return session.execute_write(claim_tx)

    def persist_candidate_manifest(self, job_id: str, lease_token: str,
                                   candidate_ids: tuple[str, ...] | list[str], *,
                                   now: datetime | None = None) -> GraphJob:
        candidates = self._candidate_ids(candidate_ids)
        instant = _time(now)
        encoded = json.dumps(candidates, ensure_ascii=True, separators=(",", ":"))
        row = self._run_write(_MANIFEST, job_id=job_id, lease_token=lease_token,
                              manifest_json=encoded, now=_stored_time(instant))
        if row is None:
            current = self.get(job_id)
            if current and current.candidate_ids is not None and current.candidate_ids != candidates:
                raise JobConflictError("candidate manifest is immutable")
            raise JobLeaseError("job lease is no longer active")
        return row

    @staticmethod
    def _candidate_ids(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        if not isinstance(values, (tuple, list)) or len(values) > 256:
            raise JobStoreError("candidate manifest must contain at most 256 IDs")
        candidates = tuple(values)
        if any(not isinstance(item, str) or not _CANDIDATE_ID.fullmatch(item) for item in candidates):
            raise JobStoreError("candidate manifest IDs are invalid")
        candidates = tuple(sorted(candidates))
        if len(candidates) != len(set(candidates)):
            raise JobStoreError("candidate manifest IDs must be unique")
        return candidates

    def complete(self, job_id: str, lease_token: str, *, now: datetime | None = None) -> GraphJob:
        instant = _time(now)
        return self._required_write(_COMPLETE, job_id=job_id, lease_token=lease_token,
                                    now=_stored_time(instant))

    def fail(self, job_id: str, lease_token: str, *, error_code: str,
             retry_after_seconds: int = 0, now: datetime | None = None) -> GraphJob:
        code = _identifier(error_code, "error_code").casefold()
        if not _ERROR_CODE.fullmatch(code):
            raise JobStoreError("error_code must be a short machine-readable code")
        if type(retry_after_seconds) is not int or not 0 <= retry_after_seconds <= 86_400:
            raise JobStoreError("retry_after_seconds must be between 0 and 86400")
        instant = _time(now)
        return self._required_write(
            _FAIL, job_id=job_id, lease_token=lease_token, error_code=code,
            retry_at=_stored_time(instant + timedelta(seconds=retry_after_seconds)),
            now=_stored_time(instant),
        )

    @staticmethod
    def mark_superseded_tx(tx: Any, *, owner_id: str, idea_lineage_root_id: str,
                           current_brief_id: str, now: datetime | None = None) -> int:
        """Supersede older active jobs within a caller's Brief-save transaction."""
        result = tx.run(
            _SUPERSEDE, owner_id=_identifier(owner_id, "owner_id"),
            idea_lineage_root_id=_identifier(idea_lineage_root_id, "idea_lineage_root_id"),
            current_brief_id=_identifier(current_brief_id, "current_brief_id"),
            now=_stored_time(_time(now)),
        ).single()
        return int(result.get("count", 0)) if isinstance(result, Mapping) else 0

    def get(self, job_id: str) -> GraphJob | None:
        with self.driver.session(database=self.database) as session:
            row = session.execute_read(lambda tx: tx.run(
                _GET, owner_id=self.owner_id, job_id=_identifier(job_id, "job_id"),
            ).single())
        return _job_from_row(row)

    def _run_write(self, query: str, **params: Any) -> GraphJob | None:
        job_id = _identifier(params.pop("job_id"), "job_id")
        with self.driver.session(database=self.database) as session:
            row = session.execute_write(lambda tx: tx.run(
                query, owner_id=self.owner_id, job_id=job_id, **params,
            ).single())
        return _job_from_row(row)

    def _required_write(self, query: str, **params: Any) -> GraphJob:
        row = self._run_write(query, **params)
        if row is None:
            raise JobLeaseError("job lease is no longer active")
        return row
