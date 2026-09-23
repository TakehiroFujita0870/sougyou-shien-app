from __future__ import annotations

import pytest

from dots.founder_graph_rerank_evaluation import (
    RerankEvaluationCase,
    RerankEvaluationError,
    build_fixed_rerank_fixture,
    evaluate_reranker,
)
from dots.model_catalog import ModelCatalog, ModelCatalogEntry


def _expected_first(query: str, candidate_ids: tuple[str, ...]) -> tuple[str, ...]:
    index = int(query.rsplit("topic-", 1)[1])
    expected = candidate_ids[5 + (index % 3)]
    return (expected, *candidate_ids)


def test_fixed_fixture_records_the_p3_sp_03_target_without_a_provider_call() -> None:
    result = evaluate_reranker(build_fixed_rerank_fixture(), _expected_first)

    assert result.model_snapshot == "luna@founder-graph-v1"
    assert result.case_count == 20
    assert result.top_5_hits == 20
    assert result.top_5_recall == 1.0
    assert result.invalid_id_count == 0
    assert result.p95_latency_ms <= 30_000
    assert result.passes_target is True


def test_unknown_and_duplicate_model_output_are_recorded_and_fail_the_gate() -> None:
    case = RerankEvaluationCase("topic", ("idea-a", "idea-b"), "idea-a")

    result = evaluate_reranker((case,), lambda _query, _candidates: ("unknown", "idea-a", "idea-a"))

    assert result.top_5_hits == 1
    assert result.invalid_id_count == 1
    assert result.duplicate_id_count == 1
    assert result.passes_target is False


def test_fixture_is_fixed_and_requires_meaningful_reordering() -> None:
    fixture = build_fixed_rerank_fixture()

    assert len(fixture) == 20
    assert all(case.expected_id not in case.candidate_ids[:5] for case in fixture)


def test_evaluation_rejects_a_model_without_rerank_capability() -> None:
    catalog = ModelCatalog((ModelCatalogEntry("other", "test", "test-v1", is_default=True),))
    case = RerankEvaluationCase("topic", ("idea-a",), "idea-a")

    with pytest.raises(RerankEvaluationError, match="does not support rerank"):
        evaluate_reranker((case,), lambda _query, candidates: candidates, catalog=catalog, logical_key="other")


def test_evaluation_rejects_non_sequence_model_output() -> None:
    case = RerankEvaluationCase("topic", ("idea-a",), "idea-a")

    with pytest.raises(RerankEvaluationError, match="sequence"):
        evaluate_reranker((case,), lambda _query, _candidates: "idea-a")
