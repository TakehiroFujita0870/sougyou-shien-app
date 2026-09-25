from dataclasses import FrozenInstanceError

import pytest

from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion, IdeaBriefValidationError, SECTION_TITLES


def test_partial_brief_has_eight_ordered_sections_without_inventing_content():
    brief = IdeaBriefVersion(
        owner_id="owner-test",
        idea_lineage_root_id="idea-root",
        based_on_idea_id="idea-current",
        sections=(IdeaBriefSection(index=3, content="月額利用料を仮説とする", unconfirmed=("価格受容性",)),),
    )

    assert brief.revision == 1
    assert SECTION_TITLES[5:] == ("実現可能性", "リスク・撤退ライン", "リスクミニマムなロードマップ")
    assert [section.index for section in brief.sections] == list(range(8))
    assert brief.sections[0].content == ""
    assert brief.sections[3].unconfirmed == ("価格受容性",)


def test_revision_retains_lineage_and_leaves_old_version_unchanged():
    first = IdeaBriefVersion(
        owner_id="owner-test",
        idea_lineage_root_id="idea-root",
        based_on_idea_id="idea-current",
        sections=(IdeaBriefSection(index=0, content="初版", evidence_ids=("evidence-1",)),),
    )

    second = first.revise(
        sections=(IdeaBriefSection(index=0, content="再検討版", evidence_ids=("evidence-1",)),),
        change_reason="市場調査を反映",
    )

    assert second.id != first.id
    assert second.revision == 2
    assert second.supersedes_id == first.id
    assert second.idea_lineage_root_id == first.idea_lineage_root_id
    assert first.sections[0].content == "初版"
    assert second.sections[0].content == "再検討版"
    with pytest.raises(FrozenInstanceError):
        first.revision = 99


def test_duplicate_or_out_of_range_sections_fail():
    with pytest.raises(IdeaBriefValidationError):
        IdeaBriefVersion(
            owner_id="owner-test",
            idea_lineage_root_id="idea-root",
            based_on_idea_id="idea-current",
            sections=(IdeaBriefSection(index=0), IdeaBriefSection(index=0)),
        )
    with pytest.raises(IdeaBriefValidationError):
        IdeaBriefSection(index=8)


def test_section_rejects_unbounded_text_and_duplicate_evidence():
    with pytest.raises(IdeaBriefValidationError):
        IdeaBriefSection(index=1, content="a" * 4001)
    with pytest.raises(IdeaBriefValidationError):
        IdeaBriefSection(index=1, evidence_ids=("e-1", "e-1"))


def test_default_private_and_no_broader_shareability_than_idea():
    brief = IdeaBriefVersion(
        owner_id="owner-test",
        idea_lineage_root_id="idea-root",
        based_on_idea_id="idea-current",
    )
    assert brief.egress_policy == "local_only"
    assert brief.can_share_with_chatgpt(idea_egress_policy="shareable") is False
    assert brief.revise(egress_policy="shareable").can_share_with_chatgpt(idea_egress_policy="local_only") is False
    assert brief.revise(egress_policy="shareable").can_share_with_chatgpt(idea_egress_policy="shareable") is True


def test_explicit_empty_revision_values_do_not_silently_reuse_old_values():
    brief = IdeaBriefVersion(owner_id="owner-test", idea_lineage_root_id="idea-root", based_on_idea_id="idea-current")
    with pytest.raises(IdeaBriefValidationError):
        brief.revise(based_on_idea_id="")
    with pytest.raises(IdeaBriefValidationError):
        brief.revise(egress_policy="")  # type: ignore[arg-type]
