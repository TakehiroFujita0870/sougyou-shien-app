"""Offline ports and deterministic adapters for external service parity."""

from dataclasses import dataclass
from enum import StrEnum
import os
from typing import Protocol


class RuntimeProfile(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class AuthPort(Protocol):
    def authenticate(self, owner_id: str | None) -> str: ...


class DatabasePort(Protocol):
    def read_object(self, owner_id: str, object_id: str) -> dict[str, str]: ...


class StoragePort(Protocol):
    def delete_object(self, owner_id: str, object_id: str) -> dict[str, str]: ...


class AiPort(Protocol):
    def generate(self, owner_id: str, prompt: str) -> dict[str, str]: ...


class WebSearchPort(Protocol):
    def search(self, owner_id: str, query: str) -> tuple[dict[str, str], ...]: ...


class BillingPort(Protocol):
    def consume(self, owner_id: str) -> dict[str, int]: ...


class RuntimeAdapter(AuthPort, DatabasePort, StoragePort, AiPort, WebSearchPort, BillingPort, Protocol):
    profile: RuntimeProfile

    def service_status(self) -> list[dict[str, str]]: ...


@dataclass(frozen=True)
class RuntimeFault(Exception):
    status_code: int
    code: str
    message: str


SERVICE_NAMES = ("auth", "db", "storage", "ai", "web_search", "billing")


class FakeRuntime:
    """A deterministic adapter; it never opens a network connection."""

    def __init__(self, profile: RuntimeProfile) -> None:
        self.profile = profile
        self._objects = {"sample-object": {"owner_id": "local-user", "state": "active"}}
        self._usage: dict[str, int] = {}

    def service_status(self) -> list[dict[str, str]]:
        return [{"service": name, "connection": "fake", "message": "deterministic local adapter"} for name in SERVICE_NAMES]

    def authenticate(self, owner_id: str | None) -> str:
        if not owner_id or not owner_id.strip():
            raise RuntimeFault(401, "authentication_required", "Sign in to continue.")
        return owner_id.strip()

    def read_object(self, owner_id: str, object_id: str) -> dict[str, str]:
        record = self._objects.get(object_id)
        if not record or record["state"] == "deleted":
            raise RuntimeFault(404, "resource_not_found", "The resource does not exist.")
        if record["owner_id"] != owner_id:
            raise RuntimeFault(403, "access_denied", "You do not have access to this resource.")
        return {"object_id": object_id, **record}

    def delete_object(self, owner_id: str, object_id: str) -> dict[str, str]:
        record = self.read_object(owner_id, object_id)
        record["state"] = "deleted"
        self._objects[object_id] = record
        return {"object_id": object_id, "state": "deleted"}

    def generate(self, owner_id: str, prompt: str) -> dict[str, str]:
        if "timeout" in prompt.lower():
            raise RuntimeFault(504, "service_timeout", "The service timed out. Please retry.")
        return {"owner_id": owner_id, "result": "fake response"}

    def search(self, owner_id: str, query: str) -> tuple[dict[str, str], ...]:
        return ({"owner_id": owner_id, "query": query, "source": "fake"},)

    def consume(self, owner_id: str) -> dict[str, int]:
        used = self._usage.get(owner_id, 0)
        if used >= 1:
            raise RuntimeFault(429, "usage_limit_exceeded", "Your local usage limit has been reached.")
        self._usage[owner_id] = used + 1
        return {"used": used + 1, "limit": 1}


class UnconfiguredRuntime:
    """Production placeholder that makes missing external configuration observable."""

    profile = RuntimeProfile.PRODUCTION

    def service_status(self) -> list[dict[str, str]]:
        return [{"service": name, "connection": "unconfigured", "message": "external connection is not configured"} for name in SERVICE_NAMES]

    def _unconfigured(self) -> None:
        raise RuntimeFault(503, "external_service_unconfigured", "This service is not configured yet.")

    def authenticate(self, owner_id: str | None) -> str:
        self._unconfigured()

    def read_object(self, owner_id: str, object_id: str) -> dict[str, str]:
        self._unconfigured()

    def delete_object(self, owner_id: str, object_id: str) -> dict[str, str]:
        self._unconfigured()

    def generate(self, owner_id: str, prompt: str) -> dict[str, str]:
        self._unconfigured()

    def search(self, owner_id: str, query: str) -> tuple[dict[str, str], ...]:
        self._unconfigured()

    def consume(self, owner_id: str) -> dict[str, int]:
        self._unconfigured()


def create_runtime(profile: RuntimeProfile | str | None = None) -> RuntimeAdapter:
    selected = RuntimeProfile(profile or os.getenv("KADODE_RUNTIME_PROFILE", RuntimeProfile.LOCAL))
    if selected is RuntimeProfile.PRODUCTION:
        return UnconfiguredRuntime()
    return FakeRuntime(selected)
