from __future__ import annotations

import pytest

from dots.idea_brief import IdeaBriefSection, SECTION_TITLES
from dots.idea_brief_read_projection import project_brief_support_quote, project_idea_brief_for_read


def _legacy_sections() -> tuple[IdeaBriefSection, ...]:
    return tuple(IdeaBriefSection(index=index, content=f"legacy body {index}") for index in range(8))


def _complete_markdown() -> str:
    return "\n\n".join(
        f"## {title}\n\nprojected body {index}"
        for index, title in enumerate(SECTION_TITLES)
    )


def test_read_projection_derives_legacy_section_shape_without_persisting_body_metadata() -> None:
    markdown = _complete_markdown().replace(
        "projected body 2", "projected body 2\n\n[Source](https://example.test/public)"
    )

    projection = project_idea_brief_for_read(markdown, _legacy_sections())

    assert projection.section_contents == tuple(f"projected body {index}" for index in range(8))[:2] + (
        "projected body 2\n\n[Source](https://example.test/public)",
    ) + tuple(f"projected body {index}" for index in range(3, 8))
    assert projection.metadata is not None
    assert projection.metadata["heading_status"] == "complete"
    assert projection.metadata["links"] == [{
        "url": "https://example.test/public",
        "label": "Source",
        "offset": markdown.index("https://example.test/public"),
        "section_index": 2,
        "verification_status": "url_only",
        "evidence_ids": [],
    }]
    assert "projected body" not in repr(projection.metadata)


def test_markdown_absence_preserves_legacy_content_without_projection_metadata() -> None:
    projection = project_idea_brief_for_read(None, _legacy_sections())

    assert projection.section_contents == tuple(f"legacy body {index}" for index in range(8))
    assert projection.metadata is None


def test_partial_markdown_projects_only_observed_sections() -> None:
    markdown = f"## {SECTION_TITLES[1]}\n\npartial body"

    projection = project_idea_brief_for_read(markdown, _legacy_sections())

    assert projection.section_contents == ("", "partial body", "", "", "", "", "", "")
    assert projection.metadata is not None
    assert projection.metadata["heading_status"] == "partial"


def test_ambiguous_markdown_fails_closed_for_content_and_link_association() -> None:
    markdown = (
        f"## {SECTION_TITLES[0]}\n\nfirst\n"
        "[Source](https://example.test/public)\n"
        f"## {SECTION_TITLES[0]}\n\nsecond"
    )

    projection = project_idea_brief_for_read(markdown, _legacy_sections())

    assert projection.section_contents == ("",) * 8
    assert projection.metadata is not None
    assert projection.metadata["heading_status"] == "ambiguous"
    assert projection.metadata["links"][0]["section_index"] is None


def test_support_quote_uses_unique_unicode_character_offsets_in_partial_markdown() -> None:
    markdown = f"## {SECTION_TITLES[2]}\n\n起業家が市場を検証する"
    quote = "起業家が市場"
    start = markdown.index(quote)

    assert start != len(markdown[:start].encode("utf-8"))
    assert project_brief_support_quote(markdown, start=start, end=start + len(quote), section_index=2) == quote


@pytest.mark.parametrize(
    ("markdown", "start", "end", "section_index"),
    [
        ("## heading\n\ntext", -1, 2, None),
        ("## heading\n\ntext", 100, 105, None),
        ("## heading\n\n   ", 15, 18, None),
        ("## heading\n\nrepeat\n\nrepeat", 12, 18, None),
        ("## heading\n\n`hidden`", 13, 19, None),
        ("## heading\n\n```\nhidden\n```", 13, 19, None),
        (
            f"## {SECTION_TITLES[0]}\n\nfirst\n## {SECTION_TITLES[0]}\n\nambiguous",
            49,
            58,
            None,
        ),
    ],
)
def test_support_quote_fails_closed_for_invalid_or_ambiguous_offsets(
    markdown: str, start: int, end: int, section_index: int | None,
) -> None:
    assert project_brief_support_quote(markdown, start=start, end=end, section_index=section_index) is None


def test_support_quote_fails_closed_when_section_locator_disagrees() -> None:
    markdown = f"## {SECTION_TITLES[0]}\n\nwrong chapter"
    quote = "wrong chapter"
    start = markdown.index(quote)

    assert project_brief_support_quote(
        markdown, start=start, end=start + len(quote), section_index=1,
    ) is None


def test_support_quote_is_bounded() -> None:
    markdown = "## Draft\n\n" + "x" * 1201
    start = markdown.index("x")

    assert project_brief_support_quote(markdown, start=start, end=len(markdown), section_index=None) is None
