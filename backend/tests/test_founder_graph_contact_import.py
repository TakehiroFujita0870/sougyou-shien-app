from __future__ import annotations

import pytest

from dots.founder_graph import EgressPolicy, Organization, PersonAsset
from dots.founder_graph_contact_import import (
    MAX_CSV_BYTES,
    MAX_FIELD_LENGTH,
    ContactImportError,
    import_contacts,
    normalize_contact_csv,
    normalize_contact_input,
    normalize_contact_row,
)
from dots.founder_graph_mcp import McpReadSurface
from dots.founder_graph_mcp_write import McpWriteSurface
from dots.founder_graph_read import GraphReadService
from dots.founder_graph_write import InMemoryGraphWriteService


def test_mapping_row_produces_write_surface_payloads_without_relationships() -> None:
    record = normalize_contact_row(
        {
            "owner_id": "owner-1",
            "name": "A Founder",
            "company": "Example Inc.",
            "description": "Met at a founder event",
            "email": "founder@example.test",
            "phone": "+81-90-0000-0000",
            "private_notes": "Follow up after the prototype review.",
        },
        owner_id="owner-1",
    )

    assert record.relationships == ()
    assert record.person.owner_id == "owner-1"
    assert record.person.contact == {"email": "founder@example.test", "phone": "+81-90-0000-0000"}
    assert record.person.egress_policy is EgressPolicy.LOCAL_ONLY
    assert record.organization is not None
    assert record.organization.name == "Example Inc."
    assert record.organization.egress_policy is EgressPolicy.LOCAL_ONLY

    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    person_receipt = surface.call("capture_person", record.person.to_tool_arguments(), owner_id=record.person.owner_id)
    organization_receipt = surface.call(
        "capture_organization",
        record.organization.to_tool_arguments(),
        owner_id=record.organization.owner_id,
    )
    assert isinstance(writes.get_node(person_receipt.target_id), PersonAsset)
    assert isinstance(writes.get_node(organization_receipt.target_id), Organization)
    assert writes.relations() == ()


def test_csv_rows_are_bounded_and_support_contact_json() -> None:
    records = normalize_contact_csv(
        "owner_id,name,company,contact,private_notes\n"
        'owner-1,"CSV Founder","CSV Inc.","{""email"": ""csv@example.test""}",local\n',
        owner_id="owner-1",
    )

    assert len(records) == 1
    assert records[0].person.contact == {"email": "csv@example.test"}
    assert records[0].person.private_notes == "local"


def test_input_dispatch_accepts_one_mapping_or_csv() -> None:
    mapping = {"name": "One", "idempotency_key": "card-1"}

    assert len(normalize_contact_input(mapping, owner_id="owner-1")) == 1
    assert len(normalize_contact_input("name\nTwo\n", owner_id="owner-1")) == 1


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"owner_id": "owner-2", "name": "Cross owner"}, "owner_id"),
        ({"name": "../private"}, "path traversal"),
        ({"name": "Unknown", "unexpected": "value"}, "unknown"),
        ({"name": "Too long", "private_notes": "x" * (MAX_FIELD_LENGTH + 1)}, "exceeds"),
    ],
)
def test_mapping_rejects_cross_owner_path_unknown_and_oversized_rows(row: dict[str, str], message: str) -> None:
    with pytest.raises(ContactImportError, match=message):
        normalize_contact_row(row, owner_id="owner-1")


def test_contact_and_private_notes_cannot_be_shareable() -> None:
    with pytest.raises(ContactImportError, match="local_only"):
        normalize_contact_row(
            {"name": "Private", "contact": {"email": "p@example.test"}, "egress_policy": "shareable"},
            owner_id="owner-1",
        )


def test_csv_rejects_malformed_unknown_headers_and_oversized_input() -> None:
    with pytest.raises(ContactImportError, match="malformed CSV"):
        normalize_contact_csv('name,company\n"unterminated,Example\n', owner_id="owner-1")

    with pytest.raises(ContactImportError, match="unknown"):
        normalize_contact_csv("name,secret\nFounder,private\n", owner_id="owner-1")

    with pytest.raises(ContactImportError, match="CSV input exceeds"):
        normalize_contact_csv("name\n" + ("x" * MAX_CSV_BYTES), owner_id="owner-1")


def test_csv_rejects_ragged_rows_and_missing_name() -> None:
    with pytest.raises(ContactImportError, match="row width"):
        normalize_contact_csv("name,company\nFounder\n", owner_id="owner-1")

    with pytest.raises(ContactImportError, match="name"):
        normalize_contact_csv("name\n \n", owner_id="owner-1")


def test_idempotency_is_stable_and_organization_key_is_distinct() -> None:
    first = normalize_contact_row({"name": "Stable", "company": "Stable Inc."}, owner_id="owner-1")
    second = normalize_contact_row({"company": "Stable Inc.", "name": "Stable"}, owner_id="owner-1")

    assert first.person.idempotency_key == second.person.idempotency_key
    assert first.organization is not None
    assert second.organization is not None
    assert first.organization.idempotency_key == second.organization.idempotency_key
    assert first.person.idempotency_key != first.organization.idempotency_key


def test_import_contacts_persists_ten_synthetic_cards_without_relationships_or_shareable_contacts() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    cards = "name,company,email,phone,private_notes\n" + "\n".join(
        f"Founder {index},Company {index},founder-{index}@example.test,+81-90-0000-{index:04d},private {index}"
        for index in range(10)
    )

    receipts = import_contacts(cards, write_surface=surface)

    assert len(receipts) == 10
    assert writes.relations() == ()
    read_surface = McpReadSurface(GraphReadService(writes))
    assert read_surface.call("search", {"query": "Founder"}, owner_id="owner-1")["results"] == []
    for index, receipt in enumerate(receipts):
        person = writes.get_node(receipt.person.target_id)
        organization = writes.get_node(receipt.organization.target_id if receipt.organization else "")
        assert isinstance(person, PersonAsset)
        assert isinstance(organization, Organization)
        assert person.name == f"Founder {index}"
        assert person.contact == {
            "email": f"founder-{index}@example.test",
            "phone": f"+81-90-0000-{index:04d}",
        }
        assert person.egress_policy is EgressPolicy.LOCAL_ONLY


def test_import_contacts_validates_all_rows_before_saving_anything() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)

    with pytest.raises(ContactImportError, match="name"):
        import_contacts(
            [{"name": "First"}, {"name": " "}],
            write_surface=surface,
        )

    assert writes.get_node("person-capture_person") is None
    assert writes.audit_events() == ()


def test_import_contacts_can_retry_a_completed_batch_without_duplicate_nodes() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    source = "name,company,email\nRetry Person,Retry Inc.,retry@example.test\n"

    first = import_contacts(source, write_surface=surface)
    second = import_contacts(source, write_surface=surface)

    assert first[0].person.replayed is False
    assert first[0].organization is not None
    assert first[0].organization.replayed is False
    assert second[0].person.replayed is True
    assert second[0].organization is not None
    assert second[0].organization.replayed is True
    assert len(writes.audit_events()) == 2
