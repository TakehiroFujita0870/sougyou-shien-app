"""Provider-independent model catalog and adapter boundary.

The Founder Graph runtime addresses a model by a logical key.  Provider names
and provider model IDs are kept in this module so domain services do not need
to branch on a vendor string.  The default entry is deliberately unconfigured:
this slice never opens a network connection and never reads credentials.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol


LUNA_LOGICAL_KEY = "luna"
MODEL_CATALOG_VERSION = "founder-graph-v1"
LUNA_CAPABILITIES = (
    "extraction",
    "entity_resolution",
    "classification",
    "facet_generation",
    "relation_candidate",
    "query_expansion",
    "rerank",
)


class ModelCatalogError(ValueError):
    """Base class for invalid or unavailable catalog entries."""


class UnknownModelKeyError(ModelCatalogError):
    """The requested logical model key is absent from the catalog."""


class DisabledModelKeyError(ModelCatalogError):
    """The requested logical model key exists but is disabled."""


class NoDefaultModelError(ModelCatalogError):
    """The catalog has no enabled default entry."""


class NoModelForCapabilityError(ModelCatalogError):
    """No enabled catalog entry supports the requested capability."""


class ModelProviderError(RuntimeError):
    """Base class for provider-boundary failures."""


class ModelProviderUnavailable(ModelProviderError):
    """The catalog entry cannot be served by a configured local adapter."""


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelCatalogError(f"{field_name} must be a non-empty string")
    return value.strip()


def _string_tuple(values: Iterable[str] | str, field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    try:
        normalized = tuple(_required_text(value, field_name) for value in values)
    except TypeError as error:
        raise ModelCatalogError(f"{field_name} must be a sequence of strings") from error
    if len(set(normalized)) != len(normalized):
        raise ModelCatalogError(f"{field_name} must not contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    """Immutable model metadata required by the model lifecycle contract."""

    logical_key: str
    provider: str
    model_id: str
    plans: tuple[str, ...] = ()
    reasoning_modes: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    cost_class: str = "unconfigured"
    enabled: bool = True
    is_default: bool = False
    catalog_version: str = MODEL_CATALOG_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "logical_key", _required_text(self.logical_key, "logical_key"))
        object.__setattr__(self, "provider", _required_text(self.provider, "provider"))
        object.__setattr__(self, "model_id", _required_text(self.model_id, "model_id"))
        object.__setattr__(self, "plans", _string_tuple(self.plans, "plans"))
        object.__setattr__(self, "reasoning_modes", _string_tuple(self.reasoning_modes, "reasoning_modes"))
        object.__setattr__(self, "capabilities", _string_tuple(self.capabilities, "capabilities"))
        object.__setattr__(self, "cost_class", _required_text(self.cost_class, "cost_class"))
        object.__setattr__(self, "catalog_version", _required_text(self.catalog_version, "catalog_version"))
        if type(self.enabled) is not bool:
            raise ModelCatalogError("enabled must be a boolean")
        if type(self.is_default) is not bool:
            raise ModelCatalogError("is_default must be a boolean")
        if self.is_default and not self.enabled:
            raise ModelCatalogError("a disabled model cannot be the default")

    @property
    def snapshot(self) -> str:
        """Return the stable identity stored with generated graph values."""

        return f"{self.logical_key}@{self.catalog_version}"

    @property
    def model_snapshot(self) -> str:
        """Compatibility alias for provenance fields named ``model_snapshot``."""

        return self.snapshot

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-compatible catalog representation."""

        return {
            "logical_key": self.logical_key,
            "provider": self.provider,
            "model_id": self.model_id,
            "plans": list(self.plans),
            "reasoning_modes": list(self.reasoning_modes),
            "capabilities": list(self.capabilities),
            "cost_class": self.cost_class,
            "enabled": self.enabled,
            "is_default": self.is_default,
            "catalog_version": self.catalog_version,
            "snapshot": self.snapshot,
        }


