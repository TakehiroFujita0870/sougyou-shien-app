"""Read-time section text and public metadata derived from IdeaBrief Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .idea_brief import SECTION_TITLES
from .markdown_report_projection import (
    MarkdownReportProjection,
    find_unique_visible_quote,
    has_visible_markdown_content,
    project_markdown_report,
)


_MAX_SUPPORT_QUOTE_CHARS = 1200


@dataclass(frozen=True, slots=True)
class IdeaBriefReadProjection:
    section_contents: tuple[str, ...]
    markdown_projection: MarkdownReportProjection | None

    @property
    def metadata(self) -> dict[str, Any] | None:
        projection = self.markdown_projection
        if projection is None:
            return None
        return {
            "heading_status": projection.heading_status,
            "headings": [
                {
                    "section_index": heading.section_index,
                    "title": heading.title,
                    "heading_offset": heading.heading_offset,
                    "body_offset": heading.body_offset,
                    "end_offset": heading.end_offset,
                }
                for heading in projection.headings
            ],
            "links": [
                {
                    "url": link.url,
                    "label": link.label,
                    "offset": link.offset,
                    "section_index": link.section_index,
                    "verification_status": link.verification_status,
                    "evidence_ids": list(link.evidence_ids),
                }
                for link in projection.links
            ],
            "ambiguity_reasons": list(projection.ambiguity_reasons),
            "links_truncated": projection.links_truncated,
        }


def _section_body(markdown: str, projection: MarkdownReportProjection, section_index: int) -> str:
    if projection.heading_status == "ambiguous":
        return ""
    heading = next((item for item in projection.headings if item.section_index == section_index), None)
    if heading is None:
        return ""
    return markdown[heading.body_offset : heading.end_offset].strip()


def project_idea_brief_for_read(
    report_markdown: str | None,
    sections: tuple[Any, ...] | list[Any],
) -> IdeaBriefReadProjection:
    """Preserve legacy stored text only when Markdown is absent; otherwise derive by offsets."""
    if not isinstance(sections, (tuple, list)) or not 1 <= len(sections) <= len(SECTION_TITLES):
        raise ValueError("IdeaBrief must contain one through eight sections")
    by_index: dict[int, Any] = {}
    for section in sections:
        index = getattr(section, "index", None)
        if type(index) is not int or not 0 <= index < len(SECTION_TITLES) or index in by_index:
            raise ValueError("IdeaBrief section indexes must be unique and canonical")
        by_index[index] = section
    if report_markdown is None:
        return IdeaBriefReadProjection(
            section_contents=tuple(
                by_index[index].content if index in by_index else ""
                for index in range(len(SECTION_TITLES))
            ),
            markdown_projection=None,
        )
    if not isinstance(report_markdown, str):
        raise TypeError("report_markdown must be a string or None")
    projection = project_markdown_report(report_markdown)
    return IdeaBriefReadProjection(
        section_contents=tuple(
            _section_body(report_markdown, projection, index)
            for index in range(len(SECTION_TITLES))
        ),
        markdown_projection=projection,
    )


def brief_support_locator_is_valid(
    report_markdown: str | None,
    *,
    start: int,
    end: int,
    section_index: int | None,
) -> bool:
    """Validate a bounded visible location without copying its report text."""
    if (
        not isinstance(report_markdown, str)
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(report_markdown)
        or end - start > _MAX_SUPPORT_QUOTE_CHARS
    ):
        return False
    if section_index is not None and (type(section_index) is not int or not 0 <= section_index < len(SECTION_TITLES)):
        return False
    try:
        projection = project_markdown_report(report_markdown)
    except (TypeError, ValueError):
        return False
    if projection.heading_status == "ambiguous":
        return False
    if section_index is not None:
        heading = next((item for item in projection.headings if item.section_index == section_index), None)
        if heading is None or not heading.body_offset <= start < end <= heading.end_offset:
            return False
    return has_visible_markdown_content(report_markdown, start, end)


def project_brief_support_quote(
    report_markdown: str | None,
    *,
    start: int,
    end: int,
    section_index: int | None,
) -> str | None:
    """Resolve one unique visible quote from an unambiguous Brief location."""
    if not brief_support_locator_is_valid(
        report_markdown, start=start, end=end, section_index=section_index,
    ):
        return None
    assert isinstance(report_markdown, str)
    quote = report_markdown[start:end]
    if find_unique_visible_quote(report_markdown, quote) != (start, end):
        return None
    return quote


def brief_section_has_readable_body(brief: Any, section_index: int) -> bool:
    """Fail closed unless the selected current section has readable, unambiguous text."""
    if type(section_index) is not int or not 0 <= section_index < len(SECTION_TITLES):
        return False
    try:
        projection = project_idea_brief_for_read(brief.report_markdown, brief.sections)
    except (AttributeError, TypeError, ValueError):
        return False
    return bool(projection.section_contents[section_index].strip())
