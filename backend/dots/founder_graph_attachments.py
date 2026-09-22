"""Local, content-addressed attachment storage for the Founder Graph.

Only digest-derived names are used below the explicitly supplied root. A
per-root in-process lock and a portable advisory file lock serialize
cooperating store instances. POSIX reads use openat/O_NOFOLLOW and fstat where
available; Windows checks symlinks and reparse-point attributes before and
after each operation.

The threat model covers untrusted caller input and path traversal. These are
filesystem safety checks, not a kernel capability boundary: a hostile,
non-cooperating process already controlling the same Windows account can
still race a path between checks, and that case is explicitly out of scope.
The caller must keep the root private. On POSIX the descriptor-based read and
mutation paths close the corresponding symlink race. Windows ACLs and
reparse-point hardening remain an operational responsibility.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import errno
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from threading import RLock
from types import MappingProxyType
from typing import Any, Iterator, Mapping, TypeAlias
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows.
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX.
    msvcrt = None  # type: ignore[assignment]


_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_JsonValue: TypeAlias = None | bool | int | float | str | list[Any] | dict[str, Any]
_REPARSE_POINT = 0x0400
_PROCESS_LOCKS: dict[str, RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()
_POSIX_OPENAT = (
    os.name != "nt"
    and hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
    and os.open in getattr(os, "supports_dir_fd", ())
)


class AttachmentStoreError(Exception):
    """Base class for attachment-store failures."""


class AttachmentMissingError(FileNotFoundError, AttachmentStoreError):
    """The requested attachment or source file does not exist."""


class AttachmentIntegrityError(AttachmentStoreError):
    """Stored bytes or metadata do not match their content-addressed identity."""


class AttachmentSecurityError(AttachmentStoreError):
    """A symlink, reparse point, non-directory, or unsafe path was detected."""


class AttachmentDeletedError(AttachmentStoreError):
    """The attachment has a tombstone and is not available for normal reads."""


class AttachmentMetadataError(AttachmentStoreError):
    """A metadata sidecar or transaction journal is invalid."""


AttachmentNotFoundError = AttachmentMissingError
CorruptAttachmentError = AttachmentIntegrityError


def compute_content_hash(content: bytes | bytearray | memoryview) -> str:
    """Return the canonical SHA-256 identity for a bytes-like value."""

    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise TypeError("content must be bytes-like")
    return sha256(bytes(content)).hexdigest()


content_hash = compute_content_hash


def _raise_type(message: str) -> Any:
    raise TypeError(message)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            return _raise_type("metadata keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze_json(item) for item in value), key=repr))
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return _raise_type("metadata must contain finite JSON-like values")


def _thaw_json(value: Any) -> _JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _text(value: str | None, name: str, *, basename: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty NUL-free string")
    if basename and (value in {".", ".."} or "/" in value or "\\" in value):
        raise ValueError(f"{name} must be a file name, not a path")
    return value


def _digest(value: str | "AttachmentMetadata") -> str:
    if isinstance(value, AttachmentMetadata):
        value = value.content_hash
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise ValueError("content_hash must be a 64-character SHA-256 hexadecimal string")
    return value.lower()


def _reference(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("reference_id must be a non-empty NUL-free string")
    return value


@dataclass(frozen=True, slots=True)
class AttachmentMetadata:
    """Immutable metadata; storage paths are strings, never writable Path objects."""

    content_hash: str
    size: int
    storage_path: str
    filename: str | None = None
    mime_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    deleted: bool = False
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_hash", _digest(self.content_hash))
        if not isinstance(self.size, int) or isinstance(self.size, bool) or self.size < 0:
            raise ValueError("size must be a non-negative integer")
        if not isinstance(self.storage_path, str) or not self.storage_path:
            raise ValueError("storage_path must be a non-empty string")
        object.__setattr__(self, "filename", _text(self.filename, "filename", basename=True))
        object.__setattr__(self, "mime_type", _text(self.mime_type, "mime_type"))
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))
        object.__setattr__(self, "references", tuple(sorted({_reference(item) for item in self.references})))
        if not isinstance(self.deleted, bool):
            raise TypeError("deleted must be a boolean")

    @property
    def hash(self) -> str:
        return self.content_hash

    @property
    def path(self) -> str:
        """Compatibility alias returning a relative string, never a Path."""

        return self.storage_path

    @property
    def mime(self) -> str | None:
        return self.mime_type

    @property
    def media_type(self) -> str | None:
        return self.mime_type

    @property
    def reference_count(self) -> int:
        return len(self.references)

    @property
    def is_deleted(self) -> bool:
        return self.deleted


@dataclass(frozen=True, slots=True)
class _Record:
    content_hash: str
    size: int
    filename: str | None
    mime_type: str | None
    metadata: Mapping[str, Any]
    deleted: bool
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ObjectInfo:
    size: int
    digest: str
    data: bytes


class AttachmentStore:
    """A private local attachment store with journaled commits and tombstones."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        if root is None:
            raise TypeError("root is required")
        try:
            candidate = Path(os.path.abspath(root))
        except TypeError as error:
            raise TypeError("root must be a filesystem path") from error
        if _linkish(candidate):
            raise AttachmentSecurityError("storage root must not be a symlink or reparse point")
        self._root = candidate
        if not candidate.exists():
            self._ensure_dir(candidate)
        elif not candidate.is_dir():
            raise NotADirectoryError(str(candidate))
        self._objects = self._root / "objects"
        self._metadata = self._root / "metadata"
        self._transactions = self._root / "transactions"
        self._quarantine = self._root / "quarantine"
        self._lock_path = self._root / ".store.lock"
        with _PROCESS_LOCKS_GUARD:
            key = str(self._root).casefold() if os.name == "nt" else str(self._root)
            self._thread_lock = _PROCESS_LOCKS.setdefault(key, RLock())
        for directory in (self._root, self._objects, self._metadata, self._transactions, self._quarantine):
            self._ensure_dir(directory)
        with self._thread_lock, self._advisory_lock():
            self._recover_locked()

    @property
    def root(self) -> str:
        return str(self._root)

    def path_for(self, content_hash: str | AttachmentMetadata) -> str:
        """Return a safe relative storage path, not a writable filesystem object."""

        digest = _digest(content_hash)
        with self._locked():
            self._assert_safe_path(self._object_path(digest))
        return self._storage_path(digest)

    def put(
        self,
        content: bytes | bytearray | memoryview,
        *,
        filename: str | None = None,
        mime_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        reference_id: str | None = None,
    ) -> AttachmentMetadata:
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise TypeError("content must be bytes-like")
        copied = bytes(content)
        supplied = (
            _text(filename, "filename", basename=True),
            _text(mime_type, "mime_type"),
            _freeze_json({} if metadata is None else metadata),
            None if reference_id is None else _reference(reference_id),
        )
        digest = compute_content_hash(copied)
        with self._locked():
            object_path = self._object_path(digest)
            record = self._load_record(digest)
            if record is not None:
                self._require_valid_object(digest, record.size)
                if record.deleted:
                    raise AttachmentDeletedError(f"attachment {digest} is deleted; call undelete first")
                refs = set(record.references)
                if supplied[3] is not None:
                    refs.add(supplied[3])
                # First-write metadata is immutable, including explicit empty values.
                next_record = _Record(
                    record.content_hash,
                    record.size,
                    record.filename,
                    record.mime_type,
                    record.metadata,
                    False,
                    tuple(sorted(refs)),
                )
            else:
                if _lexists(object_path):
                    self._quarantine_one(object_path, "orphan")
                refs = () if supplied[3] is None else (supplied[3],)
                next_record = _Record(
                    digest,
                    len(copied),
                    supplied[0],
                    supplied[1],
                    supplied[2],
                    False,
                    refs,
                )
            marker = self._begin_transaction("put", digest, next_record.size)
            try:
                if record is None:
                    self._atomic_write(object_path, copied)
                self._write_record(next_record)
                self._finish_transaction(marker)
            except Exception:
                self._recover_locked()
                raise
            self._require_valid_object(digest, next_record.size)
            return self._metadata_from_record(next_record)

    store_bytes = put
    save = put

    def put_file(
        self,
        source: str | os.PathLike[str],
        *,
        filename: str | None = None,
        mime_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        reference_id: str | None = None,
    ) -> AttachmentMetadata:
        source_path = Path(os.path.abspath(source))
        content = self._read_source_once(source_path)
        return self.put(
            content,
            filename=filename if filename is not None else source_path.name,
            mime_type=mime_type,
            metadata=metadata,
            reference_id=reference_id,
        )

    store_file = put_file

    def read(self, content_hash: str | AttachmentMetadata, *, include_deleted: bool = False) -> bytes:
        digest = _digest(content_hash)
        with self._locked():
            record = self._require_record(digest)
            if record.deleted and not include_deleted:
                raise AttachmentDeletedError(f"attachment {digest} is deleted")
            return self._require_valid_object(digest, record.size).data

    read_bytes = read
    get = read

    def verify(self, content_hash: str | AttachmentMetadata) -> bool:
        digest = _digest(content_hash)
        with self._locked():
            try:
                record = self._require_record(digest)
                self._require_valid_object(digest, record.size)
            except (AttachmentMissingError, AttachmentIntegrityError, AttachmentMetadataError):
                return False
            return True

    verify_content = verify

    def metadata(self, content_hash: str | AttachmentMetadata) -> AttachmentMetadata:
        digest = _digest(content_hash)
        with self._locked():
            record = self._require_record(digest)
            self._require_valid_object(digest, record.size)
            return self._metadata_from_record(record)

    get_metadata = metadata

    def add_reference(self, content_hash: str | AttachmentMetadata, reference_id: str) -> AttachmentMetadata:
        digest = _digest(content_hash)
        reference = _reference(reference_id)
        with self._locked():
            record = self._require_record(digest)
            self._require_valid_object(digest, record.size)
            if record.deleted:
                raise AttachmentDeletedError(f"attachment {digest} is deleted")
            updated = _Record(
                record.content_hash, record.size, record.filename, record.mime_type,
                record.metadata, False, tuple(sorted(set(record.references) | {reference})),
            )
            self._commit_record(updated, "reference")
            return self._metadata_from_record(updated)

    retain = add_reference

    def release_reference(self, content_hash: str | AttachmentMetadata, reference_id: str) -> AttachmentMetadata:
        digest = _digest(content_hash)
        reference = _reference(reference_id)
        with self._locked():
            record = self._require_record(digest)
            self._require_valid_object(digest, record.size)
            if reference not in record.references:
                raise KeyError(f"reference {reference!r} is not registered")
            updated = _Record(
                record.content_hash, record.size, record.filename, record.mime_type,
                record.metadata, record.deleted,
                tuple(item for item in record.references if item != reference),
            )
            self._commit_record(updated, "reference")
            return self._metadata_from_record(updated)

    release = release_reference

    def delete(self, content_hash: str | AttachmentMetadata) -> AttachmentMetadata:
        digest = _digest(content_hash)
        with self._locked():
            record = self._require_record(digest)
            self._require_valid_object(digest, record.size)
            if record.deleted:
                return self._metadata_from_record(record)
            updated = _Record(
                record.content_hash, record.size, record.filename, record.mime_type,
                record.metadata, True, record.references,
            )
            self._commit_record(updated, "delete")
            return self._metadata_from_record(updated)

    tombstone = delete
    remove = delete

    def undelete(self, content_hash: str | AttachmentMetadata) -> AttachmentMetadata:
        digest = _digest(content_hash)
        with self._locked():
            record = self._require_record(digest)
            self._require_valid_object(digest, record.size)
            if not record.deleted:
                return self._metadata_from_record(record)
            updated = _Record(
                record.content_hash, record.size, record.filename, record.mime_type,
                record.metadata, False, record.references,
            )
            self._commit_record(updated, "undelete")
            self._require_valid_object(digest, updated.size)
            return self._metadata_from_record(updated)

    restore = undelete

    def purge(self, content_hash: str | AttachmentMetadata) -> None:
        digest = _digest(content_hash)
        with self._locked():
            record = self._require_record(digest)
            if record.references:
                raise ValueError("cannot purge an attachment with active references")
            if not record.deleted:
                raise ValueError("attachment must be logically deleted before purge")
            marker = self._begin_transaction("purge", digest, record.size)
            try:
                self._remove(self._object_path(digest))
                self._remove(self._record_path(digest))
                self._finish_transaction(marker)
            except Exception:
                self._recover_locked()
                raise

    def _require_record(self, digest: str) -> _Record:
        record = self._load_record(digest)
        object_path = self._object_path(digest)
        if record is None:
            if _lexists(object_path):
                raise AttachmentMetadataError(f"orphan object is not adopted: {digest}")
            raise AttachmentMissingError(f"attachment {digest} is missing")
        return record

    def _require_valid_object(self, digest: str, expected_size: int) -> _ObjectInfo:
        info = self._read_object(digest)
        if info.digest != digest:
            raise AttachmentIntegrityError(f"attachment {digest} failed SHA-256 verification")
        if info.size != expected_size:
            raise AttachmentIntegrityError(f"attachment {digest} size does not match metadata")
        return info

    def _metadata_from_record(self, record: _Record) -> AttachmentMetadata:
        return AttachmentMetadata(
            record.content_hash,
            record.size,
            self._storage_path(record.content_hash),
            record.filename,
            record.mime_type,
            record.metadata,
            record.deleted,
            record.references,
        )

    def _commit_record(self, record: _Record, operation: str) -> None:
        marker = self._begin_transaction(operation, record.content_hash, record.size)
        try:
            self._write_record(record)
            self._finish_transaction(marker)
        except Exception:
            self._recover_locked()
            raise

    def _storage_path(self, digest: str) -> str:
        return f"objects/{digest[:2]}/{digest[2:]}"

    def _object_path(self, digest: str) -> Path:
        path = self._objects / digest[:2] / digest[2:]
        self._assert_safe_path(path)
        return path

    def _record_path(self, digest: str) -> Path:
        path = self._metadata / f"{digest}.json"
        self._assert_safe_path(path)
        return path

    def _load_record(self, digest: str) -> _Record | None:
        path = self._record_path(digest)
        if _linkish(path):
            raise AttachmentSecurityError("metadata sidecar must not be a symlink or reparse point")
        if not path.exists():
            return None
        if not path.is_file():
            raise AttachmentMetadataError(f"metadata sidecar is not a regular file: {path}")
        try:
            raw = json.loads(self._read_file_bytes(path).decode("utf-8"))
            if not isinstance(raw, dict) or _digest(raw["content_hash"]) != digest:
                raise ValueError
            size = raw["size"]
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise TypeError
            filename = _text(raw.get("filename"), "filename", basename=True)
            mime_type = _text(raw.get("mime_type"), "mime_type")
            metadata = _freeze_json(raw.get("metadata", {}))
            deleted = raw["deleted"]
            references = raw.get("references", [])
            if not isinstance(deleted, bool) or not isinstance(references, list):
                raise TypeError
            refs = tuple(sorted({_reference(item) for item in references}))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise AttachmentMetadataError(f"invalid attachment metadata: {path}") from error
        return _Record(digest, size, filename, mime_type, metadata, deleted, refs)

    def _write_record(self, record: _Record) -> None:
        payload = {
            "content_hash": record.content_hash,
            "deleted": record.deleted,
            "filename": record.filename,
            "metadata": _thaw_json(record.metadata),
            "mime_type": record.mime_type,
            "references": list(record.references),
            "size": record.size,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self._atomic_write(self._record_path(record.content_hash), encoded.encode("utf-8"))

    def _read_object(self, digest: str) -> _ObjectInfo:
        path = self._object_path(digest)
        self._assert_safe_path(path)
        try:
            if _POSIX_OPENAT:
                data, before, after = _read_posix_regular_file(path, "attachment object")
            else:
                if _linkish(path):
                    raise AttachmentSecurityError("attachment object must not be a symlink or reparse point")
                with path.open("rb") as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise AttachmentSecurityError("attachment object is not a regular file")
                    data = stream.read()
                    after = os.fstat(stream.fileno())
            if before.st_size != after.st_size:
                raise AttachmentIntegrityError("attachment changed while being read")
            self._assert_safe_path(path)
            if _linkish(path):
                raise AttachmentSecurityError("attachment object became a symlink or reparse point")
        except FileNotFoundError as error:
            raise AttachmentMissingError(f"attachment {digest} is missing") from error
        return _ObjectInfo(len(data), compute_content_hash(data), data)

    def _read_file_bytes(self, path: Path) -> bytes:
        """Read a small metadata/journal file through a no-follow descriptor."""

        self._assert_safe_path(path)
        if _POSIX_OPENAT:
            data, before, after = _read_posix_regular_file(path, "metadata path")
            if before.st_size != after.st_size:
                raise AttachmentIntegrityError("metadata changed while being read")
            self._assert_safe_path(path)
            return data
        if _linkish(path):
            raise AttachmentSecurityError("metadata path must not be a symlink or reparse point")
        data = path.read_bytes()
        self._assert_safe_path(path)
        if _linkish(path):
            raise AttachmentSecurityError("metadata path became a symlink or reparse point")
        return data

    def _read_source_once(self, path: Path) -> bytes:
        """Read one source descriptor; never check a path and then reopen it."""

        try:
            if _POSIX_OPENAT:
                data, before, after = _read_posix_regular_file(path, "source file")
                if before.st_size != after.st_size:
                    raise AttachmentIntegrityError("source changed while being read")
                return data
            _assert_no_reparse_components(path)
            if _linkish(path):
                raise AttachmentSecurityError("source file must not be a symlink or reparse point")
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise AttachmentSecurityError("source file is not a regular file")
                data = stream.read()
                after = os.fstat(stream.fileno())
            if before.st_size != after.st_size:
                raise AttachmentIntegrityError("source changed while being read")
            _assert_no_reparse_components(path)
            if _linkish(path):
                raise AttachmentSecurityError("source became a symlink or reparse point")
            return data
        except FileNotFoundError as error:
            raise AttachmentMissingError(str(path)) from error

    def _begin_transaction(self, operation: str, digest: str, size: int) -> Path:
        marker = self._transactions / f"{uuid4().hex}.json"
        self._atomic_write(
            marker,
            json.dumps(
                {"content_hash": digest, "operation": operation, "size": size, "version": 1},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        return marker

    def _finish_transaction(self, marker: Path) -> None:
        self._remove(marker)
        _fsync_dir(self._transactions)

    def _recover_locked(self) -> None:
        self._ensure_dir(self._quarantine)
        self._quarantine_temporary_files_locked()
        for marker in sorted(self._transactions.glob("*.json")):
            if _linkish(marker):
                raise AttachmentSecurityError("transaction marker must not be a symlink or reparse point")
            try:
                raw = json.loads(self._read_file_bytes(marker).decode("utf-8"))
                digest = _digest(raw["content_hash"])
                operation = raw["operation"]
                size = raw["size"]
                if not isinstance(operation, str) or not isinstance(size, int) or size < 0:
                    raise TypeError
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                self._quarantine_one(marker, "invalid-transaction")
                continue
            if operation == "purge":
                self._recover_purge(marker, digest, size)
            elif operation in {"put", "reference", "delete", "undelete"}:
                self._recover_record_commit(marker, digest)
            else:
                self._quarantine_one(marker, "unknown-transaction")
        self._quarantine_orphans_locked()

    def _recover_record_commit(self, marker: Path, digest: str) -> None:
        try:
            record = self._load_record(digest)
            if record is not None:
                self._require_valid_object(digest, record.size)
                self._remove(marker)
                return
        except (AttachmentStoreError, OSError):
            pass
        object_path = self._object_path(digest)
        record_path = self._record_path(digest)
        if _lexists(object_path):
            self._quarantine_one(object_path, "incomplete-object")
        if _lexists(record_path):
            self._quarantine_one(record_path, "incomplete-record")
        self._remove(marker)

    def _recover_purge(self, marker: Path, digest: str, size: int) -> None:
        record_path = self._record_path(digest)
        object_path = self._object_path(digest)
        try:
            record = self._load_record(digest)
        except AttachmentMetadataError:
            self._quarantine_one(record_path, "purge-invalid-record")
            self._quarantine_one(marker, "invalid-purge")
            return
        if record is not None and (not record.deleted or record.references):
            self._remove(marker)
            return
        self._remove(object_path)
        if _lexists(record_path):
            self._remove(record_path)
        self._remove(marker)

    def _quarantine_temporary_files_locked(self) -> None:
        for directory in (self._metadata, self._transactions):
            for temporary in sorted(directory.glob(".tmp-*")):
                self._quarantine_one(temporary, "temporary")

    def _quarantine_orphans_locked(self) -> None:
        for shard in sorted(self._objects.iterdir()):
            if _linkish(shard):
                raise AttachmentSecurityError("object shard must not be a symlink or reparse point")
            if not shard.is_dir():
                self._quarantine_one(shard, "invalid-shard")
                continue
            for object_path in sorted(shard.iterdir()):
                if _linkish(object_path):
                    raise AttachmentSecurityError("object must not be a symlink or reparse point")
                digest = shard.name + object_path.name
                if _HASH_RE.fullmatch(digest) and self._record_path(digest).exists():
                    continue
                self._quarantine_one(object_path, "orphan")
        for record_path in sorted(self._metadata.glob("*.json")):
            if _linkish(record_path):
                raise AttachmentSecurityError("metadata sidecar must not be a symlink or reparse point")
            digest = record_path.stem
            if _HASH_RE.fullmatch(digest) and _lexists(self._object_path(digest)):
                continue
            if _HASH_RE.fullmatch(digest):
                try:
                    record = self._load_record(digest)
                except AttachmentMetadataError:
                    record = None
                if record is not None and record.deleted and not record.references:
                    continue
            self._quarantine_one(record_path, "orphan-record")

    def _quarantine_one(self, path: Path, label: str) -> None:
        if not _lexists(path):
            return
        self._assert_safe_path(path)
        destination = self._quarantine / f"{label}-{path.name}-{uuid4().hex}"
        self._assert_safe_path(destination)
        if _POSIX_OPENAT:
            source_fd = _open_posix_directory(path.parent)
            quarantine_fd = _open_posix_directory(self._quarantine)
            try:
                try:
                    info = os.stat(path.name, dir_fd=source_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return
                if stat.S_ISLNK(info.st_mode):
                    raise AttachmentSecurityError("refusing to quarantine a symlink")
                os.replace(
                    path.name,
                    destination.name,
                    src_dir_fd=source_fd,
                    dst_dir_fd=quarantine_fd,
                )
                _fsync_fd(source_fd)
                _fsync_fd(quarantine_fd)
            finally:
                os.close(source_fd)
                os.close(quarantine_fd)
            return
        os.replace(path, destination)
        _fsync_dir(path.parent)
        _fsync_dir(self._quarantine)
        if os.name == "nt":
            _assert_no_reparse_components(path.parent)
            _assert_no_reparse_components(destination.parent)
            _assert_no_reparse_components(destination)
            if _linkish(destination):
                raise AttachmentSecurityError("quarantine destination became a symlink or reparse point")

    def _atomic_write(self, target: Path, content: bytes) -> None:
        self._assert_safe_path(target)
        self._ensure_dir(target.parent)
        if _POSIX_OPENAT:
            parent_fd = _open_posix_directory(target.parent)
            temporary_name = f".tmp-{uuid4().hex}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            try:
                descriptor = os.open(
                    temporary_name,
                    flags,
                    0o600,
                    dir_fd=parent_fd,
                )
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                except Exception:
                    raise
                os.replace(
                    temporary_name,
                    target.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                info = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise AttachmentSecurityError("atomic target is not a regular file")
                _fsync_fd(parent_fd)
            except Exception:
                try:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
                raise
            finally:
                os.close(parent_fd)
            self._assert_safe_path(target)
            if _linkish(target):
                raise AttachmentSecurityError("atomic target became a symlink or reparse point")
            return
        descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=str(target.parent))
        temporary = Path(temporary_name)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._assert_safe_path(target)
            os.replace(temporary, target)
            self._assert_safe_path(target)
            if _linkish(target):
                raise AttachmentSecurityError("atomic target became a symlink or reparse point")
            os.chmod(target, 0o600)
            _fsync_dir(target.parent)
            if os.name == "nt":
                _assert_no_reparse_components(target.parent)
                _assert_no_reparse_components(target)
                if _linkish(target):
                    raise AttachmentSecurityError("atomic target became a symlink or reparse point")
        finally:
            if _lexists(temporary):
                temporary.unlink()

    def _remove(self, path: Path) -> None:
        self._assert_safe_path(path)
        if _POSIX_OPENAT:
            parent_fd = _open_posix_directory(path.parent)
            try:
                try:
                    info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise AttachmentSecurityError("refusing to remove a non-regular path")
                os.unlink(path.name, dir_fd=parent_fd)
                _fsync_fd(parent_fd)
            finally:
                os.close(parent_fd)
            return
        if _lexists(path):
            if _linkish(path):
                raise AttachmentSecurityError("refusing to remove a symlink or reparse point")
            path.unlink()
            _fsync_dir(path.parent)
            if os.name == "nt":
                _assert_no_reparse_components(path.parent)
                if _linkish(path):
                    raise AttachmentSecurityError("removed path became a symlink or reparse point")

    def _ensure_dir(self, path: Path) -> None:
        self._assert_safe_path(path)
        if _POSIX_OPENAT:
            descriptor = _open_posix_directory(path, create=True)
            try:
                os.fchmod(descriptor, 0o700)
                _fsync_fd(descriptor)
            finally:
                os.close(descriptor)
            self._assert_safe_path(path)
            return
        if _linkish(path):
            raise AttachmentSecurityError(f"directory must not be a symlink or reparse point: {path}")
        path.mkdir(parents=True, exist_ok=True)
        if _linkish(path) or not path.is_dir():
            raise AttachmentSecurityError(f"storage path is not a directory: {path}")
        try:
            os.chmod(path, 0o700)
        except OSError:
            if os.name != "nt":
                raise
        self._assert_safe_path(path)

    def _assert_safe_path(self, path: Path) -> None:
        try:
            absolute = path.absolute()
            relative = absolute.relative_to(self._root)
        except ValueError as error:
            raise AttachmentSecurityError(f"path escapes attachment root: {path}") from error
        current = self._root
        for component in relative.parts:
            current = current / component
            if _linkish(current):
                raise AttachmentSecurityError(f"symlink/reparse component is not allowed: {current}")
        try:
            resolved = absolute.resolve(strict=False)
            resolved.relative_to(self._root)
        except (OSError, ValueError) as error:
            raise AttachmentSecurityError(f"path escapes attachment root: {path}") from error

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock, self._advisory_lock():
            self._recover_locked()
            yield

    @contextmanager
    def _advisory_lock(self) -> Iterator[None]:
        if _POSIX_OPENAT:
            root_fd = _open_posix_directory(self._root)
            try:
                descriptor = os.open(
                    ".store.lock",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=root_fd,
                )
            except Exception:
                os.close(root_fd)
                raise
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode):
                    raise AttachmentSecurityError("store lock is not a regular file")
                if info.st_size == 0:
                    os.write(descriptor, b"\0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.fchmod(descriptor, 0o600)
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
                    os.close(root_fd)
            return
        self._assert_safe_path(self._lock_path)
        if _linkish(self._lock_path):
            raise AttachmentSecurityError("store lock must not be a symlink or reparse point")
        descriptor = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if _linkish(self._lock_path):
                raise AttachmentSecurityError("store lock became a symlink or reparse point")
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise AttachmentSecurityError("store lock is not a regular file")
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.chmod(self._lock_path, 0o600)
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            elif msvcrt is not None:
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:  # pragma: no cover
                raise RuntimeError("no portable advisory lock implementation is available")
            if _linkish(self._lock_path):
                raise AttachmentSecurityError("store lock became a symlink or reparse point")
            yield
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                elif msvcrt is not None:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            finally:
                try:
                    lock_changed = _linkish(self._lock_path)
                finally:
                    os.close(descriptor)
                if lock_changed:
                    raise AttachmentSecurityError("store lock became a symlink or reparse point")


def _linkish(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return os.name == "nt" and bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _assert_no_reparse_components(path: Path) -> None:
    """Reject a Windows source path whose parent chain contains reparse points.

    ``put_file`` intentionally accepts a source outside the attachment root,
    so this check verifies component integrity without applying the store-root
    containment rule.  The same-account, non-cooperating race between these
    checks remains outside the module threat model.
    """

    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        if _linkish(current):
            raise AttachmentSecurityError(f"source path contains a symlink or reparse component: {current}")


def _lexists(path: Path) -> bool:
    return path.exists() or _linkish(path)


def _read_posix_regular_file(path: Path, label: str) -> tuple[bytes, os.stat_result, os.stat_result]:
    """Open a POSIX file without blocking, then verify it before reading."""

    parent_fd: int | None = None
    try:
        try:
            parent_fd = _open_posix_directory(path.parent)
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise AttachmentSecurityError(
                    f"{label} must not be a symlink or non-directory path"
                ) from error
            raise
        try:
            descriptor = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.ENOTDIR, errno.ENXIO}:
                raise AttachmentSecurityError(
                    f"{label} must not be a symlink, special node, or non-directory path"
                ) from error
            raise
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise AttachmentSecurityError(f"{label} is not a regular file")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        return b"".join(chunks), before, after
    finally:
        if parent_fd is not None:
            os.close(parent_fd)


def _open_posix_directory(path: Path, *, create: bool = False) -> int:
    """Walk every absolute component with O_DIRECTORY|O_NOFOLLOW."""

    if not _POSIX_OPENAT:
        raise RuntimeError("POSIX directory descriptors are unavailable")
    absolute = Path(os.path.abspath(path))
    if absolute.anchor != "/":
        raise AttachmentSecurityError(f"POSIX path is not absolute: {path}")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for component in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _fsync_fd(descriptor: int) -> None:
    if os.name != "nt":
        os.fsync(descriptor)


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = _open_posix_directory(path)
    try:
        _fsync_fd(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "AttachmentDeletedError",
    "AttachmentIntegrityError",
    "AttachmentMetadata",
    "AttachmentMetadataError",
    "AttachmentMissingError",
    "AttachmentNotFoundError",
    "AttachmentSecurityError",
    "AttachmentStore",
    "AttachmentStoreError",
    "CorruptAttachmentError",
    "compute_content_hash",
    "content_hash",
]
