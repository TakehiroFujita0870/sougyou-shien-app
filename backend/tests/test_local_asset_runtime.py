"""Common Asset editing uses the fixed local owner and closes its connection."""

from types import SimpleNamespace

import pytest

from dots import local_dashboard_runtime as runtime


@pytest.mark.parametrize("fails", [False, True])
def test_asset_writer_opens_on_demand_and_closes_after_success_or_failure(monkeypatch, fails):
    events = []

    class Driver:
        def close(self):
            events.append("closed")

    def gateway(driver, owner):
        events.append(("owner", owner))
        return object()

    class Writer:
        def __init__(self, gateway):
            pass

        def save(self, asset_id, **arguments):
            events.append((asset_id, arguments))
            if fails:
                raise ValueError("invalid synthetic edit")
            return SimpleNamespace(target_id="successor", revision=2, replayed=False)

    monkeypatch.setattr(runtime, "create_neo4j_driver_from_env", lambda: events.append("opened") or Driver())
    monkeypatch.setattr(runtime, "Neo4jGraphGateway", gateway)
    monkeypatch.setattr(runtime, "LocalAssetWriter", Writer)
    writer = runtime.OnDemandAssetWriter()
    assert events == []
    arguments = dict(name="edited", description="synthetic", expected_revision=1,
                     idempotency_key="test-edit", home_category="criterion")
    if fails:
        with pytest.raises(ValueError, match="invalid synthetic edit"):
            writer.save("asset", **arguments)
    else:
        assert writer.save("asset", **arguments).target_id == "successor"
    assert events == ["opened", ("owner", "owner-mvp"), ("asset", arguments), "closed"]
