"""Read-time section text and public metadata derived from IdeaBrief Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .idea_brief import SECTION_TITLES
from .markdown_report_projection import MarkdownReportProjection, project_markdown_report


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


def brief_section_has_readable_body(brief: Any, section_index: int) -> bool:
    """Fail closed unless the selected current section has readable, unambiguous text."""
    if type(section_index) is not int or not 0 <= section_index < len(SECTION_TITLES):
        return False
    try:
        projection = project_idea_brief_for_read(brief.report_markdown, brief.sections)
    except (AttributeError, TypeError, ValueError):
        return False
    return bool(projection.section_contents[section_index].strip())
