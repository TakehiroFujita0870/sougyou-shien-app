import pytest

from dots.space_knowledge import ExtractedPageInput, ReferenceInput, SpaceKnowledgeRepository


def source() -> bytes:
    return b"shared source bytes"


def test_same_owner_hash_deduplicates_original_and_derivatives() -> None:
    repo = SpaceKnowledgeRepository("owner-a")
    first = repo.store_original("brief.txt", source(), (ExtractedPageInput(1, "本文", "p1"),))
    second = repo.store_original("renamed.txt", source(), (ExtractedPageInput(1, "本文", "p1"),))
    assert second.original_id == first.original_id
    assert second.created is False
    assert repo.original_count() == 1
    assert repo.derived_count(first.original_id) == 1


def test_references_cover_all_contexts_without_copying_original() -> None:
    repo = SpaceKnowledgeRepository("owner-a")
    stored = repo.store_original("brief.txt", source(), (ExtractedPageInput(2, "根拠本文", "page=2"),))
    for kind in ("conversation", "project", "research", "idea"):
        reference = repo.add_reference(stored.original_id, ReferenceInput(kind, f"{kind}-1", "page=2"))
        assert reference.original_id == stored.original_id
    assert repo.reference_count(stored.original_id) == 4
    # Same-space references are active by default; no per-project grant exists in this contract.
    assert repo.search("根拠")


def test_owner_isolation_and_request_owner_cannot_cross_boundary() -> None:
    repo_a = SpaceKnowledgeRepository("owner-a")
    repo_b = SpaceKnowledgeRepository("owner-b")
    stored = repo_a.store_original("brief.txt", source(), ())
    assert repo_b.search("shared") == ()
    assert repo_b.add_reference(stored.original_id, ReferenceInput("project", "project-b", "p1")) is None
    assert repo_a.search("owner-b") == ()


def test_delete_propagates_to_derivatives_references_and_search() -> None:
    repo = SpaceKnowledgeRepository("owner-a")
    stored = repo.store_original("brief.txt", source(), (ExtractedPageInput(1, "削除される本文", "page=1"),))
    repo.add_reference(stored.original_id, ReferenceInput("project", "project-a", "page=1"))
    assert repo.delete_original(stored.original_id) is True
    assert repo.search("削除される") == ()
    assert repo.reference_status(stored.original_id, "project-a") == "unavailable"
    assert repo.derived_count(stored.original_id) == 0


def test_duplicate_hash_is_owner_scoped_and_embedding_is_local_fake() -> None:
    repo_a = SpaceKnowledgeRepository("owner-a")
    repo_b = SpaceKnowledgeRepository("owner-b")
    a = repo_a.store_original("a.txt", source(), (ExtractedPageInput(1, "same", "p1"),))
    b = repo_b.store_original("b.txt", source(), (ExtractedPageInput(1, "same", "p1"),))
    assert a.original_id != b.original_id
    repo_a.add_reference(a.original_id, ReferenceInput("project", "project-a", "p1"))
    result = repo_a.search("same")[0]
    assert result.embedding == ("same",)


def test_owner_principal_cannot_be_changed_by_operation_arguments() -> None:
    repo = SpaceKnowledgeRepository("owner-a")
    assert not hasattr(repo, "set_owner")
    with pytest.raises(TypeError):
        repo.search("owner-b", "query")
