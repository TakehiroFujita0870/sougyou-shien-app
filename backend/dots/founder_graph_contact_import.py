"""Pure, local-only business-card and CSV contact normalization.

This module stops at a typed command payload.  It does not read files, call a
model or network, persist nodes, resolve names, or create relationships.  The
returned payloads can be passed directly to :class:`McpWriteSurface`'s
``capture_person`` and ``capture_organization`` commands.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from hashlib import sha256
import io
import json
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from urllib.parse import unquote

from .founder_graph import EgressPolicy, Organization, PersonAsset


MAX_ROWS = 500
MAX_CSV_BYTES = 1_048_576
MAX_FIELD_LENGTH = 4_096
MAX_NAME_LENGTH = 256
MAX_CONTACT_FIELDS = 16
MAX_CONTACT_KEY_LENGTH = 64
MAX_IDEMPOTENCY_KEY_LENGTH = 128

_BASE_FIELDS = frozenset(
    {
        "owner_id",
        "name",
        "company",
        "description",
        "company_description",
        "contact",
        "private_notes",
        "idempotency_key",
        "egress_policy",
    }
)
_FLAT_CONTACT_FIELDS = frozenset(
    {"email", "phone", "mobile", "tel", "website", "url", "linkedin", "twitter", "address"}
)
_CONTACT_PREFIX = "contact_"
_PATH_PREFIX = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{1,2})")
_SAFE_CONTACT_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SAFE_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class ContactImportError(ValueError):
    """Raised when a contact row or CSV input violates the local contract."""


def _reject_path_traversal(value: str, field_name: str) -> None:
    """Reject filesystem-looking traversal without rejecting ordinary URLs."""

    if "\x00" in value:
        raise ContactImportError(f"{field_name} contains a NUL character")
    candidate = value
    for _ in range(3):
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    if _PATH_PREFIX.match(candidate) or ".." in re.split(r"[\\/]", candidate):
        raise ContactImportError(f"{field_name} contains path traversal")


def _text(value: Any, field_name: str, *, required: bool = False, limit: int = MAX_FIELD_LENGTH) -> str:
    if value is None:
        if required:
            raise ContactImportError(f"{field_name} must be a non-empty string")
        return ""
    if not isinstance(value, str):
        raise ContactImportError(f"{field_name} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise ContactImportError(f"{field_name} must be a non-empty string")
    if len(normalized) > limit:
        raise ContactImportError(f"{field_name} exceeds the {limit}-character limit")
    _reject_path_traversal(normalized, field_name)
    return normalized


def _owner(value: Any, expected: str, *, field_name: str = "owner_id") -> str:
    normalized_expected = _text(expected, "owner_id", required=True, limit=MAX_CONTACT_KEY_LENGTH)
    if value is None or value == "":
        return normalized_expected
    normalized = _text(value, field_name, required=True, limit=MAX_CONTACT_KEY_LENGTH)
    if normalized != normalized_expected:
        raise ContactImportError("owner_id does not match the local owner")
    return normalized


def _canonical_key(value: Any) -> str:
    if not isinstance(value, str):
        raise ContactImportError("row keys must be strings")
    key = value.strip().removeprefix("\ufeff").casefold()
    if not key:
        raise ContactImportError("row keys must not be empty")
    return key


def _is_allowed_key(key: str) -> bool:
    return key in _BASE_FIELDS or key in _FLAT_CONTACT_FIELDS or key.startswith(_CONTACT_PREFIX)


def _normalize_row_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ContactImportError("each contact row must be an object")
    normalized: dict[str, Any] = {}
    for raw_key, value in row.items():
        key = _canonical_key(raw_key)
        if not _is_allowed_key(key):
            raise ContactImportError(f"unknown contact field: {key}")
        if key in normalized:
            raise ContactImportError(f"duplicate contact field: {key}")
        normalized[key] = value
    return normalized


def _contact_key(value: Any) -> str:
    if not isinstance(value, str):
        raise ContactImportError("contact keys must be strings")
    key = value.strip().casefold()
    if not key or len(key) > MAX_CONTACT_KEY_LENGTH or not _SAFE_CONTACT_KEY.fullmatch(key):
        raise ContactImportError("contact keys must use short safe names")
    _reject_path_traversal(key, "contact key")
    return key


def _normalize_contact_value(value: Any, field_name: str) -> str:
    return _text(value, field_name, limit=MAX_FIELD_LENGTH)


def _normalize_contact(value: Any, flattened: Mapping[str, Any]) -> Mapping[str, str]:
    values: dict[str, str] = {}
    if value not in (None, ""):
        if isinstance(value, str):
            if len(value) > MAX_FIELD_LENGTH:
                raise ContactImportError("contact exceeds the field-size limit")
            try:
                value = json.loads(value)
            except (TypeError, ValueError) as error:
                raise ContactImportError("contact must be an object or JSON object") from error
        if not isinstance(value, Mapping):
            raise ContactImportError("contact must be an object or JSON object")
        for raw_key, raw_value in value.items():
            key = _contact_key(raw_key)
            normalized_value = _normalize_contact_value(raw_value, f"contact.{key}")
            if not normalized_value:
                continue
            values[key] = normalized_value

    for raw_key, raw_value in flattened.items():
        if raw_value in (None, ""):
            continue
        key = raw_key.removeprefix(_CONTACT_PREFIX) if raw_key.startswith(_CONTACT_PREFIX) else raw_key
        key = _contact_key(key)
        normalized_value = _normalize_contact_value(raw_value, f"contact.{key}")
        if normalized_value:
            values[key] = normalized_value
    if len(values) > MAX_CONTACT_FIELDS:
        raise ContactImportError(f"contact cannot contain more than {MAX_CONTACT_FIELDS} fields")
    return MappingProxyType(dict(sorted(values.items())))


def _idempotency_key(value: Any, *, derived: str | None = None) -> str:
    if value in (None, ""):
        if derived is None:
            raise ContactImportError("idempotency_key cannot be derived")
        return derived
    normalized = _text(value, "idempotency_key", required=True, limit=MAX_IDEMPOTENCY_KEY_LENGTH)
    if not _SAFE_IDEMPOTENCY_KEY.fullmatch(normalized):
        raise ContactImportError("idempotency_key contains unsupported characters")
    return normalized


def _derived_keys(
    *,
    owner_id: str,
    name: str,
    company: str,
    description: str,
    company_description: str,
    contact: Mapping[str, str],
    private_notes: str,
    explicit: Any,
) -> tuple[str, str]:
    canonical = json.dumps(
        {
            "owner_id": owner_id,
            "name": name,
            "company": company,
            "description": description,
            "company_description": company_description,
            "contact": dict(contact),
            "private_notes": private_notes,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()[:32]
    if explicit not in (None, ""):
        person_key = _idempotency_key(explicit)
        organization_key = f"{person_key}:org"
        if len(organization_key) > MAX_IDEMPOTENCY_KEY_LENGTH or not _SAFE_IDEMPOTENCY_KEY.fullmatch(organization_key):
            organization_key = f"contact-org-{sha256(person_key.encode('utf-8')).hexdigest()[:32]}"
        return person_key, organization_key
    return f"contact-person-{digest}", f"contact-org-{digest}"


def _tool_arguments(*, name: str, description: str, contact: Mapping[str, str], private_notes: str, key: str) -> dict[str, object]:
    return {
        "name": name,
        "description": description,
        "contact": dict(contact),
        "private_notes": private_notes,
        "egress_policy": EgressPolicy.LOCAL_ONLY.value,
        "idempotency_key": key,
    }


@dataclass(frozen=True, slots=True)
class PersonCapturePayload:
    """Typed arguments for the existing ``capture_person`` write command."""

    owner_id: str
    name: str
    description: str = ""
    contact: Mapping[str, str] = field(default_factory=dict)
    private_notes: str = ""
    idempotency_key: str = ""
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id", required=True, limit=MAX_CONTACT_KEY_LENGTH))
        object.__setattr__(self, "name", _text(self.name, "name", required=True, limit=MAX_NAME_LENGTH))
        object.__setattr__(self, "description", _text(self.description, "description"))
        object.__setattr__(self, "private_notes", _text(self.private_notes, "private_notes"))
        normalized_contact = _normalize_contact(self.contact, {})
        object.__setattr__(self, "contact", normalized_contact)
        key = _idempotency_key(self.idempotency_key)
        object.__setattr__(self, "idempotency_key", key)
        try:
            policy = self.egress_policy if isinstance(self.egress_policy, EgressPolicy) else EgressPolicy(self.egress_policy)
        except (TypeError, ValueError) as error:
            raise ContactImportError("egress_policy must be local_only") from error
        if policy is not EgressPolicy.LOCAL_ONLY:
            raise ContactImportError("person contact/private_notes require local_only egress_policy")
        object.__setattr__(self, "egress_policy", policy)

    @property
    def tool_name(self) -> str:
        return "capture_person"

    def to_tool_arguments(self) -> dict[str, object]:
        return _tool_arguments(
            name=self.name,
            description=self.description,
            contact=self.contact,
            private_notes=self.private_notes,
            key=self.idempotency_key,
        )

    def to_domain(self) -> PersonAsset:
        return PersonAsset(
            owner_id=self.owner_id,
            name=self.name,
            description=self.description,
            contact=self.contact,
            private_notes=self.private_notes,
            egress_policy=self.egress_policy,
        )


@dataclass(frozen=True, slots=True)
class OrganizationCapturePayload:
    """Typed arguments for the existing ``capture_organization`` command."""

    owner_id: str
    name: str
    description: str = ""
    idempotency_key: str = ""
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id", required=True, limit=MAX_CONTACT_KEY_LENGTH))
        object.__setattr__(self, "name", _text(self.name, "company", required=True, limit=MAX_NAME_LENGTH))
        object.__setattr__(self, "description", _text(self.description, "company_description"))
        object.__setattr__(self, "idempotency_key", _idempotency_key(self.idempotency_key))
        try:
            policy = self.egress_policy if isinstance(self.egress_policy, EgressPolicy) else EgressPolicy(self.egress_policy)
        except (TypeError, ValueError) as error:
            raise ContactImportError("egress_policy must be a valid policy") from error
        object.__setattr__(self, "egress_policy", policy)

    @property
    def tool_name(self) -> str:
        return "capture_organization"

    def to_tool_arguments(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "egress_policy": self.egress_policy.value,
            "idempotency_key": self.idempotency_key,
        }

    def to_domain(self) -> Organization:
        return Organization(
            owner_id=self.owner_id,
            name=self.name,
            description=self.description,
            egress_policy=self.egress_policy,
        )


@dataclass(frozen=True, slots=True)
class ContactCaptureRecord:
    """The independent person and optional company commands for one row."""

    person: PersonCapturePayload
    organization: OrganizationCapturePayload | None = None

    @property
    def relationships(self) -> tuple[()]:
        """Contact intake never infers or creates graph relationships."""

        return ()


PersonAssetCapturePayload = PersonCapturePayload
OrganizationAssetCapturePayload = OrganizationCapturePayload


def normalize_contact_row(row: Mapping[str, Any], *, owner_id: str) -> ContactCaptureRecord:
    """Normalize one mapping into write-surface payloads without side effects."""

    normalized = _normalize_row_mapping(row)
    expected_owner = _owner(owner_id, owner_id)
    row_owner = _owner(normalized.get("owner_id"), expected_owner)
    name = _text(normalized.get("name"), "name", required=True, limit=MAX_NAME_LENGTH)
    company = _text(normalized.get("company"), "company", limit=MAX_NAME_LENGTH)
    description = _text(normalized.get("description"), "description")
    company_description = _text(normalized.get("company_description"), "company_description")
    private_notes = _text(normalized.get("private_notes"), "private_notes")
    raw_policy = normalized.get("egress_policy", EgressPolicy.LOCAL_ONLY.value)
    try:
        policy = EgressPolicy(raw_policy)
    except (TypeError, ValueError) as error:
        raise ContactImportError("egress_policy must be local_only") from error
    if policy is not EgressPolicy.LOCAL_ONLY:
        raise ContactImportError("person contact/private_notes require local_only egress_policy")
    flattened = {
        key: value
        for key, value in normalized.items()
        if key in _FLAT_CONTACT_FIELDS or key.startswith(_CONTACT_PREFIX)
    }
    contact = _normalize_contact(normalized.get("contact"), flattened)
    person_key, organization_key = _derived_keys(
        owner_id=row_owner,
        name=name,
        company=company,
        description=description,
        company_description=company_description,
        contact=contact,
        private_notes=private_notes,
        explicit=normalized.get("idempotency_key"),
    )
    person = PersonCapturePayload(
        owner_id=row_owner,
        name=name,
        description=description,
        contact=contact,
        private_notes=private_notes,
        idempotency_key=person_key,
        egress_policy=EgressPolicy.LOCAL_ONLY,
    )
    organization = (
        OrganizationCapturePayload(
            owner_id=row_owner,
            name=company,
            description=company_description,
            idempotency_key=organization_key,
            egress_policy=EgressPolicy.LOCAL_ONLY,
        )
        if company
        else None
    )
    return ContactCaptureRecord(person=person, organization=organization)


def normalize_contact_rows(rows: Iterable[Mapping[str, Any]] | Mapping[str, Any], *, owner_id: str) -> tuple[ContactCaptureRecord, ...]:
    """Normalize a bounded iterable of row mappings."""

    if isinstance(rows, Mapping):
        rows = (rows,)
    if isinstance(rows, (str, bytes, bytearray)):
        raise ContactImportError("rows must be mappings, not text")
    try:
        iterator = iter(rows)
    except TypeError as error:
        raise ContactImportError("rows must be an iterable of mappings") from error
    result: list[ContactCaptureRecord] = []
    for index, row in enumerate(iterator):
        if index >= MAX_ROWS:
            raise ContactImportError(f"contact import cannot contain more than {MAX_ROWS} rows")
        result.append(normalize_contact_row(row, owner_id=owner_id))
    return tuple(result)


def normalize_contact_csv(csv_text: str, *, owner_id: str) -> tuple[ContactCaptureRecord, ...]:
    """Parse and normalize bounded CSV text without opening a path or file."""

    if not isinstance(csv_text, str):
        raise ContactImportError("CSV input must be text")
    try:
        encoded_size = len(csv_text.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ContactImportError("CSV input must be valid UTF-8 text") from error
    if encoded_size > MAX_CSV_BYTES:
        raise ContactImportError(f"CSV input exceeds the {MAX_CSV_BYTES}-byte limit")
    if not csv_text.strip():
        raise ContactImportError("CSV input must not be empty")

    previous_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_FIELD_LENGTH)
    try:
        try:
            reader = csv.reader(io.StringIO(csv_text, newline=""), strict=True)
            raw_headers = next(reader)
            headers = [_canonical_key(header) for header in raw_headers]
            if not headers or any(not header for header in headers):
                raise ContactImportError("CSV header must not be empty")
            if len(set(headers)) != len(headers):
                raise ContactImportError("CSV header contains duplicate fields")
            if any(not _is_allowed_key(header) for header in headers):
                unknown = next(header for header in headers if not _is_allowed_key(header))
                raise ContactImportError(f"unknown contact field: {unknown}")
            rows: list[Mapping[str, Any]] = []
            for index, values in enumerate(reader):
                if index >= MAX_ROWS:
                    raise ContactImportError(f"contact import cannot contain more than {MAX_ROWS} rows")
                if len(values) != len(headers):
                    raise ContactImportError("CSV row width does not match the header")
                rows.append(dict(zip(headers, values)))
        except ContactImportError:
            raise
        except (csv.Error, StopIteration) as error:
            raise ContactImportError("malformed CSV") from error
    finally:
        csv.field_size_limit(previous_limit)
    return normalize_contact_rows(rows, owner_id=owner_id)


def normalize_contact_input(
    source: str | Mapping[str, Any] | Iterable[Mapping[str, Any]], *, owner_id: str
) -> tuple[ContactCaptureRecord, ...]:
    """Dispatch CSV text, one mapping, or a bounded mapping iterable."""

    if isinstance(source, str):
        return normalize_contact_csv(source, owner_id=owner_id)
    return normalize_contact_rows(source, owner_id=owner_id)
