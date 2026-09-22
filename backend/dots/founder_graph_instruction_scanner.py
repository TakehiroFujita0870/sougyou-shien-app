"""Safe, non-mutating scanner for AGENTS.md and SKILL.md references."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
from typing import Iterable

from .founder_graph import InstructionArtifact, Status


class InstructionScanSecurityError(ValueError):
    """A candidate path is outside the allowed instruction boundary."""


@dataclass(frozen=True, slots=True)
class InstructionObservation:
    path: str
    scope: str
    content_hash: str
    mtime_ns: int
    summary: str
    excluded_secret_lines: int
    available: bool
    changed: bool
    artifact: InstructionArtifact | None


_SECRET_LINE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|token|password|secret|private[_ -]?key|authorization)\s*[:=]"
)
_TARGET_NAMES = frozenset({"AGENTS.md", "SKILL.md"})
_REPARSE_POINT = 0x0400


class InstructionScanner:
    """Observe instruction files below one private root without editing them."""

    def __init__(self, allowed_root: str | os.PathLike[str], *, owner_id: str = "local-owner") -> None:
        root = Path(os.path.abspath(allowed_root))
        self._assert_directory(root)
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise InstructionScanSecurityError("owner_id is required")
        self._root = root
        self._owner_id = owner_id.strip()
        self._history: dict[str, InstructionObservation] = {}

    @property
    def allowed_root(self) -> str:
        return str(self._root)

    def scan(self) -> tuple[InstructionObservation, ...]:
        paths: list[Path] = []
        for candidate in self._root.rglob("*"):
            if candidate.name in _TARGET_NAMES:
                paths.append(candidate)
        return self.scan_paths(paths)

    def scan_paths(self, paths: Iterable[str | os.PathLike[str]]) -> tuple[InstructionObservation, ...]:
        current: dict[str, InstructionObservation] = {}
        for raw_path in sorted((Path(path) for path in paths), key=lambda item: str(item)):
            path = self._safe_candidate(raw_path)
            key = self._relative(path)
            if key in current:
                raise InstructionScanSecurityError(f"duplicate instruction path: {key}")
            current[key] = self._observe(path, key)

        for key, previous in self._history.items():
            if key not in current:
                current[key] = InstructionObservation(
                    path=previous.path,
                    scope=previous.scope,
                    content_hash=previous.content_hash,
                    mtime_ns=previous.mtime_ns,
                    summary=previous.summary,
                    excluded_secret_lines=previous.excluded_secret_lines,
                    available=False,
                    changed=False,
                    artifact=previous.artifact,
                )
        self._history = current
        return tuple(current[key] for key in sorted(current))

    def _observe(self, path: Path, relative: str) -> InstructionObservation:
        try:
            raw = path.read_bytes()
            metadata = path.stat()
        except (OSError, UnicodeError) as error:
            raise InstructionScanSecurityError(f"instruction file is not readable: {relative}") from error
        digest = sha256(raw).hexdigest()
        prior = self._history.get(relative)
        changed = prior is None or prior.content_hash != digest
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise InstructionScanSecurityError(f"instruction file must be UTF-8: {relative}") from error
        summary, excluded = self._safe_summary(text)
        artifact = InstructionArtifact(
            owner_id=self._owner_id,
            id=f"instruction_{sha256(f'{relative}:{digest}'.encode('utf-8')).hexdigest()[:32]}",
            path=relative,
            scope=str(Path(relative).parent).replace("\\", "/"),
            content_hash=digest,
            status=Status.ACTIVE,
        )
        return InstructionObservation(
            path=relative,
            scope=artifact.scope,
            content_hash=digest,
            mtime_ns=metadata.st_mtime_ns,
            summary=summary,
            excluded_secret_lines=excluded,
            available=True,
            changed=changed,
            artifact=artifact,
        )

    @staticmethod
    def _safe_summary(text: str) -> tuple[str, int]:
        safe_lines: list[str] = []
        excluded = 0
        for line in text.splitlines():
            if _SECRET_LINE.search(line):
                excluded += 1
                continue
            stripped = line.strip()
            if stripped:
                safe_lines.append(stripped)
            if len(" ".join(safe_lines)) >= 600:
                break
        return " ".join(safe_lines)[:600], excluded

    def _safe_candidate(self, raw_path: Path) -> Path:
        path = Path(os.path.abspath(raw_path))
        if path.name not in _TARGET_NAMES:
            raise InstructionScanSecurityError("only AGENTS.md and SKILL.md may be scanned")
        relative = self._relative(path)
        current = self._root
        for component in Path(relative).parts:
            current = current / component
            if self._linkish(current):
                raise InstructionScanSecurityError(f"instruction path contains a symlink or reparse point: {relative}")
        if not path.is_file():
            raise InstructionScanSecurityError(f"instruction file is not a regular file: {relative}")
        return path

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self._root).as_posix()
        except ValueError as error:
            raise InstructionScanSecurityError("instruction path escapes the allowed root") from error

    @staticmethod
    def _assert_directory(path: Path) -> None:
        if InstructionScanner._linkish(path) or not path.is_dir():
            raise InstructionScanSecurityError("allowed instruction root must be a regular directory")

    @staticmethod
    def _linkish(path: Path) -> bool:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return False
        return stat.S_ISLNK(info.st_mode) or (
            os.name == "nt" and bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)
        )
