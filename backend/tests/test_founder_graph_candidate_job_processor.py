from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from nebula.founder_graph import (
    Asset, AssetKind, Claim, Decision, EgressPolicy, Evidence, Idea, MaterialKind, NodeType,
    RelationAssertion, Source, SourceRevision, Status,
)
from nebula.founder_graph_job_store import (
    CandidatePayloadManifest,
    CandidatePayloadSupport,
    GraphJob,
    JobState,
    RelationCandidatePayload,
)
from nebula.founder_graph_mcp import McpReadSurface
from nebula.founder_graph_read import GraphReadService
from nebula.founder_graph_write import InMemoryGraphWriteService
from nebula.idea_brief import IdeaBriefSection, IdeaBriefVersion
from nebula.founder_graph_candidate_job_processor import RelationCandidateJobProcessor
from nebula.founder_graph_candidate_job_processor import CandidateManifestConflictError
from nebula.founder_graph_neo4j_write import PersistedNodeReference


OWNER = "owner-test"
IDEA = "idea-test"
ASSET = "asset-test"
BRIEF = "brief-test"
MARKDOWN = "## エグゼクティブサマリー\n\n小さな倉庫を活用する。\n"
NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


class MemoryJobStore:
    def __init__(self, brief: IdeaBriefVersion):
        self.owner_id = brief.owner_id
        self.job = GraphJob(
            id=f"graph-job-{brief.id}", owner_id=brief.owner_id, brief_id=brief.id,
            idea_lineage_root_id=brief.idea_lineage_root_id,
            based_on_idea_id=brief.based_on_idea_id, state=JobState.PENDING,
            attempt_count=0, max_attempts=3, available_at=NOW, lease_owner=None,
            lease_token=None, lease_expires_at=None, last_transition=None,
            last_lease_token=None, candidate_ids=None, candidate_payload_persisted=False,
            last_error_code=None, created_at=NOW, updated_at=NOW,
        )
        self.payload = None

    def get(self, job_id):
        return self.job if self.job.id == job_id else None

    def claim_specific(self, job_id, *, worker_id, lease_seconds=60, now=None):
        instant = now or NOW
        if self.job.id != job_id or self.job.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.SUPERSEDED}:
            return None
        if self.job.state is JobState.LEASED:
            if self.job.lease_owner != worker_id or self.job.lease_expires_at <= instant:
                return None
            return self.job
        self.job = replace(
            self.job, state=JobState.LEASED, attempt_count=self.job.attempt_count + 1,
            lease_owner=worker_id, lease_token=f"lease-{self.job.attempt_count + 1}",
            lease_expires_at=instant + timedelta(seconds=lease_seconds),
        )
        return self.job

    def persist_candidate_manifest(self, job_id, lease_token, validated, *, now=None):
        assert self.job.id == job_id and self.job.lease_token == lease_token
        self.payload = CandidatePayloadManifest(
            version=1, idea_id=validated.idea_id, brief_id=validated.brief_id,
            brief_revision=validated.brief_revision,
            brief_markdown_sha256=validated.brief_markdown_sha256,
            candidates=tuple(RelationCandidatePayload(
                candidate_id=item.candidate_id,
                source_id=item.assertion.source_id, source_kind=item.assertion.source_kind.value,
                target_id=item.assertion.target_id, target_kind=item.assertion.target_kind.value,
                predicate=item.assertion.predicate.value, basis=item.assertion.basis.value,
                evidence_ids=item.assertion.evidence_ids,
                support=CandidatePayloadSupport(
                    kind=item.support.kind, char_start=item.support.char_start,
                    char_end=item.support.char_end, section_index=item.support.section_index,
                ),
            ) for item in validated.candidates),
        )
        self.job = replace(self.job, candidate_ids=self.payload.candidate_ids,
                           candidate_payload_persisted=True)
        return self.job

    def get_candidate_payloads(self, job_id, lease_token, *, now=None):
        assert self.job.id == job_id and self.job.lease_token == lease_token
        return self.payload

    def complete(self, job_id, lease_token, *, now=None):
        assert self.job.id == job_id and self.job.lease_token == lease_token
        self.job = replace(self.job, state=JobState.SUCCEEDED, lease_owner=None,
                           lease_token=None, lease_expires_at=None, last_error_code=None)
        return self.job

    def fail(self, job_id, lease_token, *, error_code, retry_after_seconds=0, now=None):
        assert self.job.id == job_id and self.job.lease_token == lease_token
        state = JobState.FAILED if self.job.attempt_count >= self.job.max_attempts else JobState.PENDING
        self.job = replace(self.job, state=state, lease_owner=None, lease_token=None,
                           lease_expires_at=None, last_error_code=error_code)
        return self.job

    def supersede_stale(self, job_id, lease_token, *, current_brief_id, current_idea_id, now=None):
        assert self.job.id == job_id and self.job.lease_token == lease_token
        assert self.job.brief_id != current_brief_id or self.job.based_on_idea_id != current_idea_id
        self.job = replace(self.job, state=JobState.SUPERSEDED, lease_owner=None,
                           lease_token=None, lease_expires_at=None, last_error_code="stale_version")
        return self.job


