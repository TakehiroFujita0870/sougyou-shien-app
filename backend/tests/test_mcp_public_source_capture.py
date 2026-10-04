import pytest

from nebula.founder_graph import EgressPolicy
from nebula.founder_graph_mcp import McpReadError, McpReadSurface
from nebula.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from nebula.founder_graph_read import GraphReadService
from nebula.founder_graph_write import GraphWriteError, InMemoryGraphWriteService


def test_capture_source_defaults_private_and_allows_explicit_public_metadata() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    base = {
        "url": "https://example.test/a", "title": "Public title",
        "summary": "Owner supplied short citation", "idempotency_key": "source-local",
    }
    local = surface.call("capture_source", base, owner_id="owner-1")
    local_source = writes.get_node(local.target_id)
    local_revision = writes.get_node(local.source_revision_id)
    assert local_source.egress_policy is EgressPolicy.LOCAL_ONLY
    assert local_revision.egress_policy is EgressPolicy.LOCAL_ONLY

    mismatched_revision = local_revision.__class__(
        owner_id=local_revision.owner_id, id="mismatch-revision", source_id=local_source.id,
        content=local_revision.content, locator=local_revision.locator, revision=1,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    with pytest.raises(GraphWriteError, match="same supported egress policy"):
        writes.capture_source(local_source, mismatched_revision, idempotency_key="policy-mismatch")

    shared = surface.call("capture_source", {
        **base, "egress_policy": "shareable", "idempotency_key": "source-public",
    }, owner_id="owner-1")
    shared_source = writes.get_node(shared.target_id)
    shared_revision = writes.get_node(shared.source_revision_id)
    assert shared_source.egress_policy is EgressPolicy.SHAREABLE
    assert shared_revision.egress_policy is EgressPolicy.SHAREABLE
    assert shared_revision.content == "Owner supplied short citation"
    reader = McpReadSurface(GraphReadService(writes))
    projection = reader.call("fetch", {"id": shared_source.id}, owner_id="owner-1")
    assert projection["fields"]["title"] == "Public title"
    assert "Owner supplied short citation" not in str(projection)
    with pytest.raises(McpReadError):
        reader.call("fetch", {"id": local_source.id}, owner_id="owner-1")


def test_capture_source_rejects_credential_urls_even_when_shareable() -> None:
    surface = McpWriteSurface(InMemoryGraphWriteService("owner-1"))
    with pytest.raises(McpWriteError, match="without credentials"):
        surface.call("capture_source", {
            "url": "https://user:secret@example.test/a", "title": "Private", "summary": "safe",
            "egress_policy": "shareable", "idempotency_key": "credential-url",
        }, owner_id="owner-1")
