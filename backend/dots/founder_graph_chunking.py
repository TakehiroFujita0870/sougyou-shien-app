"""Pure source-content segmentation for the Founder Graph domain."""

from __future__ import annotations

from .founder_graph_errors import DomainValidationError


CONTENT_CHUNK_TARGET_LENGTH = 2_400
CONTENT_CHUNK_MAX_LENGTH = 4_000


def _paragraph_boundaries(content: str, start: int, limit: int) -> tuple[int, ...]:
    boundaries: list[int] = []
    index = start
    while index < limit:
        if content[index] not in "\r\n":
            index += 1
            continue
        end = index
        newline_count = 0
        while end < limit and content[end] in "\r\n":
            if content[end] == "\r" and end + 1 < len(content) and content[end + 1] == "\n":
                end += 2
            else:
                end += 1
            newline_count += 1
        if newline_count >= 2 and end <= limit:
            boundaries.append(end)
        index = end
    return tuple(boundaries)


def _sentence_boundaries(content: str, start: int, limit: int) -> tuple[int, ...]:
    terminators = frozenset(".!?。！？")
    closers = frozenset("\"'”’»）】〕〉》")
    boundaries: list[int] = []
    index = start
    while index < limit:
        if content[index] not in terminators:
            index += 1
            continue
        end = index + 1
        while end < limit and content[end] in closers:
            end += 1
        if end < len(content) and not content[end].isspace():
            index += 1
            continue
        while end < limit and content[end].isspace():
            end += 1
        if end <= limit:
            boundaries.append(end)
        index = end
    return tuple(boundaries)


def _whitespace_boundaries(content: str, start: int, limit: int) -> tuple[int, ...]:
    boundaries: list[int] = []
    index = start
    while index < limit:
        if not content[index].isspace():
            index += 1
            continue
        end = index + 1
        while end < limit and content[end].isspace():
            end += 1
        boundaries.append(end)
        index = end
    return tuple(boundaries)


def _select_chunk_boundary(content: str, start: int, target: int, maximum: int) -> int:
    """Select a preferred structural boundary, or hard-split at maximum."""

    boundary_candidates = (
        _paragraph_boundaries(content, start, maximum),
        _sentence_boundaries(content, start, maximum),
        _whitespace_boundaries(content, start, maximum),
    )
    for candidates in boundary_candidates:
        candidates = tuple(candidate for candidate in candidates if start < candidate <= target)
        if candidates:
            return max(candidates)
    for candidates in boundary_candidates:
        candidates = tuple(candidate for candidate in candidates if target < candidate <= maximum)
        if candidates:
            return min(candidates)
    return maximum


def split_source_content(
    content: str,
    *,
    target_length: int = CONTENT_CHUNK_TARGET_LENGTH,
    max_length: int = CONTENT_CHUNK_MAX_LENGTH,
) -> tuple[tuple[int, int, str], ...]:
    """Split content into contiguous Unicode-codepoint ranges.

    Structural boundaries are preferred in paragraph, sentence, and whitespace
    order. The returned text slices concatenate exactly to the input string.
    """

    if not isinstance(content, str):
        raise DomainValidationError("source content must be a string")
    if (
        not isinstance(target_length, int)
        or isinstance(target_length, bool)
        or target_length < 1
        or not isinstance(max_length, int)
        or isinstance(max_length, bool)
        or max_length < target_length
    ):
        raise DomainValidationError("chunk lengths must be positive integers with max_length >= target_length")
    if not content:
        return ()

    chunks: list[tuple[int, int, str]] = []
    start = 0
    content_length = len(content)
    while start < content_length:
        remaining = content_length - start
        if remaining <= max_length:
            end = content_length
        else:
            target = min(start + target_length, content_length)
            maximum = min(start + max_length, content_length)
            end = _select_chunk_boundary(content, start, target, maximum)
        if end <= start:
            raise DomainValidationError("chunk splitter produced an empty range")
        chunks.append((start, end, content[start:end]))
        start = end
    return tuple(chunks)
