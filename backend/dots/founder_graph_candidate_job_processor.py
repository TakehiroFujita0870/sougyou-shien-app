"""Owner-scoped worker for durable relation-candidate jobs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
import hashlib
from typing import Any

from .founder_graph import (
    Evidence,
    EvidencePolarity,
    Idea,
    NodeType,
    Provenance,
    ProvenanceOrigin,
    RelationAssertion,
    Status,
    EgressPolicy,
)
from .founder_graph_job_store import (
    CandidatePayloadManifest,
    GraphJob,
    JobState,
    JobStoreError,
)
from .founder_graph_neo4j_write import PersistedNodeReference
from .idea_brief import IdeaBriefVersion
from .relation_candidate_manifest import (
    CandidateEntityRef,
    CandidateManifestValidationError,
    ValidatedRelationCandidateManifest,
    preflight_relation_candidate_manifest,
    validate_relation_candidate_manifest,
)
from .source_citations import evidence_lineage_is_current


class CandidateManifestConflictError(ValueError):
    """A replay tried to change the manifest already bound to a saved Brief job."""

    code = "candidate_manifest_conflict"

    def __init__(self) -> None:
        super().__init__("candidate manifest conflicts with the saved Brief job")


class RelationCandidateJobProcessor:
    """Validate once, persist quote-free retry data, and apply assertions idempotently."""

    def __init__(self, *, jobs: Any, writes: Any, brief_store: Any, worker_id: str) -> None:
        owner_id = getattr(writes, "owner_id", None)
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("an owner-bound graph write service is required")
        if getattr(jobs, "owner_id", owner_id) != owner_id:
            raise ValueError("graph job store and write service must share an owner")
        self.jobs = jobs
        self.writes = writes
        self.brief_store = brief_store
        self.owner_id = owner_id
        self.worker_id = worker_id

    def process_specific(
        self,
        job_id: str,
        *,
        raw_manifest: Mapping[str, object] | None = None,
    ) -> GraphJob | None:
        """Process only this Brief's job; graph failures never remove the saved Brief."""
        current = self.jobs.get(job_id)
        if current is None or current.owner_id != self.owner_id:
            return None
        if current.state is JobState.SUPERSEDED:
            # Save-key replay for a stale Brief returns its truthful terminal state;
            # this job can no longer write, regardless of any replayed manifest.
            return current
        if raw_manifest is not None:
            if current.candidate_payload_persisted:
                self._assert_manifest_matches_job(current, raw_manifest)
            elif current.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.SUPERSEDED}:
                raise CandidateManifestConflictError
        if current.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.SUPERSEDED}:
            return current
        # Jobs without candidates are valid queue records. Do not lease or consume an
        # attempt until a manifest is supplied; invalid ingress retries also stay put.
        if raw_manifest is None and not current.candidate_payload_persisted:
            return current

        lease = self.jobs.claim_specific(job_id, worker_id=self.worker_id)
        if lease is None:
            return self.jobs.get(job_id)
        if lease.owner_id != self.owner_id or not lease.lease_token:
            return self.jobs.get(job_id)
        token = lease.lease_token

        try:
            latest_brief = self._latest_brief(lease.idea_lineage_root_id)
            current_idea_id = self._current_idea_id(lease.idea_lineage_root_id)
            if latest_brief is None or current_idea_id is None:
                return self._fail(job_id, token, "candidate_context_missing")
            if (
                latest_brief.owner_id != self.owner_id
                or latest_brief.idea_lineage_root_id != lease.idea_lineage_root_id
            ):
                return self._fail(job_id, token, "candidate_context_invalid")
            if lease.brief_id != latest_brief.id or lease.based_on_idea_id != current_idea_id:
                return self.jobs.supersede_stale(
                    job_id, token, current_brief_id=latest_brief.id,
                    current_idea_id=current_idea_id,
                )

            persisted = self.jobs.get_candidate_payloads(job_id, token)
            if persisted is None:
                if raw_manifest is None:
                    # A legacy/corrupt pending job without either ingress or payload
                    # is not success. Leave it retryable without fabricating a result.
                    return self._fail(job_id, token, "candidate_payload_missing")
                validated = self._validate_raw(raw_manifest, latest_brief, current_idea_id)
                lease = self.jobs.persist_candidate_manifest(job_id, token, validated)
                persisted = self.jobs.get_candidate_payloads(job_id, token)
                if persisted is None:
                    return self._fail(job_id, token, "candidate_payload_missing")

            validated = self._rehydrate_and_validate(
                persisted, latest_brief=latest_brief, current_idea_id=current_idea_id,
            )
            for candidate in validated.candidates:
                self._apply_assertion(candidate.assertion)
            return self.jobs.complete(job_id, token)
        except CandidateManifestValidationError:
            return self._fail(job_id, token, "candidate_manifest_invalid")
        except JobStoreError:
            return self._fail(job_id, token, "candidate_payload_invalid")
        except Exception:
            # Deliberately store only a stable code, never provider/DB/report text.
            return self._fail(job_id, token, "candidate_processing_failed")

    def _fail(self, job_id: str, token: str, code: str) -> GraphJob:
        return self.jobs.fail(job_id, token, error_code=code, retry_after_seconds=0)

    def _assert_manifest_matches_job(
        self,
        job: GraphJob,
        manifest: Mapping[str, object],
    ) -> None:
        """Reject a changed replay before claiming or mutating the durable job."""
        try:
            latest_brief = self._latest_brief(job.idea_lineage_root_id)
            current_idea_id = self._current_idea_id(job.idea_lineage_root_id)
            if (
                latest_brief is None or current_idea_id is None
                or latest_brief.id != job.brief_id
                or current_idea_id != job.based_on_idea_id
            ):
                raise CandidateManifestConflictError
            validated = self._validate_raw(manifest, latest_brief, current_idea_id)
            candidate_ids = tuple(item.candidate_id for item in validated.candidates)
            if candidate_ids != job.candidate_ids:
                raise CandidateManifestConflictError
        except CandidateManifestConflictError:
            raise
        except Exception:
            raise CandidateManifestConflictError from None

    def _latest_brief(self, root_id: str) -> IdeaBriefVersion | None:
        getter = getattr(self.brief_store, "get_latest", None)
        if not callable(getter):
            getter = getattr(self.brief_store, "get_latest_idea_brief", None)
        if not callable(getter):
            getter = getattr(self.writes, "get_latest_idea_brief", None)
        return getter(root_id) if callable(getter) else None

    def _current_idea_id(self, root_id: str) -> str | None:
        nodes = getattr(self.writes, "nodes", None)
        if callable(nodes):
            ideas = tuple(node for node in nodes() if isinstance(node, Idea) and node.owner_id == self.owner_id)
            by_id = {idea.id: idea for idea in ideas}
            current = by_id.get(root_id)
            if current is None or current.supersedes_id is not None:
                return None
            seen = {current.id}
            while True:
                children = [idea for idea in ideas if idea.supersedes_id == current.id]
                if len(children) > 1:
                    return None
                if not children:
                    return current.id
                child = children[0]
                if child.id in seen or child.revision != current.revision + 1:
                    return None
                seen.add(child.id)
                current = child

        gateway = getattr(self.writes, "gateway", None)
        if gateway is None:
            return None
        try:
            with gateway.read_session() as session:
                chain = gateway.execute_read(
                    session, lambda tx: gateway.read_idea_chain_tx(tx, root_id),
                )
            return chain[-1].id if chain else None
        except Exception:
            return None

    def _resolve_refs(self, ids: set[str]) -> tuple[dict[str, CandidateEntityRef], dict[str, Evidence]]:
        entity_refs: dict[str, CandidateEntityRef] = {}
        evidence: dict[str, Evidence] = {}
        for identifier in ids:
            node = self.writes.get_node(identifier)
            if node is None:
                continue
            owner_id = getattr(node, "owner_id", None)
            node_id = getattr(node, "id", None)
            raw_kind = getattr(node, "node_type", None)
            raw_egress_policy = getattr(node, "egress_policy", None)
            if isinstance(node, PersistedNodeReference):
                raw_kind = node.node_type
                fields = node.fields
                raw_egress_policy = fields.get("egress_policy") if isinstance(fields, Mapping) else None
            if owner_id != self.owner_id or node_id != identifier:
                continue
            try:
                kind = raw_kind if isinstance(raw_kind, NodeType) else NodeType(raw_kind)
            except (TypeError, ValueError):
                continue
            entity_refs[identifier] = CandidateEntityRef(
                identifier, owner_id, kind, raw_egress_policy,
            )
            if kind is NodeType.EVIDENCE:
                hydrated = self._hydrate_evidence(node)
                if hydrated is not None and evidence_lineage_is_current(
                    self.writes, identifier, self.owner_id,
                ):
                    evidence[identifier] = hydrated
        return entity_refs, evidence

    def _hydrate_evidence(self, node: Any) -> Evidence | None:
        if isinstance(node, Evidence):
            return node
        if not isinstance(node, PersistedNodeReference) or node.node_type is not NodeType.EVIDENCE:
            return None
        try:
            payload = dict(node.fields)
            provenance = payload.get("provenance")
            if not isinstance(provenance, Mapping):
                return None
            provenance_values = dict(provenance)
            occurred_at = provenance_values.get("occurred_at")
            if isinstance(occurred_at, str):
                provenance_values["occurred_at"] = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            provenance_values["origin"] = ProvenanceOrigin(provenance_values["origin"])
            payload["provenance"] = Provenance(**provenance_values)
            payload["polarity"] = EvidencePolarity(payload["polarity"])
            payload["status"] = Status(payload["status"])
            payload["egress_policy"] = EgressPolicy(payload["egress_policy"])
            return Evidence(**payload)
        except (KeyError, TypeError, ValueError):
            return None

    def _validate_raw(
        self,
        manifest: Mapping[str, object],
        brief: IdeaBriefVersion,
        current_idea_id: str,
    ) -> ValidatedRelationCandidateManifest:
        candidates = preflight_relation_candidate_manifest(manifest)
        ids = self._manifest_entity_ids(candidates)
        entity_refs, evidence = self._resolve_refs(ids)
        return validate_relation_candidate_manifest(
            manifest, latest_brief=brief, current_idea_id=current_idea_id,
            entity_refs=entity_refs, source_grounded_evidence=evidence,
        )

    @staticmethod
    def _manifest_entity_ids(candidates: tuple[Mapping[str, object], ...]) -> set[str]:
        ids: set[str] = set()
        for candidate in candidates:
            for field in ("source_id", "target_id", "evidence_ids"):
                value = candidate.get(field)
                if isinstance(value, str):
                    ids.add(value)
                elif field == "evidence_ids" and isinstance(value, (list, tuple)):
                    ids.update(item for item in value if isinstance(item, str))
        return ids

    def _rehydrate_and_validate(
        self,
        payload: CandidatePayloadManifest,
        *,
        latest_brief: IdeaBriefVersion,
        current_idea_id: str,
    ) -> ValidatedRelationCandidateManifest:
        markdown = latest_brief.report_markdown
        if not isinstance(markdown, str):
            raise CandidateManifestValidationError("latest Brief Markdown is required")
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        if (
            payload.version != 1 or payload.brief_id != latest_brief.id
            or payload.brief_revision != latest_brief.revision
            or payload.idea_id != current_idea_id
            or payload.brief_markdown_sha256 != digest
        ):
            raise CandidateManifestValidationError("persisted candidate payload is stale")

        raw_candidates: list[dict[str, object]] = []
        for candidate in payload.candidates:
            support: dict[str, object]
            if candidate.support.kind == "quote":
                start, end = candidate.support.char_start, candidate.support.char_end
                if (
                    type(start) is not int or type(end) is not int
                    or start < 0 or end <= start or end > len(markdown)
                ):
                    raise CandidateManifestValidationError("persisted quote offsets are invalid")
                support = {"quote": markdown[start:end]}
            elif candidate.support.kind == "section":
                support = {"section_index": candidate.support.section_index}
            else:
                raise CandidateManifestValidationError("persisted support kind is invalid")
            raw_candidates.append({
                "source_id": candidate.source_id,
                "target_id": candidate.target_id,
                "predicate": candidate.predicate,
                "basis": candidate.basis,
                "support": support,
                "evidence_ids": list(candidate.evidence_ids),
            })
        raw = {"version": 1, "idea_id": current_idea_id, "candidates": raw_candidates}
        validated = self._validate_raw(raw, latest_brief, current_idea_id)
        if tuple(item.candidate_id for item in validated.candidates) != payload.candidate_ids:
            raise CandidateManifestValidationError("persisted candidate identity does not match current sources")
        return validated

    def _apply_assertion(self, assertion: RelationAssertion) -> None:
        family = self._relation_family(assertion.assertion_family_id)
        existing = next((item for item in family if item.id == assertion.id), None)
        if existing is not None:
            if not self._same_candidate(existing, assertion):
                raise ValueError("persisted relation candidate identity conflicts")
            return
        latest = max(family, key=lambda item: item.revision) if family else None
        if latest is not None:
            assertion = replace(
                assertion, revision=latest.revision + 1, supersedes_id=latest.id,
            )
        self.writes.save_relation_assertion(
            assertion,
            expected_family_revision=None if latest is None else latest.revision,
            idempotency_key=f"graph-job:{assertion.id}",
            actor="dots_candidate_job_processor",
        )

    @staticmethod
    def _same_candidate(existing: RelationAssertion, candidate: RelationAssertion) -> bool:
        return all(getattr(existing, field) == getattr(candidate, field) for field in (
            "owner_id", "source_id", "target_id", "source_kind", "target_kind", "predicate",
            "assertion_family_id", "status", "basis", "evidence_ids", "based_on_brief_id",
            "based_on_brief_section_index", "based_on_brief_revision",
            "based_on_brief_quote_start", "based_on_brief_quote_end",
        ))

    def _relation_family(self, family_id: str) -> tuple[RelationAssertion, ...]:
        nodes = getattr(self.writes, "nodes", None)
        if callable(nodes):
            return tuple(
                node for node in nodes()
                if isinstance(node, RelationAssertion)
                and node.owner_id == self.owner_id and node.assertion_family_id == family_id
            )
        gateway = getattr(self.writes, "gateway", None)
        if gateway is None:
            raise ValueError("relation family read is unavailable")
        label = gateway.label_for(NodeType.RELATION_ASSERTION)
        with gateway.read_session() as session:
            def read(tx: Any) -> tuple[RelationAssertion, ...]:
                result = tx.run(
                    f"MATCH (a:{label} {{owner_id: $owner_id, assertion_family_id: $family_id}}) "
                    "RETURN properties(a) AS record ORDER BY a.revision ASC",
                    owner_id=self.owner_id, family_id=family_id,
                )
                records = result.data() if callable(getattr(result, "data", None)) else list(result)
                return tuple(
                    gateway._decode_relation_assertion_record(row["record"])
                    for row in records
                )
            return gateway.execute_read(session, read)


__all__ = ["RelationCandidateJobProcessor"]
