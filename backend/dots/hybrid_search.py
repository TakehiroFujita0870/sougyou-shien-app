"""Local hybrid-search contract; no network clients or embedding credentials."""

from dataclasses import dataclass
from math import sqrt
import re


_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CONCEPTS = {
    "recycled": "circular_material",
    "recycling": "circular_material",
    "circular": "circular_material",
    "resin": "circular_material",
    "plastic": "circular_material",
    "virgin": "circular_material",
    "material": "circular_material",
}


class EmbeddingUnavailable(Exception):
    """The configured embedding adapter cannot produce a vector."""


@dataclass(frozen=True)
class ChunkCandidate:
    chunk_id: str
    owner_id: str
    content: str
    document_state: str = "ready"
    is_current_version: bool = True


@dataclass(frozen=True)
class HybridSearchResult:
    chunk_id: str
    score: float
    keyword_rank: int | None
    semantic_rank: int | None


class DeterministicFakeEmbeddingAdapter:
    """A deterministic local adapter used until release-gate #31 enables a provider."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def embed(self, text: str) -> dict[str, float]:
        if self.error:
            raise self.error
        vector: dict[str, float] = {}
        for token in _tokens(text):
            concept = _CONCEPTS.get(token, token)
            vector[concept] = vector.get(concept, 0.0) + 1.0
        return vector


def hybrid_search(
    query: str,
    authenticated_owner_id: str,
    chunks: tuple[ChunkCandidate, ...],
    adapter: DeterministicFakeEmbeddingAdapter,
    *,
    limit: int = 20,
    rrf_k: int = 60,
) -> tuple[HybridSearchResult, ...]:
    """Fuse keyword and semantic ranks after applying the owner/deletion boundary."""
    visible = tuple(
        chunk for chunk in chunks
        if chunk.owner_id == authenticated_owner_id
        and chunk.document_state == "ready"
        and chunk.is_current_version
    )
    try:
        query_vector = adapter.embed(query)
        vectors = {chunk.chunk_id: adapter.embed(chunk.content) for chunk in visible}
    except EmbeddingUnavailable:
        return ()

    query_tokens = set(_tokens(query))
    keyword = sorted(
        ((chunk.chunk_id, len(query_tokens & set(_tokens(chunk.content)))) for chunk in visible),
        key=lambda item: (-item[1], item[0]),
    )
    semantic = sorted(
        ((chunk.chunk_id, _cosine(query_vector, vectors[chunk.chunk_id])) for chunk in visible),
        key=lambda item: (-item[1], item[0]),
    )
    keyword_ranks = {chunk_id: rank for rank, (chunk_id, score) in enumerate(keyword, 1) if score > 0}
    semantic_ranks = {chunk_id: rank for rank, (chunk_id, score) in enumerate(semantic, 1) if score > 0}
    results = tuple(
        HybridSearchResult(
            chunk_id,
            sum(1 / (rrf_k + rank) for rank in (keyword_ranks.get(chunk_id), semantic_ranks.get(chunk_id)) if rank),
            keyword_ranks.get(chunk_id),
            semantic_ranks.get(chunk_id),
        )
        for chunk_id in set(keyword_ranks) | set(semantic_ranks)
    )
    return tuple(sorted(results, key=lambda result: (-result.score, result.chunk_id))[:limit])


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(value.lower()))


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    denominator = sqrt(sum(value * value for value in left.values())) * sqrt(sum(value * value for value in right.values()))
    return 0.0 if not denominator else sum(value * right.get(key, 0.0) for key, value in left.items()) / denominator
