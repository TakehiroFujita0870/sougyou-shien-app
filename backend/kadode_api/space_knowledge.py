"""Local-only shared-space original, derivatives, and reference contract."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

ReferenceKind = Literal["conversation", "project", "research", "idea"]


@dataclass(frozen=True)
class ExtractedPageInput:
    page: int
    content: str
    locator: str


@dataclass(frozen=True)
class ReferenceInput:
    kind: ReferenceKind
    source_id: str
    locator: str


@dataclass(frozen=True)
class StoreResult:
    original_id: UUID
    content_hash: str
    created: bool


@dataclass(frozen=True)
class SearchResult:
    original_id: UUID
    reference_id: UUID
    kind: ReferenceKind
    source_id: str
    locator: str
    content: str
    embedding: tuple[str, ...]


@dataclass(frozen=True)
class _Original:
    id: UUID
    owner_id: str
    filename: str
    content_hash: str
    deleted: bool = False


@dataclass(frozen=True)
class _Derivative:
    original_id: UUID
    page: int
    content: str
    locator: str
    embedding: tuple[str, ...]


@dataclass(frozen=True)
class _Reference:
    id: UUID
    owner_id: str
    original_id: UUID
    kind: ReferenceKind
    source_id: str
    locator: str
    deleted: bool = False


class SpaceKnowledgeRepository:
    """Fake repository with no filesystem, database, network, or provider calls."""

    def __init__(self) -> None:
        self._originals: dict[UUID, _Original] = {}
        self._by_hash: dict[tuple[str, str], UUID] = {}
        self._derivatives: dict[UUID, tuple[_Derivative, ...]] = {}
        self._references: dict[UUID, _Reference] = {}

    def store_original(self, owner_id: str, filename: str, content: bytes, pages: tuple[ExtractedPageInput, ...]) -> StoreResult:
        content_hash = sha256(content).hexdigest()
        existing_id = self._by_hash.get((owner_id, content_hash))
        if existing_id is not None:
            return StoreResult(existing_id, content_hash, False)
        original_id = uuid4()
        self._by_hash[(owner_id, content_hash)] = original_id
        self._originals[original_id] = _Original(original_id, owner_id, filename, content_hash)
        self._derivatives[original_id] = tuple(_Derivative(original_id, page.page, page.content, page.locator, _fake_embedding(page.content)) for page in pages)
        return StoreResult(original_id, content_hash, True)

    def add_reference(self, owner_id: str, original_id: UUID, command: ReferenceInput) -> _Reference | None:
        original = self._originals.get(original_id)
        if original is None or original.owner_id != owner_id or original.deleted:
            return None
        reference = _Reference(uuid4(), owner_id, original_id, command.kind, command.source_id, command.locator)
        self._references[reference.id] = reference
        return reference

    def delete_original(self, owner_id: str, original_id: UUID) -> bool:
        original = self._originals.get(original_id)
        if original is None or original.owner_id != owner_id:
            return False
        self._originals[original_id] = _Original(original.id, original.owner_id, original.filename, original.content_hash, True)
        self._derivatives.pop(original_id, None)
        for reference_id, reference in tuple(self._references.items()):
            if reference.original_id == original_id:
                self._references[reference_id] = _Reference(reference.id, reference.owner_id, reference.original_id, reference.kind, reference.source_id, reference.locator, True)
        return True

    def search(self, owner_id: str, query: str) -> tuple[SearchResult, ...]:
        results = []
        for reference in self._references.values():
            original = self._originals.get(reference.original_id)
            if reference.owner_id != owner_id or reference.deleted or original is None or original.deleted:
                continue
            for derivative in self._derivatives.get(reference.original_id, ()):
                if query.casefold() in derivative.content.casefold():
                    results.append(SearchResult(original.id, reference.id, reference.kind, reference.source_id, derivative.locator, derivative.content, derivative.embedding))
        return tuple(results)

    def reference_status(self, owner_id: str, original_id: UUID, source_id: str) -> str:
        original = self._originals.get(original_id)
        available = original is not None and not original.deleted and any(reference.owner_id == owner_id and reference.original_id == original_id and reference.source_id == source_id and not reference.deleted for reference in self._references.values())
        return "available" if available else "unavailable"

    def original_count(self, owner_id: str) -> int:
        return sum(1 for original in self._originals.values() if original.owner_id == owner_id and not original.deleted)

    def derived_count(self, owner_id: str, original_id: UUID) -> int:
        original = self._originals.get(original_id)
        return len(self._derivatives.get(original_id, ())) if original and original.owner_id == owner_id and not original.deleted else 0

    def reference_count(self, owner_id: str, original_id: UUID) -> int:
        return sum(1 for reference in self._references.values() if reference.owner_id == owner_id and reference.original_id == original_id and not reference.deleted)


def _fake_embedding(content: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(content.casefold().split()))
