"""Immutable, compact business-idea briefs independent of research reports.

An Idea currently has a legacy supersession chain whose ID changes on
correction.  A brief uses the first Idea ID as its lineage key while retaining
the exact Idea revision on which the brief was based.  No existing Idea needs
to be rewritten to introduce a brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4


class IdeaBriefValidationError(ValueError):
    """A brief violates its bounded domain contract."""


EgressPolicy = Literal["local_only", "shareable"]
SECTION_TITLES: tuple[str, ...] = (
    "エグゼクティブサマリー",
    "ビジネスモデル",
    "顧客とマーケットサイズ",
    "収益モデル",
    "競争優位性",
    "実現可能性",
    "リスク・撤退ライン",
    "リスクミニマムなロードマップ",
)


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise IdeaBriefValidationError(f"{name} must be a non-empty short identifier")
    return value.strip()


def _strings(values: tuple[str, ...] | list[str], name: str, *, limit: int = 32) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or len(values) > limit:
        raise IdeaBriefValidationError(f"{name} must be a bounded sequence")
    result = tuple(_identifier(value, name) for value in values)
    if len(result) != len(set(result)):
        raise IdeaBriefValidationError(f"{name} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class IdeaBriefSection:
    index: int
    content: str = ""
    facts: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()
    unconfirmed: tuple[str, ...] = ()
    owner_decisions: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index <= 7:
            raise IdeaBriefValidationError("section index must be 0 through 7")
        if not isinstance(self.content, str) or len(self.content) > 4000:
            raise IdeaBriefValidationError("section content exceeds 4000 characters")
        for name in ("facts", "inferences", "unconfirmed", "owner_decisions", "claim_ids", "evidence_ids"):
            object.__setattr__(self, name, _strings(getattr(self, name), name))


@dataclass(frozen=True, slots=True, kw_only=True)
class IdeaBriefVersion:
    owner_id: str
    idea_lineage_root_id: str
    based_on_idea_id: str
    sections: tuple[IdeaBriefSection, ...] = ()
    research_run_ids: tuple[str, ...] | list[str] = ()
    id: str = field(default_factory=lambda: f"idea-brief_{uuid4().hex}")
    revision: int = 1
    supersedes_id: str | None = None
    change_reason: str = "initial"
    egress_policy: EgressPolicy = "local_only"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        for name in ("owner_id", "idea_lineage_root_id", "based_on_idea_id", "id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if type(self.revision) is not int or self.revision < 1:
            raise IdeaBriefValidationError("revision must be a positive integer")
        if self.revision == 1 and self.supersedes_id is not None:
            raise IdeaBriefValidationError("first revision cannot supersede another brief")
        if self.revision > 1:
            object.__setattr__(self, "supersedes_id", _identifier(self.supersedes_id, "supersedes_id"))
            if self.supersedes_id == self.id:
                raise IdeaBriefValidationError("a brief cannot supersede itself")
        if not isinstance(self.change_reason, str) or not self.change_reason.strip() or len(self.change_reason) > 500:
            raise IdeaBriefValidationError("change_reason must be 1 through 500 characters")
        if self.egress_policy not in ("local_only", "shareable"):
            raise IdeaBriefValidationError("egress_policy must be local_only or shareable")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise IdeaBriefValidationError("created_at must include a timezone")
        if not isinstance(self.sections, (tuple, list)) or not all(isinstance(section, IdeaBriefSection) for section in self.sections):
            raise IdeaBriefValidationError("sections must be IdeaBriefSection values")
        by_index = {section.index: section for section in self.sections}
        if len(by_index) != len(self.sections):
            raise IdeaBriefValidationError("section indexes must be unique")
        object.__setattr__(self, "sections", tuple(by_index.get(index, IdeaBriefSection(index=index)) for index in range(len(SECTION_TITLES))))
        object.__setattr__(self, "research_run_ids", _strings(self.research_run_ids, "research_run_ids"))

    def revise(
        self,
        *,
        sections: tuple[IdeaBriefSection, ...] = (),
        change_reason: str = "revision",
        based_on_idea_id: str | None = None,
        research_run_ids: tuple[str, ...] | list[str] | None = None,
        egress_policy: EgressPolicy | None = None,
    ) -> IdeaBriefVersion:
        """Create a new version; omitted sections keep their prior content."""
        if not isinstance(sections, (tuple, list)) or not all(isinstance(section, IdeaBriefSection) for section in sections):
            raise IdeaBriefValidationError("sections must be IdeaBriefSection values")
        if len({section.index for section in sections}) != len(sections):
            raise IdeaBriefValidationError("section indexes must be unique")
        merged = {section.index: section for section in self.sections}
        merged.update({section.index: section for section in sections})
        return replace(
            self,
            id=f"idea-brief_{uuid4().hex}",
            revision=self.revision + 1,
            supersedes_id=self.id,
            based_on_idea_id=self.based_on_idea_id if based_on_idea_id is None else based_on_idea_id,
            research_run_ids=self.research_run_ids if research_run_ids is None else research_run_ids,
            sections=tuple(merged.values()),
            change_reason=change_reason,
            egress_policy=self.egress_policy if egress_policy is None else egress_policy,
            created_at=datetime.now(timezone.utc),
        )

    def can_share_with_chatgpt(self, *, idea_egress_policy: EgressPolicy) -> bool:
        return self.egress_policy == "shareable" and idea_egress_policy == "shareable"
