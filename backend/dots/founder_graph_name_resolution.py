"""Local-only candidate generation and synthetic evaluation for Person records.

This module deliberately returns review candidates only.  It never writes to a
graph, changes a Person record, or creates a MERGED_INTO relation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

from .founder_graph import PersonAsset, Status


class NameResolutionError(ValueError):
    """The local candidate request cannot be evaluated safely."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NameResolutionError(f"{field_name} must be a non-empty string")
    return value.strip()


def _pair(value: Sequence[object], field_name: str) -> tuple[str, str]:
    if isinstance(value, (str, bytes, bytearray)) or len(value) != 2:
        raise NameResolutionError(f"{field_name} must contain two person ids")
    first, second = _text(value[0], field_name), _text(value[1], field_name)
    if first == second:
        raise NameResolutionError(f"{field_name} must contain two different person ids")
    return tuple(sorted((first, second)))


def _name_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _email_key(contact: Mapping[str, str]) -> str | None:
    value = contact.get("email")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().casefold()


def _phone_key(contact: Mapping[str, str]) -> str | None:
    value = contact.get("phone")
    if not isinstance(value, str):
        return None
    digits = "".join(char for char in value if char.isdigit())
    return digits if len(digits) >= 7 else None


@dataclass(frozen=True, slots=True)
class NameResolutionCandidate:
    """A review-only pair; contact values are intentionally never exposed."""

    person_ids: tuple[str, str]
    reasons: tuple[str, ...]
    confidence: float
    status: str = "proposed"

    def __post_init__(self) -> None:
        object.__setattr__(self, "person_ids", _pair(self.person_ids, "person_ids"))
        allowed = {"same_name", "same_email", "same_phone"}
        reasons = tuple(dict.fromkeys(_text(reason, "reasons") for reason in self.reasons))
        if not reasons or not set(reasons).issubset(allowed):
            raise NameResolutionError("reasons must contain recognized local comparison labels")
        object.__setattr__(self, "reasons", reasons)
        if isinstance(self.confidence, bool):
            raise NameResolutionError("confidence must be a number between 0 and 1")
        confidence = float(self.confidence)
        if not isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise NameResolutionError("confidence must be a number between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        if self.status != "proposed":
            raise NameResolutionError("name resolution candidates must remain proposed")

    def as_dict(self) -> dict[str, object]:
        return {
            "person_ids": list(self.person_ids),
            "reasons": list(self.reasons),
            "confidence": self.confidence,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class NameResolutionEvaluation:
    """Deterministic synthetic benchmark results, not a merge result."""

    expected_pair_count: int
    found_pair_count: int
    top_3_recall: float
    automatic_merges: int = 0

    def __post_init__(self) -> None:
        if self.expected_pair_count < 0 or self.found_pair_count < 0:
            raise NameResolutionError("pair counts must not be negative")
        if self.found_pair_count > self.expected_pair_count:
            raise NameResolutionError("found pair count cannot exceed expected pair count")
        if self.expected_pair_count == 0:
            if self.top_3_recall != 1.0:
                raise NameResolutionError("an empty benchmark must have full recall")
        elif self.top_3_recall != self.found_pair_count / self.expected_pair_count:
            raise NameResolutionError("top_3_recall must match the pair counts")
        if self.automatic_merges != 0:
            raise NameResolutionError("candidate evaluation must not perform automatic merges")


def find_namesake_candidates(persons: Iterable[PersonAsset]) -> tuple[NameResolutionCandidate, ...]:
    """Return deterministic, active-owner candidate pairs without persisting anything."""

    values = tuple(persons)
    if not all(isinstance(person, PersonAsset) for person in values):
        raise NameResolutionError("persons must contain PersonAsset values")
    owners = {person.owner_id for person in values}
    if len(owners) > 1:
        raise NameResolutionError("persons must belong to one owner")
    active = tuple(person for person in values if person.status is Status.ACTIVE)
    if len({person.id for person in active}) != len(active):
        raise NameResolutionError("persons must have unique ids")

    by_name: dict[str, set[str]] = defaultdict(set)
    by_email: dict[str, set[str]] = defaultdict(set)
    by_phone: dict[str, set[str]] = defaultdict(set)
    for person in active:
        by_name[_name_key(person.name)].add(person.id)
        if email := _email_key(person.contact):
            by_email[email].add(person.id)
        if phone := _phone_key(person.contact):
            by_phone[phone].add(person.id)

    reasons_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    for reason, groups in (("same_name", by_name), ("same_email", by_email), ("same_phone", by_phone)):
        for ids in groups.values():
            ordered = sorted(ids)
            for index, first in enumerate(ordered):
                for second in ordered[index + 1:]:
                    reasons_by_pair[(first, second)].add(reason)

    weights = {"same_name": 0.55, "same_email": 0.40, "same_phone": 0.35}
    candidates = tuple(
        NameResolutionCandidate(
            person_ids=pair,
            reasons=tuple(sorted(reasons)),
            confidence=round(min(1.0, sum(weights[reason] for reason in reasons)), 2),
        )
        for pair, reasons in reasons_by_pair.items()
    )
    return tuple(sorted(candidates, key=lambda item: (-item.confidence, item.person_ids)))


def evaluate_top_3_candidates(
    persons: Iterable[PersonAsset],
    expected_pairs: Iterable[Sequence[object]],
) -> NameResolutionEvaluation:
    """Measure whether each expected synthetic pair appears in either top-three list."""

    candidates = find_namesake_candidates(persons)
    expected = {_pair(pair, "expected_pairs") for pair in expected_pairs}
    ranked: dict[str, list[NameResolutionCandidate]] = defaultdict(list)
    for candidate in candidates:
        for person_id in candidate.person_ids:
            ranked[person_id].append(candidate)
    visible = {
        candidate.person_ids
        for items in ranked.values()
        for candidate in items[:3]
    }
    found = len(expected & visible)
    return NameResolutionEvaluation(
        expected_pair_count=len(expected),
        found_pair_count=found,
        top_3_recall=1.0 if not expected else found / len(expected),
    )


__all__ = [
    "NameResolutionCandidate",
    "NameResolutionError",
    "NameResolutionEvaluation",
    "evaluate_top_3_candidates",
    "find_namesake_candidates",
]