def _brief(*, brief_id=BRIEF, revision=1, supersedes_id=None, markdown=MARKDOWN,
           egress_policy=EgressPolicy.LOCAL_ONLY):
    return IdeaBriefVersion(
        owner_id=OWNER, idea_lineage_root_id=IDEA, based_on_idea_id=IDEA,
        id=brief_id, revision=revision, supersedes_id=supersedes_id,
        report_markdown=markdown, egress_policy=egress_policy,
    )


def _manifest(quote="小さな倉庫を活用する。"):
    return {
        "version": 1,
        "idea_id": IDEA,
        "candidates": [{
            "source_id": IDEA, "target_id": ASSET, "predicate": "REUSES",
            "basis": "brief_hypothesis", "support": {"quote": quote}, "evidence_ids": [],
        }],
    }


def _context(brief=None, *, idea_policy=EgressPolicy.LOCAL_ONLY,
             asset_policy=EgressPolicy.LOCAL_ONLY):
    writes = InMemoryGraphWriteService(OWNER)
    idea = Idea(id=IDEA, owner_id=OWNER, title="倉庫案", status=Status.ACTIVE,
                egress_policy=idea_policy)
    asset = Asset(id=ASSET, owner_id=OWNER, name="倉庫", description="storage location",
                  egress_policy=asset_policy)
    writes.put_node(idea, idempotency_key="idea", expected_revision=0)
    writes.put_node(asset, idempotency_key="asset", expected_revision=0)
    saved_brief = brief or _brief()
    writes.save_idea_brief(saved_brief, expected_latest_revision=None, idempotency_key="brief")
    return writes, saved_brief


