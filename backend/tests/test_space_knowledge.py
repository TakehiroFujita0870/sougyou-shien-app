from kadode_api.space_knowledge import ExtractedPageInput, ReferenceInput, SpaceKnowledgeRepository


def source() -> bytes:
    return b"shared source bytes"


def test_same_owner_hash_deduplicates_original_and_derivatives() -> None:
    repo = SpaceKnowledgeRepository()
    first = repo.store_original("owner-a", "brief.txt", source(), (ExtractedPageInput(1, "本文", "p1"),))
    second = repo.store_original("owner-a", "renamed.txt", source(), (ExtractedPageInput(1, "本文", "p1"),))
    assert second.original_id == first.original_id
    assert second.created is False
    assert repo.original_count("owner-a") == 1
    assert repo.derived_count("owner-a", first.original_id) == 1


def test_references_cover_all_contexts_without_copying_original() -> None:
    repo = SpaceKnowledgeRepository()
    stored = repo.store_original("owner-a", "brief.txt", source(), (ExtractedPageInput(2, "根拠本文", "page=2"),))
    for kind in ("conversation", "project", "research", "idea"):
        reference = repo.add_reference("owner-a", stored.original_id, ReferenceInput(kind, f"{kind}-1", "page=2"))
        assert reference.original_id == stored.original_id
    assert repo.reference_count("owner-a", stored.original_id) == 4
    # Same-space references are active by default; no per-project grant exists in this contract.
    assert repo.search("owner-a", "根拠")


def test_owner_isolation_and_request_owner_cannot_cross_boundary() -> None:
    repo = SpaceKnowledgeRepository()
    stored = repo.store_original("owner-a", "brief.txt", source(), ())
    assert repo.search("owner-b", "shared") == ()
    assert repo.add_reference("owner-b", stored.original_id, ReferenceInput("project", "project-b", "p1")) is None


def test_delete_propagates_to_derivatives_references_and_search() -> None:
    repo = SpaceKnowledgeRepository()
    stored = repo.store_original("owner-a", "brief.txt", source(), (ExtractedPageInput(1, "削除される本文", "page=1"),))
    repo.add_reference("owner-a", stored.original_id, ReferenceInput("project", "project-a", "page=1"))
    assert repo.delete_original("owner-a", stored.original_id) is True
    assert repo.search("owner-a", "削除される") == ()
    assert repo.reference_status("owner-a", stored.original_id, "project-a") == "unavailable"
    assert repo.derived_count("owner-a", stored.original_id) == 0


def test_duplicate_hash_is_owner_scoped_and_embedding_is_local_fake() -> None:
    repo = SpaceKnowledgeRepository()
    a = repo.store_original("owner-a", "a.txt", source(), (ExtractedPageInput(1, "same", "p1"),))
    b = repo.store_original("owner-b", "b.txt", source(), (ExtractedPageInput(1, "same", "p1"),))
    assert a.original_id != b.original_id
    repo.add_reference("owner-a", a.original_id, ReferenceInput("project", "project-a", "p1"))
    result = repo.search("owner-a", "same")[0]
    assert result.embedding == ("same",)
