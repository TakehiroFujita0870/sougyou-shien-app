from __future__ import annotations

import errno
import hashlib
import json
import multiprocessing
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket

import pytest

import dots.founder_graph_attachments as attachments
from dots.founder_graph_attachments import (
    AttachmentDeletedError,
    AttachmentIntegrityError,
    AttachmentMetadataError,
    AttachmentMissingError,
    AttachmentSecurityError,
    AttachmentStore,
)


def object_path(store: AttachmentStore, stored) -> Path:
    return Path(store.root) / stored.storage_path


def _run_posix_reader(store: AttachmentStore, operation: str, argument, result_queue) -> None:
    try:
        if operation == "object":
            store._read_object(argument)
        elif operation == "metadata":
            store._read_file_bytes(argument)
        else:
            store._read_source_once(argument)
    except BaseException as error:  # pragma: no cover - executed in a child process.
        result_queue.put(type(error).__name__)
    else:  # pragma: no cover - executed in a child process.
        result_queue.put("ok")


def _assert_posix_reader_fails_closed(
    store: AttachmentStore, operation: str, argument, expected_error: str
) -> None:
    context = multiprocessing.get_context("fork")
    result_queue = context.Queue()
    process = context.Process(
        target=_run_posix_reader,
        args=(store, operation, argument, result_queue),
    )
    process.start()
    process.join(timeout=1.0)
    try:
        assert not process.is_alive(), f"{operation} reader blocked on a non-regular path"
        assert result_queue.get(timeout=1.0) == expected_error
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
        result_queue.close()
        result_queue.join_thread()


