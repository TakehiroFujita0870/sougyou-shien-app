"""Pure, local-only contracts for the SP-03 file-ingestion spike."""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Mapping, Sequence
import csv
import io


MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_DOCX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_PDF_PAGES = 500


class IngestionState(str, Enum):
    RECEIVED = "received"
    VALIDATING = "validating"
    EXTRACTING = "extracting"
    INDEXED = "indexed"
    SEARCHABLE = "searchable"
    REJECTED = "rejected"
    DELETING = "deleting"
    DELETED = "deleted"


class DeletionTarget(str, Enum):
    ORIGINAL = "original"
    EXTRACTED_TEXT = "extracted_text"
    CHUNKS = "chunks"
    EMBEDDINGS = "embeddings"


@dataclass(frozen=True)
class FileDecision:
    category: str
    state: IngestionState
    reason: str | None = None
    needs_ocr: bool = False
    untrusted_content: bool = True


@dataclass(frozen=True)
class ExtractedPage:
    page: int
    content: str


@dataclass(frozen=True)
class ExtractedContent:
    document_id: str
    version: int
    page: int
    content: str
    content_hash: str


@dataclass(frozen=True)
class DeletionItem:
    target: DeletionTarget
    identifiers: tuple[str, ...]


@dataclass(frozen=True)
class DeletionManifest:
    document_id: str
    version: int
    items: tuple[DeletionItem, ...]


def _rejected(category: str, reason: str) -> FileDecision:
    return FileDecision(category, IngestionState.REJECTED, reason)


def _is_utf_text(content: bytes) -> bool:
    return _decode_text(content) is not None


def _decode_text(content: bytes) -> str | None:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        if not content.startswith((b"\xff\xfe", b"\xfe\xff")):
            return None
        try:
            return content.decode("utf-16")
        except UnicodeDecodeError:
            return None


def _valid_csv(content: bytes) -> bool:
    text = _decode_text(content)
    if text is None:
        return False
    try:
        list(csv.reader(io.StringIO(text), strict=True))
        return True
    except (csv.Error, UnicodeDecodeError):
        return False


def classify_file(
    filename: str,
    content: bytes,
    *,
    page_count: int | None = None,
    unpacked_bytes: int | None = None,
    contains_macro: bool = False,
    contains_script: bool = False,
    has_extractable_text: bool = True,
) -> FileDecision:
    """Classify metadata and bytes without storing, extracting, or sending them."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"pdf", "docx", "txt", "csv"}:
        return _rejected("unsupported", "extension_not_allowed")
    if len(content) > MAX_SOURCE_BYTES:
        return _rejected("oversize", "source_bytes_exceeded")
    if contains_macro or contains_script:
        return _rejected("unsupported", "active_content_detected")
    if suffix == "pdf":
        if not content.startswith(b"%PDF-"):
            return _rejected("malformed", "pdf_signature_invalid")
        if b"/Encrypt" in content:
            return _rejected("encrypted", "pdf_encrypted")
        if page_count is not None and page_count > MAX_PDF_PAGES:
            return _rejected("oversize", "pdf_page_limit_exceeded")
        return FileDecision("supported", IngestionState.VALIDATING, needs_ocr=not has_extractable_text)
    if suffix == "docx":
        if not content.startswith(b"PK\x03\x04"):
            return _rejected("malformed", "docx_zip_signature_invalid")
        if unpacked_bytes is not None and unpacked_bytes > MAX_DOCX_UNPACKED_BYTES:
            return _rejected("oversize", "docx_unpacked_limit_exceeded")
        return FileDecision("supported", IngestionState.VALIDATING)
    if suffix == "txt" and not _is_utf_text(content):
        return _rejected("malformed", "text_encoding_unsupported")
    if suffix == "csv" and not _valid_csv(content):
        return _rejected("malformed", "csv_invalid")
    return FileDecision("supported", IngestionState.VALIDATING)


def normalize_extraction(
    document_id: str, version: int, pages: Sequence[ExtractedPage]
) -> tuple[ExtractedContent, ...]:
    """Normalize a fake extractor response into source-linked, hashable pages."""
    return tuple(
        ExtractedContent(document_id, version, page.page, page.content, sha256(page.content.encode()).hexdigest())
        for page in pages
    )


def deletion_manifest(
    document_id: str, version: int, identifiers: Mapping[DeletionTarget, Sequence[str]]
) -> DeletionManifest:
    """Declare every stored derivative that a future deletion worker must remove."""
    return DeletionManifest(
        document_id,
        version,
        tuple(DeletionItem(target, tuple(identifiers.get(target, ()))) for target in DeletionTarget),
    )
