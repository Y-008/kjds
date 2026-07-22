from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.verify_secrets import scan_history


def test_scan_history_detects_deleted_secret(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init")
    git("config", "user.name", "KJDS Test")
    git("config", "user.email", "test@example.invalid")
    secret = "ghp_" + "a" * 24
    (tmp_path / "credential.txt").write_text(secret, encoding="utf-8")
    git("add", "credential.txt")
    git("commit", "-m", "add fixture")
    (tmp_path / "credential.txt").unlink()
    git("add", "-u")
    git("commit", "-m", "remove fixture")

    findings, _ = scan_history(tmp_path)

    assert "history: github-token" in findings