def test_process_specific_revalidates_and_applies_hypothesis_idempotently():
    writes, brief = _context()
    jobs = MemoryJobStore(brief)
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )

    result = processor.process_specific(jobs.job.id, raw_manifest=_manifest())

    assertions = [node for node in writes.nodes() if isinstance(node, RelationAssertion)]
    assert result.state is JobState.SUCCEEDED and result.candidate_payload_persisted
    assert len(assertions) == 1
    assert assertions[0].basis.value == "brief_hypothesis"
    assert assertions[0].status.value == "proposed" and assertions[0].evidence_ids == ()
    assert assertions[0].based_on_brief_id == brief.id
    assert assertions[0].based_on_brief_section_index == 0
    assert assertions[0].based_on_brief_revision == brief.revision
    assert (assertions[0].based_on_brief_quote_start, assertions[0].based_on_brief_quote_end) == (
        MARKDOWN.index("小さな倉庫を活用する。"),
        MARKDOWN.index("小さな倉庫を活用する。") + len("小さな倉庫を活用する。"),
    )
    assert not any(getattr(node, "node_type", None) is NodeType.EVIDENCE for node in writes.nodes())
    # Raw quote text is never stored on the assertion; the read projection resolves these offsets.
    assert jobs.payload.candidates[0].support.char_start == MARKDOWN.index("小さな倉庫を活用する。")
    assert processor.process_specific(jobs.job.id).state is JobState.SUCCEEDED
    assert len([node for node in writes.nodes() if isinstance(node, RelationAssertion)]) == 1
    changed = _manifest() | {"candidates": [{
        "source_id": IDEA, "target_id": ASSET, "predicate": "DEPENDS_ON",
        "basis": "brief_hypothesis", "support": {"quote": MARKDOWN.strip().splitlines()[-1]},
        "evidence_ids": [],
    }]}
    before = jobs.job
    try:
        processor.process_specific(jobs.job.id, raw_manifest=changed)
    except CandidateManifestConflictError as error:
        assert error.code == "candidate_manifest_conflict"
    else:
        raise AssertionError("changed manifest replay must be rejected")
    assert jobs.job == before
    assert len([node for node in writes.nodes() if isinstance(node, RelationAssertion)]) == 1


def test_shareable_candidate_is_visible_in_mcp_search_and_fetch():
    brief = _brief(egress_policy=EgressPolicy.SHAREABLE)
    writes, _ = _context(
        brief, idea_policy=EgressPolicy.SHAREABLE, asset_policy=EgressPolicy.SHAREABLE,
    )
    jobs = MemoryJobStore(brief)
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )

    result = processor.process_specific(jobs.job.id, raw_manifest=_manifest())
    assertion = next(node for node in writes.nodes() if isinstance(node, RelationAssertion))
    reads = McpReadSurface(GraphReadService(writes))
    search = reads.call("search", {"query": "storage"}, owner_id=OWNER)
    idea_hit = next(item for item in search["results"] if item["id"] == IDEA)
    fetched = reads.call("fetch", {"id": assertion.id}, owner_id=OWNER)

    assert result.state is JobState.SUCCEEDED
    assert assertion.egress_policy is EgressPolicy.SHAREABLE
    assert "semantic_relation_path" in idea_hit
    assert idea_hit["semantic_relation_path"][0]["relation_assertion_id"] == assertion.id
    assert idea_hit["semantic_relation_path"][0]["target_id"] == ASSET
    assert fetched["path"] == [IDEA, "REUSES", ASSET]


