import pytest

from dots.model_catalog import (
    DEFAULT_MODEL_CATALOG,
    LUNA_LOGICAL_KEY,
    ModelCatalog,
    ModelCatalogEntry,
    ModelCatalogError,
    ModelProviderRegistry,
    ModelProviderUnavailable,
    ModelResponse,
)


def test_default_catalog_resolves_luna_and_exposes_lifecycle_fields() -> None:
    model = DEFAULT_MODEL_CATALOG.resolve(LUNA_LOGICAL_KEY)

    assert model.logical_key == "luna"
    assert model.provider == "unconfigured"
    assert model.model_id == "luna"
    assert model.plans == ()
    assert "entity_resolution" in model.capabilities
    assert "embedding" not in model.capabilities
    assert model.enabled is True
    assert model.is_default is True
    assert model.snapshot == "luna@founder-graph-v1"
    assert model.as_dict()["logical_key"] == "luna"


def test_catalog_resolves_default_when_no_logical_key_is_given() -> None:
    assert DEFAULT_MODEL_CATALOG.resolve().logical_key == LUNA_LOGICAL_KEY


def test_unknown_and_disabled_logical_keys_raise_typed_catalog_errors() -> None:
    disabled = ModelCatalogEntry(
        logical_key="disabled",
        provider="test",
        model_id="disabled-model",
        enabled=False,
    )
    catalog = ModelCatalog((disabled,))

    with pytest.raises(ModelCatalogError, match="unknown logical model key"):
        catalog.resolve("missing")
    with pytest.raises(ModelCatalogError, match="disabled logical model key"):
        catalog.resolve("disabled")


def test_registry_uses_an_explicit_adapter_without_external_calls() -> None:
    class RecordingProvider:
        name = "test"

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def generate(self, *, model: ModelCatalogEntry, prompt: str) -> ModelResponse:
            self.calls.append((model.logical_key, model.model_id, prompt))
            return ModelResponse(
                text="local result",
                logical_key=model.logical_key,
                model_snapshot=model.snapshot,
            )

    model = ModelCatalogEntry(
        logical_key="test-model",
        provider="test",
        model_id="test-model-v1",
        capabilities=("rerank",),
        is_default=True,
    )
    provider = RecordingProvider()
    registry = ModelProviderRegistry(ModelCatalog((model,)), providers={"test": provider})

    result = registry.generate(prompt="rank these", logical_key="test-model")

    assert result == ModelResponse(
        text="local result",
        logical_key="test-model",
        model_snapshot="test-model@founder-graph-v1",
    )
    assert provider.calls == [("test-model", "test-model-v1", "rank these")]


def test_default_registry_fails_closed_when_luna_provider_is_unconfigured() -> None:
    registry = ModelProviderRegistry()

    with pytest.raises(ModelProviderUnavailable, match="not configured"):
        registry.generate(prompt="extract an idea")


def test_registry_reports_missing_provider_without_falling_back() -> None:
    model = ModelCatalogEntry(
        logical_key="missing-provider",
        provider="missing",
        model_id="missing-model",
        is_default=True,
    )
    registry = ModelProviderRegistry(ModelCatalog((model,)))

    with pytest.raises(ModelProviderUnavailable, match="missing"):
        registry.adapter_for("missing-provider")


def test_catalog_rejects_duplicate_logical_keys() -> None:
    model = ModelCatalogEntry(logical_key="duplicate", provider="test", model_id="one")

    with pytest.raises(ModelCatalogError, match="duplicate logical model key"):
        ModelCatalog((model, model))
