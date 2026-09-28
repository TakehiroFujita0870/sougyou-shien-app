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
class CandidatePayloadSupport:
    kind: str
    char_start: int | None = None
    char_end: int | None = None
    section_index: int | None = None


@dataclass(frozen=True, slots=True)
class RelationCandidatePayload:
    candidate_id: str
    source_id: str
    source_kind: str
    target_id: str
    target_kind: str
    predicate: str
    basis: str
    evidence_ids: tuple[str, ...]
    support: CandidatePayloadSupport


@dataclass(frozen=True, slots=True)
class CandidatePayloadManifest:
    version: int
    idea_id: str
    brief_id: str
    brief_revision: int
    brief_markdown_sha256: str
    candidates: tuple[RelationCandidatePayload, ...]

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate.candidate_id for candidate in self.candidates)


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
    candidate_payload_persisted: bool
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


_JOB_ID_PREFIX = "graph-job_"
_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,63}$")
_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9:_-]{1,200}$")
_ENUM_VALUE = re.compile(r"^[a-z][a-z0-9:_-]{0,63}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_CANDIDATE_PAYLOAD_BYTES = 64 * 1024

_ENQUEUE = """// graph_job:enqueue
MERGE (job:FounderGraphJob {owner_id: $owner_id, brief_id: $brief_id})
ON CREATE SET job = $properties RETURN properties(job) AS job"""
_CLAIM_LOCK = """// graph_job:claim_lock
MERGE (lock:FounderGraphJobQueueLock {owner_id: $owner_id}) ON CREATE SET lock.version = 0
SET lock.version = lock.version + 1 RETURN lock.version AS version"""
_EXPIRE_EXHAUSTED = """// graph_job:expire_exhausted
MATCH (job:FounderGraphJob {owner_id: $owner_id})
WHERE ($job_id IS NULL OR job.id = $job_id) AND job.state = 'leased'
  AND job.lease_expires_at <= $now AND job.attempt_count >= job.max_attempts
SET job.state = 'failed', job.last_error_code = 'attempts_exhausted', job.lease_owner = null,
    job.lease_token = null, job.lease_expires_at = null, job.updated_at = $now RETURN count(job) AS expired"""
_CLAIM = """// graph_job:claim
MATCH (job:FounderGraphJob {owner_id: $owner_id})
WHERE ($job_id IS NULL OR job.id = $job_id) AND (
      (job.state = 'leased' AND job.lease_owner = $worker_id AND job.lease_expires_at > $now)
  OR (job.available_at <= $now AND job.attempt_count < job.max_attempts AND
      (job.state = 'pending' OR (job.state = 'leased' AND job.lease_expires_at <= $now))))
WITH job, (job.state = 'leased' AND job.lease_owner = $worker_id AND job.lease_expires_at > $now) AS same_lease
ORDER BY CASE WHEN same_lease THEN 0 ELSE 1 END, job.available_at, job.created_at, job.id LIMIT 1
SET job.state = 'leased', job.attempt_count = job.attempt_count + CASE WHEN same_lease THEN 0 ELSE 1 END,
    job.lease_owner = $worker_id, job.lease_token = CASE WHEN same_lease THEN job.lease_token ELSE $lease_token END,
    job.lease_expires_at = CASE WHEN same_lease THEN job.lease_expires_at ELSE $lease_expires_at END,
    job.updated_at = CASE WHEN same_lease THEN job.updated_at ELSE $now END
RETURN properties(job) AS job"""
_GET = """// graph_job:get
MATCH (job:FounderGraphJob {owner_id: $owner_id, id: $job_id}) RETURN properties(job) AS job"""
_INSPECTION = """// graph_job:inspection
MATCH (job:FounderGraphJob {owner_id: $owner_id})
WHERE job.state = 'failed' OR (job.state = 'pending' AND job.available_at <= $now)
WITH job
ORDER BY CASE WHEN job.state = 'pending' THEN 0 ELSE 1 END,
         job.available_at ASC, job.updated_at ASC, job.id ASC
LIMIT $limit
RETURN properties(job) AS job"""
_PAYLOADS = """// graph_job:payloads
MATCH (job:FounderGraphJob {owner_id: $owner_id, id: $job_id})
WHERE job.state = 'leased' AND job.lease_token = $lease_token AND job.lease_expires_at > $now
RETURN properties(job) AS job"""
_MANIFEST = """// graph_job:manifest
MATCH (job:FounderGraphJob {owner_id: $owner_id, id: $job_id})
WHERE job.state = 'leased' AND job.lease_token = $lease_token AND job.lease_expires_at > $now
  AND job.based_on_idea_id = $idea_id AND job.brief_id = $brief_id
  AND ((job.candidate_manifest_json IS NULL AND job.candidate_payloads_json IS NULL) OR
       (job.candidate_manifest_json = $manifest_json AND job.candidate_payloads_json = $candidate_payloads_json))
SET job.candidate_manifest_json = $manifest_json, job.candidate_payloads_json = $candidate_payloads_json,
    job.updated_at = CASE WHEN job.candidate_manifest_json IS NULL THEN $now ELSE job.updated_at END
RETURN properties(job) AS job"""
_COMPLETE = """// graph_job:complete
MATCH (job:FounderGraphJob {owner_id: $owner_id, id: $job_id})
WHERE (job.state = 'leased' AND job.lease_token = $lease_token AND job.lease_expires_at > $now) OR
      (job.state = 'succeeded' AND job.last_transition = 'complete' AND job.last_lease_token = $lease_token)
WITH job, job.state = 'leased' AS active
SET job.last_transition = CASE WHEN active THEN 'complete' ELSE job.last_transition END,
    job.last_lease_token = CASE WHEN active THEN $lease_token ELSE job.last_lease_token END,
    job.state = 'succeeded', job.lease_owner = null, job.lease_token = null,
    job.lease_expires_at = null,
    job.last_error_code = null,
    job.updated_at = CASE WHEN active THEN $now ELSE job.updated_at END
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
_SUPERSEDE_STALE = """// graph_job:supersede_stale
MATCH (job:FounderGraphJob {owner_id: $owner_id, id: $job_id})
WHERE (job.state = 'leased' AND job.lease_token = $lease_token AND job.lease_expires_at > $now
       AND (job.brief_id <> $current_brief_id OR job.based_on_idea_id <> $current_idea_id))
   OR (job.state = 'superseded' AND job.last_transition = 'supersede' AND job.last_lease_token = $lease_token)
WITH job, job.state = 'leased' AS active
SET job.state = 'superseded',
    job.last_transition = CASE WHEN active THEN 'supersede' ELSE job.last_transition END,
    job.last_lease_token = CASE WHEN active THEN $lease_token ELSE job.last_lease_token END,
    job.last_error_code = CASE WHEN active THEN 'stale_version' ELSE job.last_error_code END,
    job.lease_owner = null, job.lease_token = null, job.lease_expires_at = null,
    job.updated_at = CASE WHEN active THEN $now ELSE job.updated_at END
RETURN properties(job) AS job"""


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


def _value(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name)


def _enum_value(value: Any, name: str) -> str:
    value = getattr(value, "value", value)
    if not isinstance(value, str) or not _ENUM_VALUE.fullmatch(value):
        raise JobStoreError(f"candidate {name} is invalid")
    return value


def _payload_mapping(value: Any) -> dict[str, Any]:
    """Project only the validator's safe metadata; quote/report text is never read."""
    try:
        candidates = []
        for candidate in _value(value, "candidates"):
            assertion = _value(candidate, "assertion")
            support = _value(candidate, "support")
            kind = _enum_value(_value(support, "kind"), "support kind")
            payload_support: dict[str, Any] = {"kind": kind}
            if kind == "quote":
                payload_support.update(
                    char_start=_value(support, "char_start"),
                    char_end=_value(support, "char_end"),
                    section_index=_value(support, "section_index"),
                )
            elif kind == "section":
                payload_support["section_index"] = _value(support, "section_index")
            else:
                raise JobStoreError("candidate support kind is invalid")
            candidates.append({
                "candidate_id": _value(candidate, "candidate_id"),
                "source_id": _value(assertion, "source_id"),
                "source_kind": _value(assertion, "source_kind"),
                "target_id": _value(assertion, "target_id"),
                "target_kind": _value(assertion, "target_kind"),
                "predicate": _value(assertion, "predicate"),
                "basis": _value(assertion, "basis"),
                "evidence_ids": list(_value(assertion, "evidence_ids")),
                "support": payload_support,
            })
        return {
            "version": 1,
            "idea_id": _value(value, "idea_id"),
            "brief_id": _value(value, "brief_id"),
            "brief_revision": _value(value, "brief_revision"),
            "brief_markdown_sha256": _value(value, "brief_markdown_sha256"),
            "candidates": candidates,
        }
    except (AttributeError, TypeError) as exc:
        raise JobStoreError("validated candidate manifest fields are invalid") from exc


def _payload_from_mapping(value: Any) -> CandidatePayloadManifest:
    expected = {
        "version", "idea_id", "brief_id", "brief_revision", "brief_markdown_sha256", "candidates",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise JobStoreError("candidate payload manifest fields are invalid")
    if type(value["version"]) is not int or value["version"] != 1:
        raise JobStoreError("candidate payload version is unsupported")
    idea_id, brief_id = _identifier(value["idea_id"], "idea_id"), _identifier(value["brief_id"], "brief_id")
    revision = value["brief_revision"]
    digest = value["brief_markdown_sha256"]
    if type(revision) is not int or revision < 1 or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise JobStoreError("candidate payload Brief binding is invalid")
    raw_candidates = value["candidates"]
    if not isinstance(raw_candidates, (list, tuple)) or len(raw_candidates) > 64:
        raise JobStoreError("candidate payload must contain between 0 and 64 candidates")
    candidates: list[RelationCandidatePayload] = []
    for raw in raw_candidates:
        keys = {
            "candidate_id", "source_id", "source_kind", "target_id", "target_kind",
            "predicate", "basis", "evidence_ids", "support",
        }
        if not isinstance(raw, Mapping) or set(raw) != keys:
            raise JobStoreError("candidate payload fields are invalid")
        candidate_id = raw["candidate_id"]
        if not isinstance(candidate_id, str) or not _CANDIDATE_ID.fullmatch(candidate_id):
            raise JobStoreError("candidate ID is invalid")
        ids = [_identifier(raw[key], key) for key in ("source_id", "target_id")]
        values = [_enum_value(raw[key], key) for key in ("source_kind", "target_kind", "predicate", "basis")]
        evidence = raw["evidence_ids"]
        if not isinstance(evidence, (list, tuple)) or len(evidence) > 32:
            raise JobStoreError("candidate Evidence IDs exceed the limit")
        evidence_ids = tuple(sorted(_identifier(item, "evidence_id") for item in evidence))
        if len(evidence_ids) != len(set(evidence_ids)):
            raise JobStoreError("candidate Evidence IDs must be unique")
        raw_support = raw["support"]
        if not isinstance(raw_support, Mapping) or raw_support.get("kind") not in {"quote", "section"}:
            raise JobStoreError("candidate support fields are invalid")
        kind = raw_support["kind"]
        if kind == "quote":
            if set(raw_support) != {"kind", "char_start", "char_end", "section_index"}:
                raise JobStoreError("quote support fields are invalid")
            start, end, section = raw_support["char_start"], raw_support["char_end"], raw_support["section_index"]
            if (type(start) is not int or type(end) is not int or start < 0 or end <= start
                    or end > 60_000 or end - start > 1_200):
                raise JobStoreError("quote support offsets are invalid")
            if section is not None and (type(section) is not int or not 0 <= section <= 7):
                raise JobStoreError("quote support section index is invalid")
            if section is None and values[3] != "brief_hypothesis":
                raise JobStoreError("unsectioned quote support requires a Brief hypothesis")
            support = CandidatePayloadSupport(kind, start, end, section)
        else:
            if set(raw_support) != {"kind", "section_index"}:
                raise JobStoreError("section support fields are invalid")
            section = raw_support["section_index"]
            if type(section) is not int or not 0 <= section <= 7:
                raise JobStoreError("section support index is invalid")
            support = CandidatePayloadSupport(kind, section_index=section)
        candidates.append(RelationCandidatePayload(
            candidate_id, ids[0], values[0], ids[1], values[1], values[2], values[3], evidence_ids, support,
        ))
    candidates.sort(key=lambda item: item.candidate_id)
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise JobStoreError("candidate IDs must be unique")
    return CandidatePayloadManifest(1, idea_id, brief_id, revision, digest, tuple(candidates))


def _payload_to_mapping(manifest: CandidatePayloadManifest) -> dict[str, Any]:
    candidates = []
    for candidate in manifest.candidates:
        support = {"kind": candidate.support.kind}
        if candidate.support.kind == "quote":
            support.update(char_start=candidate.support.char_start, char_end=candidate.support.char_end,
                           section_index=candidate.support.section_index)
        else:
            support["section_index"] = candidate.support.section_index
        candidates.append({
            "candidate_id": candidate.candidate_id, "source_id": candidate.source_id,
            "source_kind": candidate.source_kind, "target_id": candidate.target_id,
            "target_kind": candidate.target_kind, "predicate": candidate.predicate,
            "basis": candidate.basis, "evidence_ids": list(candidate.evidence_ids), "support": support,
        })
    return {
        "version": 1, "idea_id": manifest.idea_id, "brief_id": manifest.brief_id,
        "brief_revision": manifest.brief_revision, "brief_markdown_sha256": manifest.brief_markdown_sha256,
        "candidates": candidates,
    }


def _encode_candidate_payload(value: Any) -> tuple[CandidatePayloadManifest, str]:
    payload = _payload_from_mapping(_payload_mapping(value))
    encoded = json.dumps(_payload_to_mapping(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_CANDIDATE_PAYLOAD_BYTES:
        raise JobStoreError("candidate payload exceeds 64 KiB")
    return payload, encoded


def _parse_candidate_payload(encoded: str) -> CandidatePayloadManifest:
    if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > _MAX_CANDIDATE_PAYLOAD_BYTES:
        raise ValueError("candidate payload size is invalid")
    try:
        payload = _payload_from_mapping(json.loads(encoded))
        canonical = json.dumps(_payload_to_mapping(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if canonical != encoded:
            raise ValueError("candidate payload is not canonical")
        return payload
    except (TypeError, json.JSONDecodeError, JobStoreError) as exc:
        raise ValueError("candidate payload is invalid") from exc


def _job_from_row(row: Any) -> GraphJob | None:
    if row is None:
        return None
    try:
        props = dict(row["job"])
        candidates = props.pop("candidate_manifest_json", None)
        payload_json = props.pop("candidate_payloads_json", None)
        candidates = None if candidates is None else json.loads(candidates)
        if candidates is not None and (not isinstance(candidates, list) or
            any(not isinstance(item, str) or not _CANDIDATE_ID.fullmatch(item) for item in candidates) or
            len(candidates) != len(set(candidates))): raise ValueError
        payload = None if payload_json is None else _parse_candidate_payload(payload_json)
        candidate_ids = None if candidates is None else tuple(candidates)
        if (payload is not None and (candidate_ids != payload.candidate_ids or
                props.get("brief_id") != payload.brief_id or props.get("based_on_idea_id") != payload.idea_id)):
            raise ValueError
        if payload_json is not None and candidate_ids is None:
            raise ValueError
        props["candidate_ids"], props["candidate_payload_persisted"] = candidate_ids, payload is not None
        props["state"] = JobState(props["state"])
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

    @staticmethod
    def job_id_for(owner_id: str, brief_id: str) -> str:
        """Return the canonical durable job ID for an owner and saved Brief."""
        return _job_id(_identifier(owner_id, "owner_id"), _identifier(brief_id, "brief_id"))

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
        identity = FounderGraphJobStore.job_id_for(owner, brief.id)
        at = _stored_time(instant)
        properties = {
            "id": identity, "owner_id": owner, "brief_id": brief.id,
            "idea_lineage_root_id": brief.idea_lineage_root_id,
            "based_on_idea_id": brief.based_on_idea_id, "state": JobState.PENDING.value,
            "attempt_count": 0, "max_attempts": max_attempts,
            "available_at": at, "lease_owner": None, "lease_token": None,
            "lease_expires_at": None, "last_transition": None, "last_lease_token": None,
            "candidate_manifest_json": None,
            "candidate_payloads_json": None,
            "last_error_code": None, "created_at": at, "updated_at": at,
        }
        row = tx.run(_ENQUEUE, owner_id=owner, brief_id=brief.id, properties=properties).single()
        job = _job_from_row(row)
        if job is None:
            raise JobStoreError("job enqueue did not return a record")
        return job

    def claim(self, *, worker_id: str, lease_seconds: int = 60,
              now: datetime | None = None) -> GraphJob | None:
        return self._claim(None, worker_id=worker_id, lease_seconds=lease_seconds, now=now)

    def claim_specific(self, job_id: str, *, worker_id: str, lease_seconds: int = 60,
                       now: datetime | None = None) -> GraphJob | None:
        """Claim only the requested owner-scoped job, without consuming another job."""
        return self._claim(_identifier(job_id, "job_id"), worker_id=worker_id,
                           lease_seconds=lease_seconds, now=now)

    def _claim(self, job_id: str | None, *, worker_id: str, lease_seconds: int,
               now: datetime | None) -> GraphJob | None:
        worker = _identifier(worker_id, "worker_id")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise JobStoreError("lease_seconds must be between 1 and 3600")
        instant = _time(now)
        expiry = _stored_time(instant + timedelta(seconds=lease_seconds))
        token = token_urlsafe(32)

        def claim_tx(tx: Any) -> GraphJob | None:
            tx.run(_CLAIM_LOCK, owner_id=self.owner_id).single()
            tx.run(_EXPIRE_EXHAUSTED, owner_id=self.owner_id, job_id=job_id,
                   now=_stored_time(instant))
            row = tx.run(
                _CLAIM, owner_id=self.owner_id, worker_id=worker, lease_token=token,
                lease_expires_at=expiry, job_id=job_id, now=_stored_time(instant),
            ).single()
            return _job_from_row(row)

        with self.driver.session(database=self.database) as session:
            return session.execute_write(claim_tx)

    def persist_candidate_manifest(self, job_id: str, lease_token: str,
                                   validated_manifest: Any, *, now: datetime | None = None) -> GraphJob:
        """Atomically freeze candidate IDs and their bounded, quote-free retry payload."""
        payload, payload_json = _encode_candidate_payload(validated_manifest)
        candidates = payload.candidate_ids
        instant = _time(now)
        encoded = json.dumps(candidates, ensure_ascii=True, separators=(",", ":"))
        row = self._run_write(_MANIFEST, job_id=job_id, lease_token=lease_token,
                              manifest_json=encoded, candidate_payloads_json=payload_json,
                              brief_id=payload.brief_id, idea_id=payload.idea_id,
                              now=_stored_time(instant))
        if row is None:
            current = self.get(job_id)
            if (current and current.state is JobState.LEASED and current.lease_token == lease_token
                    and current.lease_expires_at is not None and current.lease_expires_at > instant):
                raise JobConflictError("candidate manifest is immutable")
            raise JobLeaseError("job lease is no longer active")
        return row

    def get_candidate_payloads(self, job_id: str, lease_token: str, *,
                               now: datetime | None = None) -> CandidatePayloadManifest | None:
        """Read retry data only for the job's current, unexpired lease."""
        instant = _time(now)
        with self.driver.session(database=self.database) as session:
            row = session.execute_read(lambda tx: tx.run(
                _PAYLOADS, owner_id=self.owner_id, job_id=_identifier(job_id, "job_id"),
                lease_token=lease_token, now=_stored_time(instant),
            ).single())
        if row is None:
            raise JobLeaseError("job lease is no longer active")
        job = _job_from_row(row)
        raw = dict(row["job"]).get("candidate_payloads_json")
        if job is None or raw is None:
            return None
        payload = _parse_candidate_payload(raw)
        if payload.brief_id != job.brief_id or payload.idea_id != job.based_on_idea_id:
            raise JobStoreError("persisted candidate payload is bound to another Brief")
        return payload

    @staticmethod
    def _candidate_ids(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        if not isinstance(values, (tuple, list)) or len(values) > 64:
            raise JobStoreError("candidate manifest must contain at most 64 IDs")
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

    def supersede_stale(self, job_id: str, lease_token: str, *, current_brief_id: str,
                        current_idea_id: str, now: datetime | None = None) -> GraphJob:
        """Terminally supersede this live lease only after its Brief or Idea is stale."""
        instant = _time(now)
        return self._required_write(
            _SUPERSEDE_STALE, job_id=job_id, lease_token=lease_token,
            current_brief_id=_identifier(current_brief_id, "current_brief_id"),
            current_idea_id=_identifier(current_idea_id, "current_idea_id"),
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

    def list_inspection_jobs(self, *, limit: int = 20,
                             now: datetime | None = None) -> tuple[GraphJob, ...]:
        """Read at most 20 due pending and terminal failed jobs for this owner."""
        if type(limit) is not int or not 1 <= limit <= 20:
            raise JobStoreError("inspection limit must be between 1 and 20")
        instant = _time(now)

        def read(tx: Any) -> list[Any]:
            result = tx.run(
                _INSPECTION, owner_id=self.owner_id, now=_stored_time(instant), limit=limit,
            )
            return result.data() if callable(getattr(result, "data", None)) else list(result)

        with self.driver.session(database=self.database) as session:
            rows = session.execute_read(read)
        jobs = tuple(_job_from_row(row) for row in rows)
        if len(jobs) > limit or any(
            job is None or job.owner_id != self.owner_id
            or not (job.state is JobState.FAILED or
                    job.state is JobState.PENDING and job.available_at <= instant)
            for job in jobs
        ):
            raise JobStoreError("inspection query returned invalid job records")
        return tuple(job for job in jobs if job is not None)

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