def test_reuses_criterion_asset_without_reclassifying_as_strength_or_decision():
    quote = "この案にも「規模より関係密度を優先する」判断基準を適用する。"
    markdown = f"## エグゼクティブサマリー\n\n{quote}\n"
    brief = _brief(markdown=markdown, egress_policy=EgressPolicy.SHAREABLE)
    writes = InMemoryGraphWriteService(OWNER)
    idea = Idea(
        id=IDEA, owner_id=OWNER, title="倉庫案", status=Status.ACTIVE,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    criterion = Asset(
        id=ASSET, owner_id=OWNER, name="判断基準: 関係密度を優先",
        kind=AssetKind.KNOWLEDGE, home_category="criterion",
        description="規模より関係密度を優先する。", egress_policy=EgressPolicy.SHAREABLE,
    )
    existing_strength = Asset(
        id="asset-strength", owner_id=OWNER, name="既存の強み",
        kind=AssetKind.STRENGTH, home_category="strength",
        description="既存の強みの記録。", egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(idea, idempotency_key="idea-criterion", expected_revision=0)
    writes.put_node(criterion, idempotency_key="criterion-asset", expected_revision=0)
    writes.put_node(existing_strength, idempotency_key="strength-asset", expected_revision=0)
    writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key="criterion-brief")
    jobs = MemoryJobStore(brief)
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )

    result = processor.process_specific(jobs.job.id, raw_manifest=_manifest(quote=quote))
    assertions = [node for node in writes.nodes() if isinstance(node, RelationAssertion)]
    decisions = [node for node in writes.nodes() if isinstance(node, Decision)]
    reads = McpReadSurface(GraphReadService(writes))
    searched = reads.call("search", {"query": "関係密度を優先"}, owner_id=OWNER)
    category_search = reads.call("search", {"query": "criterion"}, owner_id=OWNER)
    criterion_hit = next(item for item in searched["results"] if item["id"] == criterion.id)
    category_hit = next(item for item in category_search["results"] if item["id"] == criterion.id)
    idea_hit = next(item for item in searched["results"] if item["id"] == idea.id)
    relation_path = idea_hit["semantic_relation_path"][0]
    fetched = reads.call("fetch", {"id": criterion.id}, owner_id=OWNER)

    assert result.state is JobState.SUCCEEDED
    assert len(assertions) == 1
    assert assertions[0].predicate.value == "REUSES"
    assert assertions[0].target_id == criterion.id
    assert assertions[0].basis.value == "brief_hypothesis"
    assert assertions[0].status.value == "proposed"
    assert decisions == []
    assert criterion_hit["fields"]["home_category"] == "criterion"
    assert category_hit["fields"]["home_category"] == "criterion"
    assert criterion_hit["fields"]["kind"] == AssetKind.KNOWLEDGE.value
    assert fetched["fields"]["home_category"] == "criterion"
    assert fetched["fields"]["kind"] == AssetKind.KNOWLEDGE.value
    assert relation_path["predicate"] == "REUSES"
    assert relation_path["target_id"] == criterion.id
    assert relation_path["basis"] == "brief_hypothesis"
    assert relation_path["status"] == "proposed"
    assert relation_path["support_quote"] == quote
    assert writes.get_node(existing_strength.id).home_category == "strength"
    assert writes.get_node(existing_strength.id).kind is AssetKind.STRENGTH


def test_private_candidate_endpoint_keeps_relation_local_in_memory_processor():
    brief = _brief(egress_policy=EgressPolicy.SHAREABLE)
    writes, _ = _context(
        brief, idea_policy=EgressPolicy.SHAREABLE, asset_policy=EgressPolicy.LOCAL_ONLY,
    )
    jobs = MemoryJobStore(brief)
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )

    processor.process_specific(jobs.job.id, raw_manifest=_manifest())
    assertion = next(node for node in writes.nodes() if isinstance(node, RelationAssertion))

    assert assertion.egress_policy is EgressPolicy.LOCAL_ONLY


def test_resolve_refs_reads_egress_policy_from_persisted_neo4j_node_fields():
    class Writes:
        owner_id = OWNER

        def get_node(self, node_id):
            return PersistedNodeReference(
                id=node_id, owner_id=OWNER, node_type=NodeType.IDEA, revision=1,
                fields={"egress_policy": EgressPolicy.SHAREABLE.value},
            )

    processor = RelationCandidateJobProcessor(
        jobs=object(), writes=Writes(), brief_store=None, worker_id="inline-worker",
    )

    refs, _evidence = processor._resolve_refs({IDEA})

    assert refs[IDEA].egress_policy is EgressPolicy.SHAREABLE


def test_explicit_empty_manifest_completes_review_without_creating_relations():
    writes, brief = _context()
    jobs = MemoryJobStore(brief)
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )

    result = processor.process_specific(
        jobs.job.id, raw_manifest={"version": 1, "idea_id": IDEA, "candidates": []},
    )

    assert result.state is JobState.SUCCEEDED
    assert result.candidate_ids == () and result.candidate_payload_persisted
    assert not any(isinstance(node, RelationAssertion) for node in writes.nodes())


