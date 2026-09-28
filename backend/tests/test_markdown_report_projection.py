from __future__ import annotations

import pytest

from dots.idea_brief import SECTION_TITLES
from dots.markdown_report_projection import (
    find_unique_visible_quote,
    has_visible_markdown_content,
    project_markdown_report,
)


def test_partial_markdown_projects_canonical_positions_and_public_links_only() -> None:
    private_body = "unique draft prose that must not be copied into metadata"
    markdown = (
        f"## {SECTION_TITLES[0]}\n\n{private_body}\n"
        "[公的統計](https://example.test/report)\n\n"
        f"## {SECTION_TITLES[3]}\n\n収益の検討中\n"
    )

    projection = project_markdown_report(markdown)

    assert projection.heading_status == "partial"
    assert [(item.section_index, item.title) for item in projection.headings] == [
        (0, SECTION_TITLES[0]),
        (3, SECTION_TITLES[3]),
    ]
    assert projection.headings[0].heading_offset == markdown.index("## ")
    assert projection.headings[0].body_offset > projection.headings[0].heading_offset
    assert projection.headings[0].end_offset == projection.headings[1].heading_offset
    assert len(projection.links) == 1
    link = projection.links[0]
    assert (link.url, link.label, link.section_index) == (
        "https://example.test/report",
        "公的統計",
        0,
    )
    assert link.verification_status == "url_only"
    assert link.evidence_ids == ()
    assert private_body not in repr(projection)
    assert not hasattr(projection, "markdown")


def test_eight_canonical_headings_in_order_are_complete() -> None:
    markdown = "\n\n".join(f"## {title}\n本文" for title in SECTION_TITLES)

    projection = project_markdown_report(markdown)

    assert projection.heading_status == "complete"
    assert [item.section_index for item in projection.headings] == list(range(8))
    assert all(
        markdown[item.heading_offset : item.heading_offset + len(item.title) + 3]
        == f"## {item.title}"
        for item in projection.headings
    )


def test_fenced_and_inline_code_headings_and_links_are_ignored() -> None:
    markdown = (
        "```markdown\n"
        f"## {SECTION_TITLES[0]}\n[偽リンク](https://ignored.test)\n"
        "```\n"
        f"## {SECTION_TITLES[1]}\n"
        "`[inline](https://inline-ignored.test)`\n"
        "[実リンク](https://example.test/public)\n"
    )

    projection = project_markdown_report(markdown)

    assert projection.heading_status == "partial"
    assert [item.section_index for item in projection.headings] == [1]
    assert [(item.url, item.label, item.section_index) for item in projection.links] == [
        ("https://example.test/public", "実リンク", 1)
    ]


@pytest.mark.parametrize(
    "indexes",
    [
        (0, 2, 2),
        (0, 3, 1),
    ],
    ids=("duplicate", "out-of-order"),
)
def test_ambiguous_heading_sequence_does_not_guess_link_associations(
    indexes: tuple[int, ...],
) -> None:
    markdown = "\n".join(
        f"## {SECTION_TITLES[index]}\n[資料](https://example.test/{offset})"
        for offset, index in enumerate(indexes)
    )

    projection = project_markdown_report(markdown)

    assert projection.heading_status == "ambiguous"
    assert projection.ambiguity_reasons
    assert [item.section_index for item in projection.headings] == list(indexes)
    assert projection.links
    assert all(item.section_index is None for item in projection.links)


def test_unsafe_or_non_public_urls_are_not_projected() -> None:
    markdown = (
        "[安全](https://example.test/public)\n"
        "[資格情報](https://user:password@example.test/private)\n"
        "[秘密付き](https://example.test/?access_token=secret)\n"
        "[スクリプト](javascript:alert(1))\n"
        "https://example.test/plain\n"
    )

    projection = project_markdown_report(markdown)

    assert [item.url for item in projection.links] == [
        "https://example.test/public",
        "https://example.test/plain",
    ]
    assert projection.links[0].label == "安全"
    assert projection.links[1].label is None
    assert all(item.verification_status == "url_only" for item in projection.links)
    assert all(item.evidence_ids == () for item in projection.links)


def test_unique_visible_quote_returns_exact_offsets_but_ignores_code_and_ambiguity() -> None:
    markdown = "Intro `inline secret`.\n\nVisible quote.\n```text\nHidden quote.\n```\n"

    assert find_unique_visible_quote(markdown, "Visible quote.") == (
        markdown.index("Visible quote."), markdown.index("Visible quote.") + len("Visible quote."),
    )
    assert find_unique_visible_quote(markdown, "Hidden quote.") is None
    assert find_unique_visible_quote(markdown, "inline secret") is None
    assert find_unique_visible_quote(markdown + "\nVisible quote.", "Visible quote.") is None
    assert find_unique_visible_quote(markdown, "not present") is None


def test_visible_section_content_ignores_fenced_code_and_checks_offset_ranges() -> None:
    markdown = f"## {SECTION_TITLES[0]}\n\nVisible prose.\n\n```text\nOnly code.\n```\n"
    projection = project_markdown_report(markdown)
    heading = projection.headings[0]

    assert has_visible_markdown_content(markdown, heading.body_offset, heading.end_offset)
    code_only = "```text\nOnly code.\n```\n"
    assert not has_visible_markdown_content(code_only, 0, len(code_only))
    assert not has_visible_markdown_content(markdown, -1, len(markdown))
