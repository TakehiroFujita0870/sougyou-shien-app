from kadode_api.hybrid_search import (
    ChunkCandidate,
    DeterministicFakeEmbeddingAdapter,
    EmbeddingUnavailable,
    hybrid_search,
)


OWNER_A = "00000000-0000-0000-0000-000000000001"
OWNER_B = "00000000-0000-0000-0000-000000000002"


def test_rrf_keeps_exact_keyword_and_semantic_matches_at_the_top() -> None:
    adapter = DeterministicFakeEmbeddingAdapter()
    chunks = (
        ChunkCandidate("exact", OWNER_A, "JP2023-123456A uses recycled resin"),
        ChunkCandidate("semantic", OWNER_A, "Circular material reduces virgin plastic consumption"),
        ChunkCandidate("noise", OWNER_A, "Restaurant menu planning"),
    )

    results = hybrid_search("recycled plastic JP2023-123456A", OWNER_A, chunks, adapter)

    assert [result.chunk_id for result in results] == ["exact", "semantic"]
    assert results[0].keyword_rank == 1
    assert results[1].semantic_rank == 2


def test_owner_and_deleted_or_non_current_chunks_never_reach_either_ranker() -> None:
    adapter = DeterministicFakeEmbeddingAdapter()
    chunks = (
        ChunkCandidate("own", OWNER_A, "recycled plastic market"),
        ChunkCandidate("other-owner", OWNER_B, "recycled plastic market"),
        ChunkCandidate("deleted", OWNER_A, "recycled plastic market", document_state="deleted"),
        ChunkCandidate("old-version", OWNER_A, "recycled plastic market", is_current_version=False),
    )

    results = hybrid_search("recycled plastic", OWNER_A, chunks, adapter)

    assert [result.chunk_id for result in results] == ["own"]


def test_fake_adapter_failure_returns_a_recoverable_search_state() -> None:
    adapter = DeterministicFakeEmbeddingAdapter(error=EmbeddingUnavailable())
    results = hybrid_search("recycled plastic", OWNER_A, (ChunkCandidate("own", OWNER_A, "recycled plastic"),), adapter)

    assert results == ()