class ModelCatalog:
    """Immutable lookup boundary for logical model metadata."""

    def __init__(self, entries: Iterable[ModelCatalogEntry]) -> None:
        normalized = tuple(entries)
        if not normalized:
            raise ModelCatalogError("model catalog must contain at least one entry")
        if not all(isinstance(entry, ModelCatalogEntry) for entry in normalized):
            raise ModelCatalogError("model catalog entries must be ModelCatalogEntry values")
        keys = tuple(entry.logical_key for entry in normalized)
        if len(set(keys)) != len(keys):
            raise ModelCatalogError("duplicate logical model key")
        self._entries = normalized
        self._by_key = MappingProxyType({entry.logical_key: entry for entry in normalized})

    @property
    def entries(self) -> tuple[ModelCatalogEntry, ...]:
        return self._entries

    def resolve(self, logical_key: str | None = None) -> ModelCatalogEntry:
        if logical_key is None:
            return self.default()
        key = _required_text(logical_key, "logical_key")
        entry = self._by_key.get(key)
        if entry is None:
            raise UnknownModelKeyError(f"unknown logical model key: {key}")
        if not entry.enabled:
            raise DisabledModelKeyError(f"disabled logical model key: {key}")
        return entry

    def default(self) -> ModelCatalogEntry:
        defaults = tuple(entry for entry in self._entries if entry.enabled and entry.is_default)
        if len(defaults) != 1:
            raise NoDefaultModelError("model catalog must have exactly one enabled default")
        return defaults[0]

    def for_capability(self, capability: str) -> ModelCatalogEntry:
        requested = _required_text(capability, "capability")
        candidates = tuple(
            entry for entry in self._entries if entry.enabled and requested in entry.capabilities
        )
        if not candidates:
            raise NoModelForCapabilityError(f"no enabled model supports capability: {requested}")
        return next((entry for entry in candidates if entry.is_default), candidates[0])

    def resolve_capability(self, capability: str) -> ModelCatalogEntry:
        """Named alias for callers that prefer capability-oriented wording."""

        return self.for_capability(capability)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Provider-neutral result shape for a local adapter."""

    text: str
    logical_key: str
    model_snapshot: str


class ModelProvider(Protocol):
    """Minimal provider adapter contract; implementations may be local fakes."""

    name: str

    def generate(self, *, model: ModelCatalogEntry, prompt: str) -> ModelResponse: ...


class UnconfiguredModelProvider:
    """Fail-closed adapter used until an explicitly approved provider is wired."""

    name = "unconfigured"

    def generate(self, *, model: ModelCatalogEntry, prompt: str) -> ModelResponse:
        del prompt
        raise ModelProviderUnavailable(
            f"model provider '{model.provider}' is not configured for logical model '{model.logical_key}'"
        )


@dataclass(frozen=True, slots=True)
class ModelBinding:
    """A resolved catalog entry and its explicitly registered provider adapter."""

    model: ModelCatalogEntry
    provider: ModelProvider

    @property
    def logical_key(self) -> str:
        return self.model.logical_key


class ModelProviderRegistry:
    """Resolve logical models and delegate to explicitly supplied adapters."""

    def __init__(
        self,
        catalog: ModelCatalog | None = None,
        providers: Mapping[str, ModelProvider] | Iterable[ModelProvider] | None = None,
    ) -> None:
        self.catalog = catalog or DEFAULT_MODEL_CATALOG
        if providers is None:
            registered: dict[str, ModelProvider] = {}
        elif isinstance(providers, Mapping):
            registered = dict(providers)
        else:
            registered = {provider.name: provider for provider in providers}
        if any(not isinstance(name, str) or not name.strip() for name in registered):
            raise ModelProviderError("provider names must be non-empty strings")
        self._providers = {"unconfigured": UnconfiguredModelProvider(), **registered}

    def binding_for(self, logical_key: str | None = None) -> ModelBinding:
        model = self.catalog.resolve(logical_key)
        provider = self._providers.get(model.provider)
        if provider is None:
            raise ModelProviderUnavailable(
                f"model provider '{model.provider}' is not configured for logical model '{model.logical_key}'"
            )
        return ModelBinding(model=model, provider=provider)

    def adapter_for(self, logical_key: str | None = None) -> ModelProvider:
        return self.binding_for(logical_key).provider

    def generate(self, logical_key: str | None = None, prompt: str = "") -> ModelResponse:
        binding = self.binding_for(logical_key)
        return binding.provider.generate(model=binding.model, prompt=prompt)


LUNA_MODEL = ModelCatalogEntry(
    logical_key=LUNA_LOGICAL_KEY,
    # The provider and model ID remain placeholders until a separately approved
    # provider decision.  Neither value is sent anywhere by this module.
    provider="unconfigured",
    model_id=LUNA_LOGICAL_KEY,
    capabilities=LUNA_CAPABILITIES,
    cost_class="unconfigured",
    is_default=True,
)

DEFAULT_MODEL_CATALOG = ModelCatalog((LUNA_MODEL,))


def create_model_provider_registry(
    *,
    catalog: ModelCatalog | None = None,
    providers: Mapping[str, ModelProvider] | Iterable[ModelProvider] | None = None,
) -> ModelProviderRegistry:
    """Build a registry while keeping provider injection explicit for callers."""

    return ModelProviderRegistry(catalog=catalog, providers=providers)
