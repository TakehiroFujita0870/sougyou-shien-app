import pytest

from dots.founder_graph import (
    DomainValidationError,
    NodeType,
    RelationAssertion,
    RelationType,
)


def make_assertion(**overrides: object) -> RelationAssertion:
    values: dict[str, object] = {
        "owner_id": "owner-1",
        "source_id": "idea-1",
        "source_kind": NodeType.IDEA,
        "target_id": "asset-1",
        "target_kind": NodeType.ASSET,
        "predicate": RelationType.REUSES,
        "assertion_family_id": "family-1",
    }
    values.update(overrides)
    return RelationAssertion(**values)  # type: ignore[arg-type]


def test_relation_assertion_without_brief_reference_remains_legacy_compatible() -> None:
    assertion = make_assertion()

    assert assertion.based_on_brief_id is None
    assert assertion.based_on_brief_section_index is None


@pytest.mark.parametrize("section_index", [0, 7])
def test_relation_assertion_accepts_brief_and_valid_section(section_index: int) -> None:
    assertion = make_assertion(
        based_on_brief_id="brief-1",
        based_on_brief_section_index=section_index,
    )

    assert assertion.based_on_brief_id == "brief-1"
    assert assertion.based_on_brief_section_index == section_index


def test_relation_assertion_normalizes_brief_identifier() -> None:
    assertion = make_assertion(
        based_on_brief_id=" brief-1 ",
        based_on_brief_section_index=3,
    )

    assert assertion.based_on_brief_id == "brief-1"


@pytest.mark.parametrize(
    "reference",
    [
        {"based_on_brief_id": "brief-1"},
        {"based_on_brief_section_index": 2},
    ],
)
def test_relation_assertion_requires_brief_reference_pair(reference: dict[str, object]) -> None:
    with pytest.raises(DomainValidationError, match="must be provided together"):
        make_assertion(**reference)


@pytest.mark.parametrize("section_index", [True, False, -1, 8])
def test_relation_assertion_rejects_invalid_brief_section_index(section_index: object) -> None:
    with pytest.raises(DomainValidationError, match="section index must be an integer from 0 to 7"):
        make_assertion(
            based_on_brief_id="brief-1",
            based_on_brief_section_index=section_index,
        )


@pytest.mark.parametrize("brief_id", ["", "   ", 12])
def test_relation_assertion_rejects_invalid_brief_identifier(brief_id: object) -> None:
    with pytest.raises(DomainValidationError, match="based_on_brief_id must be a non-empty string"):
        make_assertion(based_on_brief_id=brief_id, based_on_brief_section_index=0)
