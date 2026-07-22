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


def forbidden_path(relative: str) -> str | None:
    name = Path(relative).name.lower()
    if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
        return "forbidden environment file"
    if Path(relative).suffix.lower() in FORBIDDEN_SUFFIXES:
        return "forbidden secret or backup file type"
    return None


def scan_paths(root: Path, paths: list[str]) -> list[str]:
    findings: list[str] = []
    for relative in paths:
        path = root / relative
        path_finding = forbidden_path(relative)
        if path_finding:
            findings.append(f"{relative}: {path_finding}")
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


def scan_history(root: Path) -> tuple[list[str], int]:
    historical_paths = {
        line
        for line in subprocess.run(
            ["git", "log", "--all", "--name-only", "--format="],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout.splitlines()
        if line
    }
    findings = [
        f"history:{path}: {reason}"
        for path in sorted(historical_paths)
        if (reason := forbidden_path(path))
    ]
    patch = subprocess.run(
        ["git", "log", "--all", "--format=", "--no-ext-diff", "--no-color", "-p"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    for rule, pattern in SECRET_PATTERNS.items():
        if pattern.search(patch):
            findings.append(f"history: {rule}")
    return findings, len(historical_paths)


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
    history_findings, historical_path_count = scan_history(root)
    findings.extend(history_findings)
    if findings:
        print("Secret scan failed:\n" + "\n".join(findings))
        return 1
    print(
        "Secret scan passed: "
        f"{len(paths)} non-ignored worktree files and "
        f"{historical_path_count} historical paths checked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
