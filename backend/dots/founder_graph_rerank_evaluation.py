"""Offline, deterministic evaluation contract for Founder Graph reranking.

The production model is deliberately not called here.  This module fixes the
synthetic questions, candidate identifiers, scoring rules, and provenance
record so an approved Luna adapter can later be compared without sending data
or quietly changing the default retrieval order.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from math import ceil, isfinite
from time import perf_counter

from .model_catalog import DEFAULT_MODEL_CATALOG, LUNA_LOGICAL_KEY, ModelCatalog


class RerankEvaluationError(ValueError):
    """The synthetic rerank evaluation input or result is unsafe to score."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RerankEvaluationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _ids(values: Sequence[object], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise RerankEvaluationError(f"{field_name} must be a sequence of identifiers")
    normalized = tuple(_text(value, field_name) for value in values)
    if not normalized:
        raise RerankEvaluationError(f"{field_name} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise RerankEvaluationError(f"{field_name} must not contain duplicate identifiers")
    return normalized


@dataclass(frozen=True, slots=True)
class RerankEvaluationCase:
    """One PII-free question with a known relevant candidate identifier."""

    query: str
    candidate_ids: tuple[str, ...]
    expected_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", _text(self.query, "query"))
        object.__setattr__(self, "candidate_ids", _ids(self.candidate_ids, "candidate_ids"))
        object.__setattr__(self, "expected_id", _text(self.expected_id, "expected_id"))
        if self.expected_id not in self.candidate_ids:
            raise RerankEvaluationError("expected_id must be one of candidate_ids")


@dataclass(frozen=True, slots=True)
class RerankEvaluation:
    """A compact, comparable result for the fixed twenty-question fixture."""

    model_snapshot: str
    case_count: int
    top_5_hits: int
    top_5_recall: float
    invalid_id_count: int
    duplicate_id_count: int
    p95_latency_ms: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_snapshot", _text(self.model_snapshot, "model_snapshot"))
        if self.case_count < 1 or self.top_5_hits < 0 or self.top_5_hits > self.case_count:
            raise RerankEvaluationError("case and hit counts are invalid")
        if self.top_5_recall != self.top_5_hits / self.case_count:
            raise RerankEvaluationError("top_5_recall must match the recorded hit count")
        if self.invalid_id_count < 0 or self.duplicate_id_count < 0:
            raise RerankEvaluationError("invalid and duplicate counts must not be negative")
        if not isfinite(self.p95_latency_ms) or self.p95_latency_ms < 0:
            raise RerankEvaluationError("p95_latency_ms must be a finite non-negative number")

    @property
    def passes_target(self) -> bool:
        """Return the P3-SP-03 threshold without treating invalid output as safe."""

        return (
            self.case_count == 20
            and self.top_5_hits >= 16
            and self.invalid_id_count == 0
            and self.p95_latency_ms <= 30_000
        )


Reranker = Callable[[str, tuple[str, ...]], Sequence[object]]
Clock = Callable[[], float]


def evaluate_reranker(
    cases: Iterable[RerankEvaluationCase],
    reranker: Reranker,
    *,
    catalog: ModelCatalog = DEFAULT_MODEL_CATALOG,
    logical_key: str = LUNA_LOGICAL_KEY,
    clock: Clock = perf_counter,
) -> RerankEvaluation:
    """Score an injected reranker without opening a provider connection.

    Unknown identifiers are counted and ignored.  Duplicate identifiers are
    ignored after their first occurrence, preserving a stable top-five view.
    The result remains a failed gate whenever an unknown identifier appears.
    """

    if not callable(reranker) or not callable(clock):
        raise RerankEvaluationError("reranker and clock must be callable")
    model = catalog.resolve(logical_key)
    if "rerank" not in model.capabilities:
        raise RerankEvaluationError("selected logical model does not support rerank")
    values = tuple(cases)
    if not values or not all(isinstance(case, RerankEvaluationCase) for case in values):
        raise RerankEvaluationError("cases must contain at least one RerankEvaluationCase")

    hits = 0
    invalid_count = 0
    duplicate_count = 0
    durations_ms: list[float] = []
    for case in values:
        started = clock()
        returned = reranker(case.query, case.candidate_ids)
        elapsed_ms = (clock() - started) * 1_000
        if not isfinite(elapsed_ms) or elapsed_ms < 0:
            raise RerankEvaluationError("clock must return a non-decreasing finite value")
        durations_ms.append(elapsed_ms)
        if isinstance(returned, (str, bytes, bytearray)):
            raise RerankEvaluationError("reranker must return a sequence of identifiers")
        allowed = set(case.candidate_ids)
        ranked: list[str] = []
        seen: set[str] = set()
        for candidate_id in returned:
            if not isinstance(candidate_id, str) or not candidate_id.strip() or candidate_id.strip() not in allowed:
                invalid_count += 1
                continue
            identifier = candidate_id.strip()
            if identifier in seen:
                duplicate_count += 1
                continue
            seen.add(identifier)
            ranked.append(identifier)
        if case.expected_id in ranked[:5]:
            hits += 1

    ordered_durations = sorted(durations_ms)
    p95_index = ceil(len(ordered_durations) * 0.95) - 1
    return RerankEvaluation(
        model_snapshot=model.snapshot,
        case_count=len(values),
        top_5_hits=hits,
        top_5_recall=hits / len(values),
        invalid_id_count=invalid_count,
        duplicate_id_count=duplicate_count,
        p95_latency_ms=ordered_durations[p95_index],
    )


def build_fixed_rerank_fixture() -> tuple[RerankEvaluationCase, ...]:
    """Return the fixed twenty-question, PII-free P3-SP-03 evaluation set."""

    cases: list[RerankEvaluationCase] = []
    for index in range(1, 21):
        token = f"topic-{index:02d}"
        candidate_ids = tuple(f"idea-{index:02d}-{rank:02d}" for rank in range(1, 9))
        # The expected item begins outside the original top five.  A reranker
        # must therefore make a meaningful ordering choice for a perfect score.
        expected_id = candidate_ids[5 + (index % 3)]
        cases.append(
            RerankEvaluationCase(
                query=f"founder graph research for {token}",
                candidate_ids=candidate_ids,
                expected_id=expected_id,
            )
        )
    return tuple(cases)


__all__ = [
    "RerankEvaluation",
    "RerankEvaluationCase",
    "RerankEvaluationError",
    "build_fixed_rerank_fixture",
    "evaluate_reranker",
]