def test_saved_assertion_is_not_duplicated_when_completion_needs_retry():
    writes, brief = _context()
    jobs = MemoryJobStore(brief)
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )
    complete = jobs.complete
    fail_once = True

    def flaky_complete(job_id, lease_token, *, now=None):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("transient completion issue")
        return complete(job_id, lease_token, now=now)

    jobs.complete = flaky_complete
    first = processor.process_specific(jobs.job.id, raw_manifest=_manifest())
    assert first.state is JobState.PENDING
    assert first.last_error_code == "candidate_processing_failed"
    assert first.candidate_payload_persisted
    assert len([node for node in writes.nodes() if isinstance(node, RelationAssertion)]) == 1

    retried = processor.process_specific(jobs.job.id)
    assert retried.state is JobState.SUCCEEDED and retried.last_error_code is None
    assert len([node for node in writes.nodes() if isinstance(node, RelationAssertion)]) == 1


def test_invalid_candidate_records_retry_state_without_undoing_saved_brief():
    writes, brief = _context()
    jobs = MemoryJobStore(brief)
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )

    result = processor.process_specific(jobs.job.id, raw_manifest=_manifest("quote not in Brief"))

    assert result.state is JobState.PENDING and result.last_error_code == "candidate_manifest_invalid"
    assert writes.get_idea_brief(brief.id) == brief
    assert not any(isinstance(node, RelationAssertion) for node in writes.nodes())
    resumed = processor.process_specific(jobs.job.id)
    assert resumed.state is JobState.PENDING and resumed.last_error_code == "candidate_manifest_invalid"
    assert resumed.attempt_count == result.attempt_count


def test_manifest_limits_are_checked_before_resolving_any_candidate_ids(monkeypatch):
    writes, brief = _context()
    jobs = MemoryJobStore(brief)
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )
    lookups = []
    original_get_node = writes.get_node

    def tracked_get_node(node_id):
        lookups.append(node_id)
        return original_get_node(node_id)

    monkeypatch.setattr(writes, "get_node", tracked_get_node)
    too_many = _manifest() | {"candidates": _manifest()["candidates"] * 65}

    result = processor.process_specific(jobs.job.id, raw_manifest=too_many)

    assert result.state is JobState.PENDING and result.last_error_code == "candidate_manifest_invalid"
    assert lookups == []


def test_neo4j_evidence_reference_is_hydrated_as_typed_source_grounded_evidence():
    writes, brief = _context()
    processor = RelationCandidateJobProcessor(
        jobs=MemoryJobStore(brief), writes=writes, brief_store=writes, worker_id="inline-worker",
    )
    evidence = Evidence(
        owner_id=OWNER, id="evidence-test", claim_id="claim-test",
        source_revision_id="revision-test", content_chunk_id="chunk-test",
        char_start=0, char_end=4, locator="chars:0-4", content_hash="a" * 64,
    )
    reference = PersistedNodeReference(
        id=evidence.id, owner_id=OWNER, node_type=NodeType.EVIDENCE,
        revision=0, fields=asdict(evidence),
    )

    assert processor._hydrate_evidence(reference) == evidence


