"""Bounded, content-free metadata projection for an IdeaBrief Markdown report."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .idea_brief import SECTION_TITLES
from .source_citations import citation_metadata


HeadingStatus = Literal["partial", "complete", "ambiguous"]


@dataclass(frozen=True, slots=True)
class ProjectedHeading:
    section_index: int
    title: str
    heading_offset: int
    body_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class ProjectedLink:
    url: str
    label: str | None
    offset: int
    section_index: int | None
    verification_status: Literal["url_only"] = "url_only"
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MarkdownReportProjection:
    heading_status: HeadingStatus
    headings: tuple[ProjectedHeading, ...]
    links: tuple[ProjectedLink, ...]
    ambiguity_reasons: tuple[str, ...]
    links_truncated: bool


_MAX_MARKDOWN_CHARS = 60_000
_MAX_LINKS = 128
_ATX_H2 = re.compile(r"^ {0,3}##(?!#)[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_INLINE_RUN = re.compile(r"`+")
_MARKDOWN_LINK = re.compile(
    r"\[([^\]\r\n]{1,300})\]\(\s*(?:<([^>\s]+)>|([^\s)]+))"
    r"(?:\s+\"[^\"]*\"|\s+'[^']*')?\s*\)"
)
_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>", re.IGNORECASE)
_BARE_URL = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]*>")
_LABEL_MARKUP = re.compile(r"[`*_~\[\]\\]+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _mask_span(chars: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if chars[index] not in "\r\n":
            chars[index] = " "


def _visible_markdown(markdown: str) -> str:
    """Mask fenced and inline code while preserving original character offsets."""
    chars = list(markdown)
    fence_marker: str | None = None
    fence_length = 0
    offset = 0
    for line in markdown.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if fence_marker is None:
            opening = _FENCE_OPEN.match(content)
            if opening:
                run = opening.group(1)
                if run[0] != "`" or "`" not in opening.group(2):
                    fence_marker, fence_length = run[0], len(run)
                    _mask_span(chars, offset, offset + len(line))
        else:
            closing = _FENCE_CLOSE.match(content)
            _mask_span(chars, offset, offset + len(line))
            if closing and closing.group(1)[0] == fence_marker and len(closing.group(1)) >= fence_length:
                fence_marker = None
                fence_length = 0
        offset += len(line)

    masked = "".join(chars)
    chars = list(masked)
    runs = list(_INLINE_RUN.finditer(masked))
    index = 0
    while index < len(runs):
        opening = runs[index]
        length = len(opening.group())
        closing_index = next(
            (
                candidate
                for candidate in range(index + 1, len(runs))
                if len(runs[candidate].group()) == length
            ),
            None,
        )
        if closing_index is None:
            index += 1
            continue
        _mask_span(chars, opening.start(), runs[closing_index].end())
        index = closing_index + 1
    return "".join(chars)


def _safe_label(value: str) -> str | None:
    value = _HTML_TAG.sub(" ", value)
    value = _LABEL_MARKUP.sub("", value)
    value = _CONTROL.sub(" ", value)
    value = " ".join(value.split())[:160].strip()
    return value or None


def _clean_url(value: str) -> str:
    value = value.rstrip(".,;:!?")
    while value.endswith((")", "]", "}")):
        closing = value[-1]
        opening = {")": "(", "]": "[", "}": "{"}[closing]
        if value.count(closing) <= value.count(opening):
            break
        value = value[:-1]
    return value


def _link_candidates(markdown: str) -> list[tuple[int, int, str, str | None]]:
    candidates: list[tuple[int, int, str, str | None]] = []
    occupied: list[tuple[int, int]] = []

    def add(start: int, end: int, raw_url: str, label: str | None) -> None:
        if any(start < used_end and end > used_start for used_start, used_end in occupied):
            return
        url = _clean_url(raw_url)
        safe_label = _safe_label(label) if label is not None else None
        if not url or citation_metadata({"locator": url, "title": safe_label or "Public link"}) is None:
            return
        candidates.append((start, end, url, safe_label))
        occupied.append((start, end))

    for match in _MARKDOWN_LINK.finditer(markdown):
        url_group = 2 if match.group(2) is not None else 3
        add(match.start(url_group), match.end(url_group), match.group(url_group), match.group(1))
    for match in _AUTOLINK.finditer(markdown):
        add(match.start(1), match.end(1), match.group(1), None)
    for match in _BARE_URL.finditer(markdown):
        add(match.start(), match.end(), match.group(), None)
    candidates.sort(key=lambda item: item[0])
    return candidates


def project_markdown_report(markdown: str) -> MarkdownReportProjection:
    """Return canonical heading positions and safe URL-only citations, never body text."""
    if not isinstance(markdown, str):
        raise TypeError("markdown must be a string")
    if len(markdown) > _MAX_MARKDOWN_CHARS:
        raise ValueError("markdown exceeds the IdeaBrief report limit")

    visible = _visible_markdown(markdown)
    boundaries: list[tuple[int, int | None, str | None, int]] = []
    title_indexes = {title: index for index, title in enumerate(SECTION_TITLES)}
    offset = 0
    for line in visible.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        match = _ATX_H2.match(content)
        if match:
            title = match.group(1).strip()
            boundaries.append((offset, title_indexes.get(title), title, offset + len(line)))
        offset += len(line)

    canonical = [item for item in boundaries if item[1] is not None]
    indexes = [item[1] for item in canonical]
    reasons: list[str] = []
    for previous, current in zip(indexes, indexes[1:]):
        if current == previous:
            reasons.append("duplicate_heading")
        elif current < previous:
            reasons.append("out_of_order_heading")
    ambiguous = bool(reasons)
    complete = indexes == list(range(len(SECTION_TITLES)))
    heading_status: HeadingStatus = "ambiguous" if ambiguous else "complete" if complete else "partial"

    headings = tuple(
        ProjectedHeading(
            section_index=section_index,
            title=title or "",
            heading_offset=heading_offset,
            body_offset=body_offset,
            end_offset=boundaries[position + 1][0] if position + 1 < len(boundaries) else len(markdown),
        )
        for position, (heading_offset, section_index, title, body_offset) in enumerate(boundaries)
        if section_index is not None
    )

    links_truncated = False
    links: list[ProjectedLink] = []
    for offset, _end, url, label in _link_candidates(visible):
        if len(links) >= _MAX_LINKS:
            links_truncated = True
            break
        section_index: int | None = None
        if not ambiguous:
            for heading in headings:
                if heading.body_offset <= offset < heading.end_offset:
                    section_index = heading.section_index
                    break
                if heading.body_offset > offset:
                    break
        links.append(
            ProjectedLink(
                url=url,
                label=label,
                offset=offset,
                section_index=section_index,
            )
        )

    return MarkdownReportProjection(
        heading_status=heading_status,
        headings=headings,
        links=tuple(links),
        ambiguity_reasons=tuple(dict.fromkeys(reasons)),
        links_truncated=links_truncated,
    )


def find_unique_visible_quote(markdown: str, quote: str) -> tuple[int, int] | None:
    """Locate one exact quote in visible Markdown without returning report text.

    Fenced and inline code is masked using the same rules as the projection, so
    code examples cannot act as semantic support. Repeated quotes are
    intentionally unresolved because an offset would otherwise be ambiguous.
    """
    if not isinstance(markdown, str) or len(markdown) > _MAX_MARKDOWN_CHARS:
        raise ValueError("markdown exceeds the IdeaBrief report limit")
    if not isinstance(quote, str) or not quote.strip():
        return None
    visible = _visible_markdown(markdown)
    start = visible.find(quote)
    if start < 0 or visible.find(quote, start + 1) >= 0:
        return None
    return start, start + len(quote)


def has_visible_markdown_content(markdown: str, start: int, end: int) -> bool:
    """Return whether an offset range contains non-code, non-whitespace text."""
    if not isinstance(markdown, str) or len(markdown) > _MAX_MARKDOWN_CHARS:
        raise ValueError("markdown exceeds the IdeaBrief report limit")
    if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(markdown):
        return False
    return bool(_visible_markdown(markdown)[start:end].strip())
