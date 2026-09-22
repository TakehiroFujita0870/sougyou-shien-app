from __future__ import annotations

from copy import deepcopy

import pytest

from dots.founder_graph import ReportSection, ReportVersion
from dots.founder_graph_report_diff import (
    FOUNDER_GRAPH_REPORT_CHAPTERS,
    ReportDiffInputError,
    diff_report_versions,
    project_report_version,
)


EXPECTED_CHAPTERS = (
    (0, "エグゼクティブサマリー"),
    (1, "ビジネスモデル"),
    (2, "顧客とマーケットサイズ"),
    (3, "収益モデル"),
    (4, "競争優位性"),
    (5, "実現可能性"),
    (6, "リスク・撤退ライン"),
    (7, "リスクミニマムなロードマップ"),
)


def _mapping_report(*sections: dict[str, object], **fields: object) -> dict[str, object]:
    return {
        "id": fields.pop("id", "report-1"),
        "owner_id": fields.pop("owner_id", "owner-1"),
        "sections": list(sections),
        **fields,
    }


def _domain_report(*, content: str = "same", owner_id: str = "owner-1") -> ReportVersion:
    sections = tuple(
        ReportSection(
            owner_id=owner_id,
            id=section_id,
            content=content if section_id == 0 else f"section-{section_id}",
            evidence_ids=(f"evidence-{section_id}",),
        )
        for section_id, _ in EXPECTED_CHAPTERS
    )
    return ReportVersion(
        owner_id=owner_id,
        id="report-domain",
        sections=sections,
        run_ids=("run-1",),
        evidence_ids=("evidence-0",),
    )


def test_project_report_version_accepts_domain_and_safe_mappings() -> None:
    domain = project_report_version(_domain_report())
    mapping = project_report_version(
        _mapping_report(
            {"id": 0, "content": "summary", "evidence_ids": ["evidence-1"]},
            {"id": "3", "content": "revenue"},
            status="draft",
            references=["source-1"],
        )
    )

    assert domain is not None
    assert [section.id for section in domain.sections] == list(range(8))
    assert mapping is not None
    assert [section.id for section in mapping.sections] == [0, 3]
    assert mapping.sections[0].title == "エグゼクティブサマリー"
    assert mapping.references == ("source-1",)


def test_fixed_eight_chapter_names_are_used_even_when_mapping_titles_are_tampered() -> None:
    assert tuple((int(chapter["id"]), str(chapter["title"])) for chapter in FOUNDER_GRAPH_REPORT_CHAPTERS) == EXPECTED_CHAPTERS

    projected = project_report_version(
        _mapping_report(
            {"id": 5, "title": "攻撃者が差し替えた名前", "content": "feasible"},
        )
    )
    assert projected is not None
    assert projected.sections[0].title == "実現可能性"


def test_diff_marks_added_changed_unchanged_and_removed() -> None:
    previous = _mapping_report(
        {"id": 0, "content": "summary"},
        {"id": 1, "content": "old model"},
        {"id": 2, "content": "same"},
    )
    current = _mapping_report(
        {"id": 1, "content": "new model"},
        {"id": 2, "content": "same"},
        {"id": 3, "content": "new revenue"},
    )

    diff = diff_report_versions(previous, current)

    assert [section.status for section in diff.sections] == [
        "removed",
        "changed",
        "unchanged",
        "added",
        "unchanged",
        "unchanged",
        "unchanged",
        "unchanged",
    ]
    assert diff.impacted_chapter_ids == (0, 1, 3)
    assert diff.unchanged_chapter_ids == (2, 4, 5, 6, 7)
    assert diff.removed_chapter_ids == (0,)
    assert diff.changed_chapter_ids == (1,)
    assert diff.added_chapter_ids == (3,)


def test_diff_includes_references_withdrawn_claims_and_follow_up_context() -> None:
    previous = _mapping_report(
        {"id": 0, "content": "old", "references": ["source-old"], "withdrawn_claims": ["claim-old"]},
        references=["report-source-old"],
        withdrawn_claims=[{"id": "claim-report-old", "reason": "反証"}],
    )
    current = _mapping_report(
        {
            "id": 0,
            "content": "new",
            "references": ["source-new"],
            "withdrawn_claims": [{"id": "claim-old", "reason": "反証"}],
        },
        references=["report-source-new"],
    )

    diff = diff_report_versions(
        previous,
        current,
        follow_up_question="この会社も同種ではないか？",
        follow_up_evidence_ids=["evidence-new", {"id": "evidence-second", "raw": "do not copy"}],
    )

    assert diff.follow_up_question == "この会社も同種ではないか？"
    assert diff.follow_up_evidence_ids == ("evidence-new", "evidence-second")
    assert diff.references == ("report-source-new",)
    assert diff.withdrawn_claims == ()
    assert diff.sections[0].previous.references == ("source-old",)
    assert diff.sections[0].current.references == ("source-new",)
    assert diff.sections[0].current.withdrawn_claims == ("claim-old · 反証",)
    assert diff.report_metadata_changed is True
    rendered = repr(diff.as_dict())
    assert "do not copy" not in rendered
    assert "private raw" not in rendered


def test_projection_omits_private_and_raw_fields_and_does_not_mutate_input() -> None:
    report = _mapping_report(
        {
            "id": 0,
            "content": "safe content",
            "source_text": "private source text",
            "private_notes": "private note",
            "raw": {"secret": "raw"},
            "metadata": {
                "references": [{"id": "safe-ref", "raw": "private raw"}],
                "private_notes": "private metadata",
            },
        },
        metadata={
            "references": [{"id": "report-ref", "source_text": "private"}],
            "raw": "do not copy",
        },
        private_notes="private report note",
    )
    original = deepcopy(report)

    projected = project_report_version(report)
    assert projected is not None
    result = projected.as_dict()
    rendered = repr(result)
    assert "private" not in rendered
    assert "source text" not in rendered
    assert "private raw" not in rendered
    assert "do not copy" not in rendered
    assert result["references"] == ["report-ref"]
    assert report == original


def test_diff_keeps_old_projection_immutable_and_rejects_cross_owner_or_malformed_input() -> None:
    previous = _mapping_report({"id": 0, "content": "old"})
    current = _mapping_report({"id": 0, "content": "new"})
    diff = diff_report_versions(previous, current)
    previous["sections"].append({"id": 7, "content": "mutated after call"})  # type: ignore[union-attr]
    assert diff.previous is not None
    assert [section.id for section in diff.previous.sections] == [0]
    assert diff.previous.sections[0].content == "old"

    with pytest.raises(ReportDiffInputError, match="same owner"):
        diff_report_versions(
            _mapping_report({"id": 0}, owner_id="owner-1"),
            _mapping_report({"id": 0}, owner_id="owner-2"),
        )
    with pytest.raises(ReportDiffInputError, match="sections"):
        project_report_version({"id": "malformed", "sections": "not-a-collection"})
    with pytest.raises(ReportDiffInputError, match="section id"):
        project_report_version(_mapping_report({"id": 99, "content": "unknown chapter"}))