def test_external_evidence_candidate_is_rechecked_and_applied_with_source_grounding():
    writes = InMemoryGraphWriteService(OWNER)
    idea = Idea(id=IDEA, owner_id=OWNER, title="倉庫案", status=Status.ACTIVE)
    asset = Asset(id=ASSET, owner_id=OWNER, name="倉庫", description="保管場所")
    writes.put_node(idea, idempotency_key="idea", expected_revision=0)
    writes.put_node(asset, idempotency_key="asset", expected_revision=0)
    source = Source(
        owner_id=OWNER, id="source-test", title="倉庫調査", kind=MaterialKind.WEB,
        locator="https://example.test/warehouse", current_revision_id="revision-test", revision=1,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    revision = SourceRevision(
        owner_id=OWNER, id="revision-test", source_id=source.id,
        content="A warehouse is required.", locator=source.locator, revision=1,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    source_receipt = writes.capture_source(source, revision, idempotency_key="source")
    claim = Claim(
        owner_id=OWNER, id="claim-test", text="A warehouse is required",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(claim, idempotency_key="claim", operation="append_claim")
    evidence_receipt = writes.capture_evidence(
        claim.id, source_receipt.content_chunk_ids[0], egress_policy=EgressPolicy.SHAREABLE,
        idempotency_key="evidence",
    )
    evidence = writes.get_node(evidence_receipt.target_id)
    assert isinstance(evidence, Evidence)
    sections = tuple(IdeaBriefSection(
        index=index, evidence_ids=(evidence.id,) if index == 0 else (),
    ) for index in range(8))
    brief = replace(_brief(), sections=sections)
    writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key="brief")
    jobs = MemoryJobStore(brief)
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )
    manifest = _manifest() | {"candidates": [{
        "source_id": IDEA, "target_id": ASSET, "predicate": "REQUIRES_CAPABILITY",
        "basis": "external_evidence", "support": {"section_index": 0},
        "evidence_ids": [evidence.id],
    }]}

    result = processor.process_specific(jobs.job.id, raw_manifest=manifest)

    assertions = [node for node in writes.nodes() if isinstance(node, RelationAssertion)]
    assert result.state is JobState.SUCCEEDED
    assert len(assertions) == 1 and assertions[0].evidence_ids == (evidence.id,)
    assert assertions[0].basis.value == "external_evidence"
    assert assertions[0].based_on_brief_revision == brief.revision
    assert assertions[0].based_on_brief_section_index == 0
    assert assertions[0].based_on_brief_quote_start is None
    assert assertions[0].based_on_brief_quote_end is None


def test_stale_lineage_evidence_is_rejected_before_assertion_write(monkeypatch):
    writes = InMemoryGraphWriteService(OWNER)
    idea = Idea(id=IDEA, owner_id=OWNER, title="倉庫案", status=Status.ACTIVE)
    asset = Asset(id=ASSET, owner_id=OWNER, name="倉庫", description="保管場所")
    writes.put_node(idea, idempotency_key="idea", expected_revision=0)
    writes.put_node(asset, idempotency_key="asset", expected_revision=0)
    evidence = Evidence(
        owner_id=OWNER, id="evidence-stale", claim_id="claim-test",
        source_revision_id="old-revision", content_chunk_id="old-chunk",
        char_start=0, char_end=4, locator="chars:0-4", content_hash="a" * 64,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    get_node = writes.get_node
    monkeypatch.setattr(
        writes, "get_node",
        lambda identifier: evidence if identifier == evidence.id else get_node(identifier),
    )
    brief = _brief()
    jobs = MemoryJobStore(brief)
    writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key="brief")
    monkeypatch.setattr(
        "nebula.founder_graph_candidate_job_processor.evidence_lineage_is_current",
        lambda *_args: False,
    )
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )
    manifest = _manifest() | {"candidates": [{
        "source_id": IDEA, "target_id": ASSET, "predicate": "REQUIRES_CAPABILITY",
        "basis": "external_evidence", "support": {"section_index": 0},
        "evidence_ids": [evidence.id],
    }]}

    result = processor.process_specific(jobs.job.id, raw_manifest=manifest)

    assert result.state is JobState.PENDING
    assert result.last_error_code == "candidate_manifest_invalid"
    assert not any(isinstance(node, RelationAssertion) for node in writes.nodes())


def test_old_job_is_superseded_before_applying_against_new_brief():
    writes, brief = _context()
    jobs = MemoryJobStore(brief)
    newer = brief.revise(report_markdown=MARKDOWN + "\n次の段落。")
    writes.save_idea_brief(newer, expected_latest_revision=brief.revision, idempotency_key="brief-v2")
    processor = RelationCandidateJobProcessor(
        jobs=jobs, writes=writes, brief_store=writes, worker_id="inline-worker",
    )

    result = processor.process_specific(jobs.job.id, raw_manifest=_manifest())

    assert result.state is JobState.SUPERSEDED and result.last_error_code == "stale_version"
    assert not any(isinstance(node, RelationAssertion) for node in writes.nodes())
    replay = processor.process_specific(jobs.job.id, raw_manifest=_manifest())
    assert replay == result
