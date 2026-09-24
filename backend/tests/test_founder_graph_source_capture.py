from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dots.founder_graph import (
    ContentChunk,
    EgressPolicy,
    Idea,
    Source,
    SourceRevision,
    build_content_chunks,
    split_source_content,
    _paragraph_boundaries,
)
from dots.founder_graph_write import (
    InMemoryGraphWriteService,
    capture_idea_payload_fingerprint,
    payload_fingerprint,
)


UTC = timezone.utc
CAPTURED_AT = datetime(2026, 9, 24, 0, 0, tzinfo=UTC)


def _capture_fixture(content: str, *, egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY) -> tuple[Idea, Source, SourceRevision]:
    idea = Idea(owner_id="owner-1", id="idea-capture", title="Captured idea")
    source = Source(
        owner_id="owner-1",
        id="source-capture",
        title="Captured conversation",
        kind="conversation",
        current_revision_id="source-revision-capture",
        revision=1,
        egress_policy=egress_policy,
        created_at=CAPTURED_AT,
    )
    revision = SourceRevision(
        owner_id="owner-1",
        id="source-revision-capture",
        source_id=source.id,
        content=content,
        retrieved_at=CAPTURED_AT,
        egress_policy=egress_policy,
    )
    return idea, source, revision


def test_splitter_keeps_contiguous_unicode_ranges_and_reconstructs_source() -> None:
    content = "😀" * 2_390 + "\n\n" + "文章" * 1_300

    ranges = split_source_content(content)

    assert ranges
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(content)
    assert all(end - start <= 4_000 for start, end, _text in ranges)
    assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:]))
    assert "".join(text for _start, _end, text in ranges) == content
    assert ranges[0][1] == 2_392


def test_splitter_prefers_sentence_then_whitespace_and_hard_splits_without_boundaries() -> None:
    sentence_content = "a" * 2_380 + ". " + "b" * 2_600
    sentence_ranges = split_source_content(sentence_content)
    assert sentence_ranges[0][1] == 2_382

    paragraph_after_target = "a" * 2_380 + ". " + "b" * 100 + "\n\n" + "c" * 2_600
    fallback_ranges = split_source_content(paragraph_after_target)
    assert fallback_ranges[0][1] == 2_382

    hard_ranges = split_source_content("x" * 5_001)
    assert [(start, end) for start, end, _text in hard_ranges] == [(0, 4_000), (4_000, 5_001)]


def test_paragraph_boundaries_count_crlf_sequences_not_characters() -> None:
    content = "first\r\nsecond"
    blank_line_content = "first\r\n\r\nsecond"

    assert _paragraph_boundaries(content, 0, len(content)) == ()
    assert _paragraph_boundaries(blank_line_content, 0, len(blank_line_content)) == (len("first\r\n\r\n"),)

    prefix = "a" * 2_380 + ". " + "b" * 8
    single_crlf_ranges = split_source_content(prefix + "\r\n" + "c" * 2_600)
    blank_line_crlf_ranges = split_source_content(prefix + "\r\n\r\n" + "c" * 2_600)

    assert single_crlf_ranges[0][1] == 2_382
    assert blank_line_crlf_ranges[0][1] == len(prefix) + 4


def test_capture_idea_fingerprint_keeps_pre_chunk_durable_contract() -> None:
    idea, source, revision = _capture_fixture("fingerprint source text")
    chunks = build_content_chunks(revision)

    assert capture_idea_payload_fingerprint(idea, source, revision, chunks, "owner-1") == payload_fingerprint(
        "capture_idea", idea, source, revision, "owner-1"
    )


def test_content_chunks_are_deterministic_local_only_and_empty_source_has_none() -> None:
    idea, source, revision = _capture_fixture("first paragraph\n\nsecond paragraph", egress_policy=EgressPolicy.SHAREABLE)

    first = build_content_chunks(revision)
    second = build_content_chunks(revision)

    assert first == second
    assert all(chunk.egress_policy is EgressPolicy.LOCAL_ONLY for chunk in first)
    assert all(chunk.source_revision_id == revision.id for chunk in first)
    assert all(chunk.text == revision.content[chunk.char_start : chunk.char_end] for chunk in first)
    assert all(chunk.id.startswith("content-chunk_") for chunk in first)
    assert build_content_chunks(_capture_fixture("")[2]) == ()
    assert idea.source_text == ""
    assert source.current_revision_id == revision.id


def test_capture_receipt_contains_only_opaque_source_and_chunk_ids_and_replay_reuses_them() -> None:
    idea, source, revision = _capture_fixture("The saved local conversation.")
    service = InMemoryGraphWriteService("owner-1")

    receipt = service.capture_idea(idea, source, revision, idempotency_key="capture-1")
    replay = service.capture_idea(idea, source, revision, idempotency_key="capture-1")
    chunks = tuple(node for node in service.nodes() if isinstance(node, ContentChunk))

    assert receipt.target_id == idea.id
    assert receipt.source_revision_id == revision.id
    assert receipt.content_chunk_ids == tuple(chunk.id for chunk in chunks)
    assert replay.replayed is True
    assert replay.target_id == receipt.target_id
    assert replay.source_revision_id == receipt.source_revision_id
    assert replay.content_chunk_ids == receipt.content_chunk_ids
    assert "The saved local conversation." not in repr(receipt)
    assert "locator" not in repr(receipt)
    assert len(chunks) == 1
    assert len(service.nodes()) == 4


def test_capture_empty_source_returns_revision_id_without_chunks() -> None:
    idea, source, revision = _capture_fixture("")
    service = InMemoryGraphWriteService("owner-1")

    receipt = service.capture_idea(idea, source, revision, idempotency_key="capture-empty")

    assert receipt.target_id == idea.id
    assert receipt.source_revision_id == revision.id
    assert receipt.content_chunk_ids == ()
    assert not tuple(node for node in service.nodes() if isinstance(node, ContentChunk))
    assert len(service.nodes()) == 3


def test_capture_rolls_back_chunks_nodes_audit_and_idempotency_on_audit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    idea, source, revision = _capture_fixture("Rollback this source.")
    service = InMemoryGraphWriteService("owner-1")

    def fail_after_mutation(*_args: object, **_kwargs: object) -> None:
        service._audit.append("partial-audit")  # type: ignore[arg-type]
        raise RuntimeError("audit sink unavailable")

    monkeypatch.setattr(service, "_append_audit", fail_after_mutation)
    with pytest.raises(RuntimeError, match="audit sink"):
        service.capture_idea(idea, source, revision, idempotency_key="capture-rollback")

    assert service.nodes() == ()
    assert service.audit_events() == ()
    assert service._idempotency == {}
