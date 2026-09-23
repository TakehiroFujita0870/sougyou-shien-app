from __future__ import annotations

import pytest

from dots.founder_graph import PersonAsset, Status
from dots.founder_graph_name_resolution import (
    NameResolutionError,
    evaluate_top_3_candidates,
    find_namesake_candidates,
)


def _person(identifier: str, name: str, *, email: str = "", phone: str = "", status: Status = Status.ACTIVE) -> PersonAsset:
    contact = {key: value for key, value in {"email": email, "phone": phone}.items() if value}
    return PersonAsset(owner_id="synthetic-owner", id=identifier, name=name, contact=contact, status=status)


def test_candidates_are_local_review_pairs_without_contact_values_or_writes() -> None:
    candidates = find_namesake_candidates(
        (
            _person("person-a", "Aki Ito", email="aki@example.test"),
            _person("person-b", " aki  ito ", email="AKI@example.test"),
            _person("person-c", "Aki Ito"),
        )
    )

    first = candidates[0]
    assert first.person_ids == ("person-a", "person-b")
    assert first.reasons == ("same_email", "same_name")
    assert first.confidence == 0.95
    assert all(candidate.status == "proposed" for candidate in candidates)
    assert "aki@example.test" not in str([candidate.as_dict() for candidate in candidates])
    assert "MERGED_INTO" not in str([candidate.as_dict() for candidate in candidates])


def test_synthetic_benchmark_meets_top_three_target_with_zero_automatic_merges() -> None:
    people = (
        _person("person-a", "Aki Ito", email="aki@example.test"),
        _person("person-b", "Aki Ito", email="AKI@example.test"),
        _person("person-c", "Ken Sato", phone="+81-90-0000-0001"),
        _person("person-d", " ken  sato ", phone="819000000001"),
        _person("person-e", "Ken Sato"),
    )

    result = evaluate_top_3_candidates(people, (("person-a", "person-b"), ("person-c", "person-d")))

    assert result.expected_pair_count == 2
    assert result.found_pair_count == 2
    assert result.top_3_recall >= 0.90
    assert result.automatic_merges == 0


def test_archived_people_and_cross_owner_inputs_are_not_merged_or_compared() -> None:
    archived = _person("person-archived", "Aki Ito", email="aki@example.test", status=Status.ARCHIVED)
    active = _person("person-active", "Aki Ito", email="aki@example.test")

    assert find_namesake_candidates((archived, active)) == ()
    with pytest.raises(NameResolutionError, match="one owner"):
        find_namesake_candidates((active, PersonAsset(owner_id="other-owner", id="person-other", name="Aki Ito")))


def test_invalid_expected_pairs_fail_closed() -> None:
    person = _person("person-a", "Aki Ito")

    with pytest.raises(NameResolutionError, match="two different"):
        evaluate_top_3_candidates((person,), (("person-a", "person-a"),))
