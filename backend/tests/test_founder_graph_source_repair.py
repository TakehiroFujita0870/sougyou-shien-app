from __future__ import annotations

from dataclasses import replace

import pytest

from dots.founder_graph import ContentChunk, Idea, Source, SourceRevision, build_content_chunks
from dots.founder_graph_write import GraphWriteError, InMemoryGraphWriteService


def _legacy_capture(content: str = "A saved conversation.") -> tuple[InMemoryGraphWriteService, Source, SourceRevision]:
    service = InMemoryGraphWriteService("owner-1")
    source = Source(
        owner_id="owner-1",
        id="source-1",
        title="Conversation",
        kind="conversation",
        current_revision_id="revision-1",
    )
    revision = SourceRevision(
        owner_id="owner-1", id="revision-1", source_id=source.id, content=content,
    )
    service.capture_idea(
        Idea(owner_id="owner-1", id="idea-1", title="Saved idea"),
        source,
        revision,
        idempotency_key="capture-1",
    )
    return service, source, revision


def test_source_chain_repair_preview_is_read_only_and_apply_is_idempotent() -> None:
    service, source, revision = _legacy_capture()
    chunks = build_content_chunks(revision)
    before_edges = service.structural_edges()
    before_audit = service.audit_events()
    before_nodes = service.nodes()
    before_idempotency = dict(service._idempotency)

    preview = service.preview_source_chain_repair()

    assert preview.owner_id == "owner-1"
    assert preview.source_count == 1
    assert preview.revision_count == 1
    assert preview.chunk_count == len(chunks) == 1
    assert preview.edges_to_add == (
        (source.id, "HAS_SOURCE_REVISION", revision.id),
        (source.id, "CURRENT_SOURCE_REVISION", revision.id),
        (revision.id, "HAS_CHUNK", chunks[0].id),
    )
    assert service.structural_edges() == before_edges
    assert service.audit_events() == before_audit
    assert service.nodes() == before_nodes
    assert service._idempotency == before_idempotency

    applied = service.apply_source_chain_repair()
    assert applied.edges_added == preview.edges_to_add
    assert service.structural_edges() == preview.edges_to_add
    audit_after_apply = service.audit_events()
    assert len(audit_after_apply) == len(before_audit) + 1
    assert audit_after_apply[-1].operation == "repair_source_chain_edges"

    repeated = service.apply_source_chain_repair()
    assert repeated.edges_added == ()
    assert service.structural_edges() == preview.edges_to_add
    assert service.audit_events() == audit_after_apply


def test_source_chain_repair_preserves_existing_correct_edges_and_adds_only_missing() -> None:
    service, source, revision = _legacy_capture()
    chunks = build_content_chunks(revision)
    correct = (source.id, "HAS_SOURCE_REVISION", revision.id)
    service._structural_edges.append(correct)

    applied = service.apply_source_chain_repair()

    assert applied.edges_added == (
        (source.id, "CURRENT_SOURCE_REVISION", revision.id),
        (revision.id, "HAS_CHUNK", chunks[0].id),
    )
    assert service.structural_edges().count(correct) == 1


@pytest.mark.parametrize(
    "problem",
    [
        "foreign_chunk", "foreign_revision", "wrong_chunk_range", "wrong_chunk_hash",
        "wrong_content_hash", "wrong_current_pointer", "unexpected_ordinal",
        "duplicate_edge", "reversed_edge", "malformed_edge",
    ],
)
def test_source_chain_repair_fails_closed_before_any_change(problem: str) -> None:
    service, source, revision = _legacy_capture()
    chunk = build_content_chunks(revision)[0]
    if problem == "foreign_chunk":
        service._nodes[chunk.id] = replace(chunk, owner_id="owner-2")
    elif problem == "foreign_revision":
        service._nodes[revision.id] = replace(revision, owner_id="owner-2")
    elif problem == "wrong_chunk_range":
        object.__setattr__(chunk, "char_end", chunk.char_end + 1)
        service._nodes[chunk.id] = chunk
    elif problem == "wrong_chunk_hash":
        object.__setattr__(chunk, "text_hash", "0" * 64)
        service._nodes[chunk.id] = chunk
    elif problem == "wrong_content_hash":
        object.__setattr__(revision, "content_hash", "0" * 64)
    elif problem == "wrong_current_pointer":
        service._nodes[source.id] = replace(source, current_revision_id="missing-revision")
    elif problem == "unexpected_ordinal":
        extra = ContentChunk(
            owner_id="owner-1", id="chunk-extra", source_revision_id=revision.id,
            ordinal=1, char_start=0, char_end=len(revision.content), text=revision.content,
        )
        service._nodes[extra.id] = extra
    elif problem == "duplicate_edge":
        service._structural_edges.extend(((source.id, "HAS_SOURCE_REVISION", revision.id),) * 2)
    elif problem == "malformed_edge":
        service._structural_edges.append((source.id, "HAS_SOURCE_REVISION"))
    else:
        service._structural_edges.append((revision.id, "HAS_SOURCE_REVISION", source.id))

    before_edges = service.structural_edges()
    before_audit = service.audit_events()
    with pytest.raises(GraphWriteError):
        service.apply_source_chain_repair()

    assert service.structural_edges() == before_edges
    assert service.audit_events() == before_audit


def test_source_chain_repair_accepts_an_empty_revision_without_chunks() -> None:
    service, _source, _revision = _legacy_capture("")

    preview = service.preview_source_chain_repair()

    assert preview.chunk_count == 0
    assert len(preview.edges_to_add) == 2


def test_source_chain_repair_rolls_back_edges_when_audit_write_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _source, _revision = _legacy_capture()
    before_edges = service.structural_edges()
    before_audit = service.audit_events()

    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(service, "_append_audit", fail_audit)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        service.apply_source_chain_repair()

    assert service.structural_edges() == before_edges
    assert service.audit_events() == before_audit


def test_source_chain_repair_builds_history_for_multiple_revisions() -> None:
    service, source, first = _legacy_capture()
    second = SourceRevision(
        owner_id="owner-1", id="revision-2", source_id=source.id,
        revision=2, supersedes_id=first.id, content="Corrected conversation.",
    )
    service._nodes[source.id] = replace(source, revision=2, current_revision_id=second.id)
    service._nodes[second.id] = second
    second_chunk = build_content_chunks(second)[0]
    service._nodes[second_chunk.id] = second_chunk

    repaired = service.apply_source_chain_repair()

    assert (source.id, "HAS_SOURCE_REVISION", first.id) in repaired.edges_added
    assert (source.id, "HAS_SOURCE_REVISION", second.id) in repaired.edges_added
    assert (source.id, "CURRENT_SOURCE_REVISION", second.id) in repaired.edges_added
    assert (second.id, "HAS_CHUNK", second_chunk.id) in repaired.edges_added
    assert (source.id, "CURRENT_SOURCE_REVISION", first.id) not in repaired.edges_added
