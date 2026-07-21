from __future__ import annotations

import re
import subprocess
from pathlib import Path

FORBIDDEN_SUFFIXES = frozenset({".key", ".pem", ".p12", ".pfx", ".dump", ".backup"})
SECRET_PATTERNS = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(rb"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "aws-access-key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "slack-token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
}


def scan_paths(root: Path, paths: list[str]) -> list[str]:
    findings: list[str] = []
    for relative in paths:
        path = root / relative
        name = path.name.lower()
        if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
            findings.append(f"{relative}: forbidden environment file")
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"{relative}: forbidden secret or backup file type")
            continue
        try:
            content = path.read_bytes()
        except (OSError, ValueError):
            continue
        if b"\x00" in content:
            continue
        for rule, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{relative}: {rule}")
    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    worktree_files = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    paths = [item for item in worktree_files if item]
    findings = scan_paths(root, paths)
    if findings:
        print("Secret scan failed:\n" + "\n".join(findings))
        return 1
    print(f"Secret scan passed: {len(paths)} non-ignored worktree files checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
