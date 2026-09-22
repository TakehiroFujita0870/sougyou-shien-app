from __future__ import annotations

from pathlib import Path

import pytest

from dots.founder_graph_instruction_scanner import InstructionScanSecurityError, InstructionScanner


def test_scanner_accepts_agents_and_skill_under_allowed_root(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Project rules\nKeep history.\n", encoding="utf-8")
    skill_dir = tmp_path / ".codex" / "skills" / "graph"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Graph skill\nUse typed relations.\n", encoding="utf-8")

    observations = InstructionScanner(tmp_path).scan()

    assert [item.path for item in observations] == [".codex/skills/graph/SKILL.md", "AGENTS.md"]
    assert all(item.available and item.artifact is not None for item in observations)
    assert observations[0].scope == ".codex/skills/graph"


def test_scanner_rejects_outside_and_symlink_paths(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "AGENTS.md"
    outside_file.write_text("outside", encoding="utf-8")
    scanner = InstructionScanner(root)

    with pytest.raises(InstructionScanSecurityError, match="escapes"):
        scanner.scan_paths([outside_file])
    link = root / "SKILL.md"
    try:
        link.symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(InstructionScanSecurityError, match="symlink"):
        scanner.scan_paths([link])


def test_scanner_tracks_hash_change_and_missing_without_mutating_history(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("first", encoding="utf-8")
    scanner = InstructionScanner(tmp_path)

    first = scanner.scan()[0]
    unchanged = scanner.scan()[0]
    path.write_text("second", encoding="utf-8")
    changed = scanner.scan()[0]
    path.unlink()
    missing = scanner.scan()[0]

    assert first.changed is True
    assert unchanged.changed is False
    assert changed.changed is True
    assert changed.content_hash != first.content_hash
    assert missing.available is False
    assert missing.content_hash == changed.content_hash
    assert path.exists() is False


def test_secret_lines_are_excluded_from_summary_and_artifact(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "# Safe title\nAPI_KEY=super-secret-value\nUse local graph search.\npassword: hidden\n",
        encoding="utf-8",
    )
    scanner = InstructionScanner(tmp_path)

    observation = scanner.scan()[0]

    assert observation.excluded_secret_lines == 2
    assert "super-secret-value" not in observation.summary
    assert "hidden" not in observation.summary
    assert observation.artifact is not None
    assert "super-secret-value" not in repr(observation.artifact)
