from __future__ import annotations

from dataclasses import fields, replace
import json

import pytest

from dots.founder_graph import DomainValidationError
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_neo4j_read import _decode_assertion
from test_founder_graph_relation_assertion_write import _setup


def test_relation_assertion_stores_unicode_quote_offsets_without_quote_text() -> None:
    _writes, _idea, _claim, _evidence, _brief, assertion = _setup()
    markdown = "## 事業概要\n\n創業支援の構想を記録する"
    quote = "創業支援の構想"
    quote_start = markdown.index(quote)
    quote_end = quote_start + len(quote)
    located = replace(
        assertion,
        based_on_brief_revision=1,
        based_on_brief_quote_start=quote_start,
        based_on_brief_quote_end=quote_end,
    )

    payload = json.loads(_node_properties(located)["payload_json"])

    assert payload["based_on_brief_id"] == "brief-relation"
    assert payload["based_on_brief_section_index"] == 1
    assert payload["based_on_brief_revision"] == 1
    assert payload["based_on_brief_quote_start"] == quote_start
    assert payload["based_on_brief_quote_end"] == quote_end
    assert not {"quote", "support_quote", "excerpt"}.intersection(payload)
    assert not {"quote", "support_quote", "excerpt"}.intersection(
        field.name for field in fields(located)
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"based_on_brief_quote_start": 1},
        {"based_on_brief_quote_start": True, "based_on_brief_quote_end": 3},
        {"based_on_brief_quote_start": -1, "based_on_brief_quote_end": 3},
        {"based_on_brief_quote_start": 3, "based_on_brief_quote_end": 3},
        {"based_on_brief_revision": True},
        {"based_on_brief_revision": 0},
    ],
)
def test_relation_assertion_rejects_malformed_brief_locators(changes: dict[str, object]) -> None:
    _writes, _idea, _claim, _evidence, _brief, assertion = _setup()

    with pytest.raises(DomainValidationError):
        replace(assertion, **changes)


def test_section_locator_can_include_revision_without_quote_offsets() -> None:
    _writes, _idea, _claim, _evidence, _brief, assertion = _setup()

    located = replace(assertion, based_on_brief_revision=1)

    assert located.based_on_brief_revision == 1
    assert located.based_on_brief_quote_start is None
    assert located.based_on_brief_quote_end is None


def test_old_relation_assertion_payloads_decode_without_locator_fields() -> None:
    _writes, _idea, _claim, _evidence, _brief, assertion = _setup()
    payload = json.loads(_node_properties(assertion)["payload_json"])
    for field_name in (
        "based_on_brief_revision",
        "based_on_brief_quote_start",
        "based_on_brief_quote_end",
    ):
        payload.pop(field_name, None)
    encoded = json.dumps(payload, ensure_ascii=False)
    read_row = {
        "assertion_payload_json": encoded,
        "assertion_id": assertion.id,
        "assertion_owner_id": assertion.owner_id,
        "assertion_node_type": "relation_assertion",
        "assertion_revision": assertion.revision,
        "assertion_status": assertion.status.value,
        "assertion_egress_policy": assertion.egress_policy.value,
    }
    write_record = {
        "id": assertion.id,
        "owner_id": assertion.owner_id,
        "node_type": "relation_assertion",
        "revision": assertion.revision,
        "status": assertion.status.value,
        "assertion_family_id": assertion.assertion_family_id,
        "supersedes_id": assertion.supersedes_id,
        "payload_json": encoded,
    }

    read_decoded = _decode_assertion(read_row, owner_id=assertion.owner_id)
    write_decoded = Neo4jGraphGateway(object(), assertion.owner_id)._decode_relation_assertion_record(write_record)

    for decoded in (read_decoded, write_decoded):
        assert decoded.id == assertion.id
        assert decoded.based_on_brief_id == assertion.based_on_brief_id
        assert decoded.based_on_brief_section_index == assertion.based_on_brief_section_index
        assert decoded.based_on_brief_revision is None
        assert decoded.based_on_brief_quote_start is None
        assert decoded.based_on_brief_quote_end is None
