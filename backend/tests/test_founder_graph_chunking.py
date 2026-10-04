from __future__ import annotations

import pytest

from nebula import founder_graph, founder_graph_chunking


def test_chunking_contract_is_reexported_without_changing_identity() -> None:
    exported_names = (
        "CONTENT_CHUNK_MAX_LENGTH",
        "CONTENT_CHUNK_TARGET_LENGTH",
        "split_source_content",
        "_paragraph_boundaries",
        "_sentence_boundaries",
        "_whitespace_boundaries",
        "_select_chunk_boundary",
    )

    for name in exported_names:
        assert getattr(founder_graph, name) is getattr(founder_graph_chunking, name)

    assert founder_graph.DomainValidationError is founder_graph_chunking.DomainValidationError


def test_chunking_module_preserves_ranges_and_domain_validation() -> None:
    content = "😀" * 2_380 + ". " + "文章" * 1_400

    ranges = founder_graph_chunking.split_source_content(content)

    assert ranges[0] == (0, 2_382, content[:2_382])
    assert ranges[-1][1] == len(content)
    assert "".join(text for _start, _end, text in ranges) == content
    with pytest.raises(founder_graph.DomainValidationError, match="chunk lengths"):
        founder_graph_chunking.split_source_content("content", target_length=0)