def test_put_is_content_addressed_atomic_and_deduplicates_bytes(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    payload = b"founder graph attachment\x00"
    supplied_metadata = {"labels": ["source"], "version": 1}
    expected_hash = hashlib.sha256(payload).hexdigest()

    first = store.put(
        payload,
        filename="brief.txt",
        mime_type="text/plain",
        metadata=supplied_metadata,
        reference_id="source-revision-1",
    )
    second = store.put(bytearray(payload), filename="renamed.txt", reference_id="source-revision-2")

    assert first.content_hash == expected_hash
    assert first.hash == expected_hash
    assert first.size == len(payload)
    assert first.mime_type == "text/plain"
    assert first.path == second.path
    assert first.storage_path == second.storage_path
    assert second.reference_count == 2
    assert second.filename == "brief.txt"
    assert second.mime_type == "text/plain"
    first_path = object_path(store, first)
    assert first_path.is_file()
    assert not list(first_path.parent.glob(".tmp-*"))
    assert len(list((tmp_path / "attachments" / "objects").rglob("*"))) == 2

    supplied_metadata["labels"].append("changed")
    assert first.metadata["labels"] == ("source",)

    mutable_input = bytearray(b"copy me")
    copied = store.put(mutable_input)
    mutable_input[:] = b"changed"
    assert store.read(copied.content_hash) == b"copy me"


def test_metadata_and_caller_inputs_are_immutable_and_persist_across_instances(tmp_path: Path) -> None:
    root = tmp_path / "attachments"
    caller_metadata = {"nested": {"keep": True}, "items": ["one"]}
    store = AttachmentStore(root)
    stored = store.put(b"immutable", metadata=caller_metadata)

    caller_metadata["nested"]["keep"] = False
    caller_metadata["items"].append("two")

    with pytest.raises(TypeError):
        stored.metadata["nested"]["keep"] = False  # type: ignore[index]
    with pytest.raises(TypeError):
        stored.metadata["items"] += ("two",)  # type: ignore[index]

    reloaded = AttachmentStore(root).metadata(stored.content_hash)
    assert reloaded.metadata["nested"]["keep"] is True
    assert reloaded.metadata["items"] == ("one",)


def test_logical_delete_keeps_shared_bytes_until_references_are_released_and_purged(
    tmp_path: Path,
) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    stored = store.put(b"shared", reference_id="source-a")
    store.add_reference(stored.content_hash, "source-b")

    tombstone = store.delete(stored.content_hash)
    assert tombstone.deleted is True
    assert tombstone.reference_count == 2
    assert object_path(store, stored).is_file()
    with pytest.raises(AttachmentDeletedError):
        store.read(stored.content_hash)
    assert store.read(stored.content_hash, include_deleted=True) == b"shared"

    with pytest.raises(ValueError, match="references"):
        store.purge(stored.content_hash)

    store.release_reference(stored.content_hash, "source-a")
    remaining = store.release_reference(stored.content_hash, "source-b")
    assert remaining.reference_count == 0
    assert remaining.deleted is True
    assert store.verify(stored.content_hash) is True

    store.purge(stored.content_hash)
    assert not object_path(store, stored).exists()
    with pytest.raises(AttachmentMissingError):
        store.read(stored.content_hash, include_deleted=True)
    assert store.verify(stored.content_hash) is False


def test_missing_and_corrupt_content_have_deterministic_behavior(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    missing_hash = hashlib.sha256(b"missing").hexdigest()

    assert store.verify(missing_hash) is False
    with pytest.raises(AttachmentMissingError):
        store.read(missing_hash)

    stored = store.put(b"original")
    object_path(store, stored).write_bytes(b"corrupt")
    assert store.verify(stored.content_hash) is False
    with pytest.raises(AttachmentIntegrityError):
        store.read(stored.content_hash)


def test_missing_object_with_sidecar_fails_closed_for_all_metadata_operations(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    stored = store.put(b"present", reference_id="source-1")
    object_path(store, stored).unlink()

    with pytest.raises(AttachmentMissingError):
        store.metadata(stored.content_hash)
    with pytest.raises(AttachmentMissingError):
        store.add_reference(stored.content_hash, "source-2")
    with pytest.raises(AttachmentMissingError):
        store.delete(stored.content_hash)
    assert store.verify(stored.content_hash) is False


def test_tampered_record_size_or_hash_is_rejected(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    stored = store.put(b"record-integrity")
    sidecar = Path(store.root) / "metadata" / f"{stored.content_hash}.json"
    record = json.loads(sidecar.read_text(encoding="utf-8"))

    record["size"] += 1
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AttachmentIntegrityError):
        store.metadata(stored.content_hash)

    record["size"] = stored.size
    record["content_hash"] = "0" * 64
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AttachmentMetadataError):
        store.metadata(stored.content_hash)


def test_put_rejects_tombstone_and_only_undelete_reactivates_valid_object(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    stored = store.put(b"deleted")
    store.delete(stored.content_hash)

    with pytest.raises(AttachmentDeletedError):
        store.put(b"deleted", reference_id="new-reference")
    restored = store.undelete(stored.content_hash)
    assert restored.deleted is False
    assert store.read(stored.content_hash) == b"deleted"


def test_two_store_instances_serialize_reference_updates_without_lost_updates(tmp_path: Path) -> None:
    root = tmp_path / "attachments"
    first_store = AttachmentStore(root)
    stored = first_store.put(b"concurrent")
    stores = (first_store, AttachmentStore(root))
    references = tuple(f"reference-{index}" for index in range(8))

    def add_reference(item: tuple[AttachmentStore, str]) -> None:
        item[0].add_reference(stored.content_hash, item[1])

    with ThreadPoolExecutor(max_workers=len(references)) as pool:
        list(pool.map(add_reference, ((stores[index % 2], reference) for index, reference in enumerate(references))))

    reloaded = AttachmentStore(root).metadata(stored.content_hash)
    assert set(reloaded.references) == set(references)


def test_failed_sidecar_commit_is_quarantined_and_not_auto_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "attachments"
    store = AttachmentStore(root)

    def fail_record(_record) -> None:
        raise OSError("simulated sidecar failure")

    monkeypatch.setattr(store, "_write_record", fail_record)
    with pytest.raises(OSError, match="sidecar"):
        store.put(b"orphaned")

    digest = hashlib.sha256(b"orphaned").hexdigest()
    assert not (Path(store.root) / "objects" / digest[:2] / digest[2:]).exists()
    assert list((Path(store.root) / "quarantine").iterdir())
    assert AttachmentStore(root).verify(digest) is False


def test_purge_journal_finishes_in_safe_order_after_sidecar_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "attachments"
    store = AttachmentStore(root)
    stored = store.put(b"purge-recovery")
    store.delete(stored.content_hash)

    original_remove = store._remove

    def fail_sidecar(path: Path) -> None:
        if path.suffix == ".json" and path.parent.name == "metadata":
            raise OSError("simulated sidecar removal failure")
        original_remove(path)

    monkeypatch.setattr(store, "_remove", fail_sidecar)
    with pytest.raises(OSError, match="sidecar"):
        store.purge(stored.content_hash)

    reloaded = AttachmentStore(root)
    assert reloaded.verify(stored.content_hash) is False
    assert not (Path(reloaded.root) / "metadata" / f"{stored.content_hash}.json").exists()


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_purge_deleted_zero_reference_cleans_missing_or_corrupt_object(
    tmp_path: Path, damage: str
) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    stored = store.put(b"purge-damaged")
    store.delete(stored.content_hash)
    target = object_path(store, stored)
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"wrong-bytes")

    store.purge(stored.content_hash)
    assert not target.exists()
    assert not (Path(store.root) / "metadata" / f"{stored.content_hash}.json").exists()


def test_startup_quarantines_abandoned_metadata_and_transaction_temps(tmp_path: Path) -> None:
    root = tmp_path / "attachments"
    store = AttachmentStore(root)
    for directory in ("metadata", "transactions"):
        (Path(store.root) / directory / ".tmp-abandoned").write_bytes(b"stale")

    reloaded = AttachmentStore(root)
    assert not (Path(reloaded.root) / "metadata" / ".tmp-abandoned").exists()
    assert not (Path(reloaded.root) / "transactions" / ".tmp-abandoned").exists()
    assert len(list((Path(reloaded.root) / "quarantine").glob("temporary-*"))) == 2


def test_hash_paths_reject_traversal_and_do_not_escape_root(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    bad_hashes = ("../outside", "..\\outside", "a" * 63, "g" * 64, "")

    for bad_hash in bad_hashes:
        with pytest.raises(ValueError):
            store.path_for(bad_hash)

    outside = tmp_path / "outside"
    outside.write_bytes(b"must not be read")
    with pytest.raises(ValueError):
        store.read("..\\outside")
    assert outside.read_bytes() == b"must not be read"


def test_symlinked_object_is_rejected_when_platform_supports_symlinks(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    stored = store.put(b"safe")
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside-content")
    object_path(store, stored).unlink()
    try:
        os.symlink(outside, object_path(store, stored))
    except (OSError, NotImplementedError):
        pytest.skip("the test platform does not permit symlink creation")

    with pytest.raises(AttachmentSecurityError):
        store.read(stored.content_hash, include_deleted=True)
    with pytest.raises(AttachmentSecurityError):
        store.verify(stored.content_hash)


def test_missing_source_file_is_rejected_without_creating_an_attachment(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments")

    with pytest.raises(AttachmentMissingError):
        store.put_file(tmp_path / "does-not-exist.bin")

    assert not list((tmp_path / "attachments" / "objects").rglob("*"))
    assert not list((tmp_path / "attachments" / "metadata").rglob("*"))


def test_root_is_explicit_and_object_path_stays_inside_root(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        AttachmentStore()  # type: ignore[call-arg]

    store = AttachmentStore(tmp_path / "attachments")
    stored = store.put(b"inside")
    assert isinstance(stored.path, str)
    assert not isinstance(stored.path, Path)
    assert not hasattr(stored.path, "write_bytes")
    assert object_path(store, stored).resolve().is_relative_to((tmp_path / "attachments").resolve())


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor contract")
def test_posix_object_metadata_and_source_fifo_opens_fail_closed_without_blocking(
    tmp_path: Path,
) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    digest = hashlib.sha256(b"fifo-object").hexdigest()
    object_fifo = Path(store.root) / "objects" / digest[:2] / digest[2:]
    object_fifo.parent.mkdir()
    metadata_fifo = Path(store.root) / "metadata" / "fifo-sidecar"
    source_fifo = tmp_path / "fifo-source.bin"
    for fifo in (object_fifo, metadata_fifo, source_fifo):
        os.mkfifo(fifo)

    _assert_posix_reader_fails_closed(store, "object", digest, "AttachmentSecurityError")
    _assert_posix_reader_fails_closed(store, "metadata", metadata_fifo, "AttachmentSecurityError")
    _assert_posix_reader_fails_closed(store, "source", source_fifo, "AttachmentSecurityError")

    assert not list((Path(store.root) / "transactions").iterdir())
    assert list((Path(store.root) / "objects" / digest[:2]).iterdir()) == [object_fifo]
    assert list((Path(store.root) / "metadata").iterdir()) == [metadata_fifo]


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor contract")
@pytest.mark.parametrize("surface", ["object", "metadata", "source"])
def test_posix_socket_open_failures_are_security_errors_for_each_surface(
    surface: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="a-", dir="/tmp") as root:
        store = AttachmentStore(Path(root) / "attachments")
        digest = hashlib.sha256(f"socket-{surface}".encode()).hexdigest()
        if surface == "object":
            socket_path = Path(store.root) / "objects" / digest[:2] / digest[2:]
            socket_path.parent.mkdir()
            reader = lambda: store._read_object(digest)
        elif surface == "metadata":
            socket_path = Path(store.root) / "metadata" / "socket-sidecar"
            reader = lambda: store._read_file_bytes(socket_path)
        else:
            socket_path = Path(root) / "socket-source.bin"
            reader = lambda: store._read_source_once(socket_path)

        unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            unix_socket.bind(str(socket_path))
            with pytest.raises(AttachmentSecurityError) as captured:
                reader()
            cause = captured.value.__cause__
            assert isinstance(cause, OSError)
            assert cause.errno == errno.ENXIO
        finally:
            unix_socket.close()
            socket_path.unlink(missing_ok=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor contract")
@pytest.mark.parametrize("node_kind", ["directory", "fifo"])
def test_posix_nonregular_nodes_are_rejected_before_read_for_all_surfaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, node_kind: str
) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    monkeypatch.setattr(
        attachments.os,
        "read",
        lambda *_args, **_kwargs: pytest.fail("non-regular node was read"),
    )
    digest = hashlib.sha256(f"{node_kind}-object".encode()).hexdigest()
    paths_and_readers = (
        (
            Path(store.root) / "objects" / digest[:2] / digest[2:],
            lambda: store._read_object(digest),
        ),
        (
            Path(store.root) / "metadata" / f"{node_kind}-sidecar",
            lambda: store._read_file_bytes(
                Path(store.root) / "metadata" / f"{node_kind}-sidecar"
            ),
        ),
        (
            tmp_path / f"{node_kind}-source.bin",
            lambda: store._read_source_once(tmp_path / f"{node_kind}-source.bin"),
        ),
    )
    for path, reader in paths_and_readers:
        path.parent.mkdir(parents=True, exist_ok=True)
        if node_kind == "directory":
            path.mkdir()
        else:
            os.mkfifo(path)
        with pytest.raises(AttachmentSecurityError):
            reader()


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor contract")
def test_posix_device_is_rejected_after_fstat_before_read() -> None:
    device_path = Path("/dev/null")
    with pytest.raises(AttachmentSecurityError):
        attachments._read_posix_regular_file(device_path, "device")


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor contract")
def test_posix_fstat_precedes_first_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "regular.bin"
    path.write_bytes(b"ordered")
    events: list[str] = []
    original_fstat = attachments.os.fstat
    original_read = attachments.os.read

    def recording_fstat(descriptor: int):
        events.append("fstat")
        return original_fstat(descriptor)

    def recording_read(descriptor: int, size: int):
        events.append("read")
        return original_read(descriptor, size)

    monkeypatch.setattr(attachments.os, "fstat", recording_fstat)
    monkeypatch.setattr(attachments.os, "read", recording_read)
    assert attachments._read_posix_regular_file(path, "source")[0] == b"ordered"
    assert events.index("fstat") < events.index("read")


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor contract")
def test_posix_special_open_and_enotdir_failures_close_parent_descriptors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    socket_path = tmp_path / "socket"
    unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    unix_socket.bind(str(socket_path))
    non_directory = tmp_path / "not-a-directory"
    non_directory.write_bytes(b"not a directory")
    enotdir_path = non_directory / "child"
    opened: list[int] = []
    closed: list[int] = []
    original_open = attachments.os.open
    original_close = attachments.os.close

    def recording_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def recording_close(descriptor: int):
        closed.append(descriptor)
        return original_close(descriptor)

    monkeypatch.setattr(attachments.os, "open", recording_open)
    monkeypatch.setattr(attachments.os, "close", recording_close)
    try:
        for _ in range(20):
            with pytest.raises(AttachmentSecurityError):
                attachments._read_posix_regular_file(socket_path, "socket")
            with pytest.raises(AttachmentSecurityError) as captured:
                attachments._read_posix_regular_file(enotdir_path, "enotdir")
            assert captured.value.__cause__.errno == errno.ENOTDIR
        assert set(opened) <= set(closed)
    finally:
        unix_socket.close()
        socket_path.unlink(missing_ok=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor contract")
@pytest.mark.parametrize("error_number", [errno.EIO, errno.ENXIO], ids=["eio", "enxio"])
def test_posix_general_io_error_is_not_catch_all_security_error(
    error_number: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "io-error.bin"
    path.write_bytes(b"payload")

    def raise_io_error(_descriptor: int, _size: int):
        raise OSError(error_number, "simulated I/O failure")

    monkeypatch.setattr(attachments.os, "read", raise_io_error)
    with pytest.raises(OSError) as captured:
        attachments._read_posix_regular_file(path, "source")
    assert captured.value.errno == error_number
    assert not isinstance(captured.value, AttachmentSecurityError)


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor contract")
def test_posix_symlink_and_eloop_are_normalized_to_attachment_security_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AttachmentStore(tmp_path / "attachments")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    digest = hashlib.sha256(b"symlink-object").hexdigest()
    object_link = Path(store.root) / "objects" / digest[:2] / digest[2:]
    object_link.parent.mkdir()
    metadata_link = Path(store.root) / "metadata" / "sidecar.json"
    source_target = tmp_path / "source-target"
    source_target.mkdir()
    (source_target / "source.bin").write_bytes(b"source")
    source_parent_link = tmp_path / "source-link"

    os.symlink(outside, object_link)
    os.symlink(outside, metadata_link)
    os.symlink(source_target, source_parent_link, target_is_directory=True)

    def assert_eloop(callable_) -> None:
        with pytest.raises(AttachmentSecurityError) as captured:
            callable_()
        cause = captured.value.__cause__
        assert isinstance(cause, OSError)
        assert cause.errno in {errno.ELOOP, errno.ENOTDIR}

    with monkeypatch.context() as context:
        context.setattr(store, "_assert_safe_path", lambda _path: None)
        assert_eloop(lambda: store._read_object(digest))
        assert_eloop(lambda: store._read_file_bytes(metadata_link))
        assert_eloop(lambda: store._read_source_once(source_parent_link / "source.bin"))

    object_link.unlink()
    metadata_link.unlink()
    source_parent_link.unlink()

    missing_digest = hashlib.sha256(b"missing").hexdigest()
    with pytest.raises(AttachmentMissingError):
        store.read(missing_digest)

    stored = store.put(b"metadata-classification")
    sidecar = Path(store.root) / "metadata" / f"{stored.content_hash}.json"
    sidecar.write_text("{invalid", encoding="utf-8")
    with pytest.raises(AttachmentMetadataError):
        store.metadata(stored.content_hash)


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point contract")
def test_windows_put_file_rejects_parent_junction_escape_before_and_after_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The source contract covers every parent, including a junction-like node."""

    store = AttachmentStore(tmp_path / "attachments")
    source_parent = tmp_path / "junction-parent"
    source_parent.mkdir()
    source = source_parent / "source.bin"
    source.write_bytes(b"source")
    original_linkish = attachments._linkish
    fstat_calls = 0

    def recording_fstat(descriptor: int):
        nonlocal fstat_calls
        fstat_calls += 1
        return original_fstat(descriptor)

    original_fstat = attachments.os.fstat
    monkeypatch.setattr(attachments.os, "fstat", recording_fstat)

    def junction_like(path: Path) -> bool:
        if Path(path) == source_parent:
            # First pass is clean; the simulated reparse point appears before
            # the post-read component walk.
            return fstat_calls >= 2
        return original_linkish(path)

    monkeypatch.setattr(attachments, "_linkish", junction_like)
    with pytest.raises(AttachmentSecurityError):
        store.put_file(source)

    assert not list((Path(store.root) / "objects").rglob("*"))
    assert not list((Path(store.root) / "metadata").rglob("*"))
    assert not list((Path(store.root) / "transactions").rglob("*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point contract")
def test_windows_quarantine_replace_and_unlink_recheck_parent_reparse_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Quarantine, replace, and unlink reject a reparse state after mutation."""

    store = AttachmentStore(tmp_path / "attachments")
    original_linkish = attachments._linkish

    # Quarantine: the source parent becomes reparse-like immediately after
    # os.replace, before the journal can accept the mutation.
    quarantine_source = Path(store.root) / "metadata" / "quarantine-source"
    quarantine_source.write_bytes(b"orphan")
    quarantine_parent = quarantine_source.parent
    quarantine_state = False
    original_replace = attachments.os.replace

    def replacing(*args, **kwargs):
        nonlocal quarantine_state
        result = original_replace(*args, **kwargs)
        quarantine_state = True
        return result

    def quarantine_linkish(path: Path) -> bool:
        if Path(path) == quarantine_parent:
            return quarantine_state
        return original_linkish(path)

    monkeypatch.setattr(attachments, "_linkish", quarantine_linkish)
    monkeypatch.setattr(attachments.os, "replace", replacing)
    with pytest.raises(AttachmentSecurityError):
        store._quarantine_one(quarantine_source, "test")

    # Atomic replace: the target itself becomes reparse-like after replace.
    monkeypatch.setattr(attachments, "_linkish", original_linkish)
    target = Path(store.root) / "metadata" / "atomic-target"
    atomic_state = False

    def atomic_replacing(*args, **kwargs):
        nonlocal atomic_state
        result = original_replace(*args, **kwargs)
        atomic_state = True
        return result

    def atomic_linkish(path: Path) -> bool:
        if Path(path) == target:
            return atomic_state
        return original_linkish(path)

    monkeypatch.setattr(attachments, "_linkish", atomic_linkish)
    monkeypatch.setattr(attachments.os, "replace", atomic_replacing)
    with pytest.raises(AttachmentSecurityError):
        store._atomic_write(target, b"atomic")

    # Unlink: the affected parent becomes reparse-like after the unlink.
    monkeypatch.setattr(attachments, "_linkish", original_linkish)
    remove_target = Path(store.root) / "metadata" / "remove-target"
    remove_target.write_bytes(b"remove")
    remove_state = False
    original_unlink = Path.unlink

    def unlinking(path: Path, *args, **kwargs):
        nonlocal remove_state
        result = original_unlink(path, *args, **kwargs)
        if Path(path) == remove_target:
            remove_state = True
        return result

    def remove_linkish(path: Path) -> bool:
        if Path(path) == remove_target.parent:
            return remove_state
        return original_linkish(path)

    monkeypatch.setattr(attachments, "_linkish", remove_linkish)
    monkeypatch.setattr(Path, "unlink", unlinking)
    with pytest.raises(AttachmentSecurityError):
        store._remove(remove_target)
