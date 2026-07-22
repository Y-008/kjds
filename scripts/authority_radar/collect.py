from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

USER_AGENT = "KJDS-Authority-Radar/1.0 (local research collector)"
TRACKING_QUERY_PREFIXES = ("utm_", "spm", "scm", "ref_")
CATEGORY_LABELS = {
    "ai_frontier": "AI 前沿",
    "capital": "资本与监管",
    "enterprise_ai": "企业端 AI",
    "cross_border_ecommerce": "跨境电商",
    "china_platforms": "国内平台",
    "agent_infrastructure": "Agent 基础设施",
    "agentic_commerce": "Agentic Commerce",
}


@dataclass(frozen=True)
class Event:
    source_id: str
    category: str
    title: str
    url: str
    published_at: str | None
    source_tier: str
    confidence: float
    impact: int
    requires_review: bool
    excerpt: str
    raw: dict[str, Any]

    @property
    def key(self) -> str:
        material = f"{self.source_id}|{normalize_url(self.url)}|{normalize_text(self.title)}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(UTC).isoformat(timespec="seconds")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def normalize_url(value: str) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value.strip())
    filtered_query = []
    for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith(TRACKING_QUERY_PREFIXES) or lowered in {"source", "campaign"}:
            continue
        filtered_query.append((key, item))
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, urllib.parse.urlencode(filtered_query), "")
    )


def strip_markup(value: str) -> str:
    without_blocks = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_blocks)
    return normalize_text(without_tags)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def _child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names and child.text:
            return child.text.strip()
    return ""


def _entry_link(node: ET.Element) -> str:
    for child in node:
        if child.tag.rsplit("}", 1)[-1].lower() != "link":
            continue
        href = child.attrib.get("href")
        rel = child.attrib.get("rel", "alternate")
        if href and rel in {"alternate", ""}:
            return href
        if child.text and child.text.strip().startswith("http"):
            return child.text.strip()
    return ""


def parse_feed(payload: bytes, source: dict[str, Any]) -> list[Event]:
    root = ET.fromstring(payload)
    entries = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    results: list[Event] = []
    for node in entries[: int(source.get("max_items", 20))]:
        title = normalize_text(_child_text(node, ("title",)))
        link = _entry_link(node)
        if not link:
            link = _child_text(node, ("guid", "id"))
        published_raw = _child_text(node, ("published", "updated", "pubdate", "date"))
        summary = _child_text(node, ("summary", "description", "content"))
        if not title or not link:
            continue
        published = parse_datetime(published_raw)
        results.append(
            Event(
                source_id=source["id"],
                category=source["category"],
                title=title,
                url=normalize_url(link),
                published_at=isoformat(published) if published else None,
                source_tier=source["source_tier"],
                confidence=float(source["confidence"]),
                impact=int(source["impact"]),
                requires_review=bool(source.get("requires_review", False)),
                excerpt=strip_markup(summary)[:800],
                raw={"published_raw": published_raw},
            )
        )
    return results


def init_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS source_state (
            source_id TEXT PRIMARY KEY,
            last_checked_at TEXT,
            last_success_at TEXT,
            last_error TEXT,
            etag TEXT,
            last_modified TEXT,
            content_hash TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
            event_key TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at TEXT,
            discovered_at TEXT NOT NULL,
            source_tier TEXT NOT NULL,
            confidence REAL NOT NULL,
            impact INTEGER NOT NULL,
            requires_review INTEGER NOT NULL,
            excerpt TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new'
        );
        CREATE INDEX IF NOT EXISTS idx_events_category_time ON events(category, discovered_at DESC);
        CREATE TABLE IF NOT EXISTS runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            sources_checked INTEGER NOT NULL DEFAULT 0,
            events_new INTEGER NOT NULL DEFAULT 0,
            errors_json TEXT NOT NULL DEFAULT '[]'
        );
        """
    )
    existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(source_state)")}
    for column, definition in {
        "failure_count": "INTEGER NOT NULL DEFAULT 0",
        "next_retry_at": "TEXT",
        "last_status_code": "INTEGER",
    }.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE source_state ADD COLUMN {column} {definition}")
    connection.commit()


def get_state(connection: sqlite3.Connection, source_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM source_state WHERE source_id = ?", (source_id,)).fetchone()


def is_due(state: sqlite3.Row | None, source: dict[str, Any], now: datetime) -> bool:
    if not state or not state["last_checked_at"]:
        return True
    if state["last_error"] and state["next_retry_at"]:
        next_retry = parse_datetime(state["next_retry_at"])
        return not next_retry or now >= next_retry
    last_checked = parse_datetime(state["last_checked_at"])
    if not last_checked:
        return True
    return now - last_checked >= timedelta(minutes=int(source.get("interval_minutes", 60)))


def update_state(
    connection: sqlite3.Connection,
    source_id: str,
    *,
    success: bool,
    error: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    content_hash: str | None = None,
    status_code: int | None = None,
) -> None:
    now = isoformat()
    current = get_state(connection, source_id)
    previous_failures = int(current["failure_count"] or 0) if current else 0
    failure_count = 0 if success else previous_failures + 1
    next_retry_at = None
    if not success:
        blocked = status_code in {401, 403, 498}
        delay_minutes = 1440 if blocked else min(15 * (2 ** min(failure_count - 1, 5)), 360)
        next_retry_at = isoformat(utc_now() + timedelta(minutes=delay_minutes))
    connection.execute(
        """
        INSERT INTO source_state (
            source_id, last_checked_at, last_success_at, last_error, etag, last_modified, content_hash,
            failure_count, next_retry_at, last_status_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            last_checked_at = excluded.last_checked_at,
            last_success_at = CASE WHEN excluded.last_success_at IS NULL
                THEN source_state.last_success_at ELSE excluded.last_success_at END,
            last_error = excluded.last_error,
            etag = COALESCE(excluded.etag, source_state.etag),
            last_modified = COALESCE(excluded.last_modified, source_state.last_modified),
            content_hash = COALESCE(excluded.content_hash, source_state.content_hash),
            failure_count = excluded.failure_count,
            next_retry_at = excluded.next_retry_at,
            last_status_code = excluded.last_status_code
        """,
        (
            source_id,
            now,
            now if success else None,
            error,
            etag,
            last_modified,
            content_hash,
            failure_count,
            next_retry_at,
            status_code,
        ),
    )


def fetch_url(url: str, state: sqlite3.Row | None = None) -> tuple[int, bytes, dict[str, str]]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml,application/rss+xml,text/html,*/*"}
    if state and state["etag"]:
        headers["If-None-Match"] = state["etag"]
    if state and state["last_modified"]:
        headers["If-Modified-Since"] = state["last_modified"]
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return 304, b"", dict(exc.headers.items())
            last_error = exc
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise
        except (TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(2**attempt)
    if last_error:
        raise last_error
    raise RuntimeError("request failed without an exception")


def github_releases(source: dict[str, Any]) -> list[Event]:
    repo = source["repo"]
    endpoint = f"repos/{repo}/releases?per_page={int(source.get('max_items', 5))}"
    gh = shutil.which("gh")
    payload: list[dict[str, Any]]
    if gh:
        process = subprocess.run(
            [gh, "api", "-H", "Accept: application/vnd.github+json", endpoint],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if process.returncode == 0:
            payload = json.loads(process.stdout)
        else:
            raise RuntimeError(f"gh api failed: {normalize_text(process.stderr)[:300]}")
    else:
        status, body, _ = fetch_url(f"https://api.github.com/{endpoint}")
        if status != 200:
            raise RuntimeError(f"GitHub API returned {status}")
        payload = json.loads(body)
    results = []
    for release in payload:
        published = parse_datetime(release.get("published_at") or release.get("created_at"))
        title = release.get("name") or release.get("tag_name") or "Unnamed release"
        results.append(
            Event(
                source_id=source["id"],
                category=source["category"],
                title=f"{repo}: {title}",
                url=release.get("html_url", f"https://github.com/{repo}/releases"),
                published_at=isoformat(published) if published else None,
                source_tier=source["source_tier"],
                confidence=float(source["confidence"]),
                impact=int(source["impact"]),
                requires_review=bool(source.get("requires_review", False)),
                excerpt=strip_markup(release.get("body") or "")[:800],
                raw={"tag_name": release.get("tag_name"), "prerelease": release.get("prerelease", False)},
            )
        )
    return results


def parse_github_commits(payload: list[dict[str, Any]], source: dict[str, Any]) -> list[Event]:
    results = []
    for item in payload:
        commit = item.get("commit") or {}
        committer = commit.get("committer") or commit.get("author") or {}
        published = parse_datetime(committer.get("date"))
        message = normalize_text(commit.get("message") or "")
        title = message.split("\n", 1)[0] or "Unnamed commit"
        sha = item.get("sha") or ""
        results.append(
            Event(
                source_id=source["id"],
                category=source["category"],
                title=f"{source['repo']}: {title}",
                url=item.get("html_url", f"https://github.com/{source['repo']}/commits"),
                published_at=isoformat(published) if published else None,
                source_tier=source["source_tier"],
                confidence=float(source["confidence"]),
                impact=int(source["impact"]),
                requires_review=bool(source.get("requires_review", True)),
                excerpt=message[:800],
                raw={"sha": sha, "verified": (commit.get("verification") or {}).get("verified")},
            )
        )
    return results


def github_commits(source: dict[str, Any]) -> list[Event]:
    repo = source["repo"]
    endpoint = f"repos/{repo}/commits?per_page={int(source.get('max_items', 5))}"
    gh = shutil.which("gh")
    payload: list[dict[str, Any]]
    if gh:
        process = subprocess.run(
            [gh, "api", "-H", "Accept: application/vnd.github+json", endpoint],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if process.returncode != 0:
            raise RuntimeError(f"gh api failed: {normalize_text(process.stderr)[:300]}")
        payload = json.loads(process.stdout)
    else:
        status, body, _ = fetch_url(f"https://api.github.com/{endpoint}")
        if status != 200:
            raise RuntimeError(f"GitHub API returned {status}")
        payload = json.loads(body)
    return parse_github_commits(payload, source)


def insert_events(
    connection: sqlite3.Connection,
    events: list[Event],
    *,
    cutoff: datetime,
) -> int:
    inserted = 0
    for event in events:
        published = parse_datetime(event.published_at)
        if published and published < cutoff:
            continue
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO events (
                event_key, source_id, category, title, url, published_at, discovered_at,
                source_tier, confidence, impact, requires_review, excerpt, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.key,
                event.source_id,
                event.category,
                event.title,
                event.url,
                event.published_at,
                isoformat(),
                event.source_tier,
                event.confidence,
                event.impact,
                int(event.requires_review),
                event.excerpt,
                json.dumps(event.raw, ensure_ascii=False, sort_keys=True),
            ),
        )
        inserted += int(cursor.rowcount > 0)
    return inserted


def process_page_hash(
    connection: sqlite3.Connection,
    source: dict[str, Any],
    state: sqlite3.Row | None,
) -> int:
    status, body, headers = fetch_url(source["url"], state)
    if status == 304:
        update_state(connection, source["id"], success=True)
        return 0
    text = body.decode("utf-8", errors="replace")
    normalized = strip_markup(text)
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    previous_hash = state["content_hash"] if state else None
    inserted = 0
    if previous_hash and previous_hash != content_hash:
        event = Event(
            source_id=source["id"],
            category=source["category"],
            title=f"{source['name']} 页面发生变化，需人工核验 ({content_hash[:10]})",
            url=source["url"],
            published_at=None,
            source_tier=source["source_tier"],
            confidence=float(source["confidence"]),
            impact=int(source["impact"]),
            requires_review=True,
            excerpt=normalized[:800],
            raw={"previous_hash": previous_hash, "content_hash": content_hash},
        )
        inserted = insert_events(connection, [event], cutoff=datetime.min.replace(tzinfo=UTC))
    update_state(
        connection,
        source["id"],
        success=True,
        etag=headers.get("ETag"),
        last_modified=headers.get("Last-Modified"),
        content_hash=content_hash,
    )
    return inserted


def process_source(
    connection: sqlite3.Connection,
    source: dict[str, Any],
    state: sqlite3.Row | None,
    now: datetime,
    bootstrap_hours: int,
) -> int:
    source_type = source["type"]
    cutoff = now - timedelta(hours=int(source.get("bootstrap_hours", bootstrap_hours)))
    if source_type == "rss":
        status, payload, headers = fetch_url(source["url"], state)
        if status == 304:
            update_state(connection, source["id"], success=True)
            return 0
        events = parse_feed(payload, source)
        inserted = insert_events(connection, events, cutoff=cutoff)
        update_state(
            connection,
            source["id"],
            success=True,
            etag=headers.get("ETag"),
            last_modified=headers.get("Last-Modified"),
        )
        return inserted
    if source_type == "github_releases":
        inserted = insert_events(connection, github_releases(source), cutoff=cutoff)
        update_state(connection, source["id"], success=True)
        return inserted
    if source_type == "github_commits":
        inserted = insert_events(connection, github_commits(source), cutoff=cutoff)
        update_state(connection, source["id"], success=True)
        return inserted
    if source_type == "page_hash":
        return process_page_hash(connection, source, state)
    if source_type == "manual":
        update_state(connection, source["id"], success=True)
        return 0
    raise ValueError(f"Unsupported source type: {source_type}")


def export_markdown(connection: sqlite3.Connection, path: Path, hours: int = 168, limit: int = 80) -> None:
    cutoff = isoformat(utc_now() - timedelta(hours=hours))
    rows = connection.execute(
        """
        SELECT * FROM events
        WHERE discovered_at >= ?
        ORDER BY impact DESC, COALESCE(published_at, discovered_at) DESC
        LIMIT ?
        """,
        (cutoff, limit),
    ).fetchall()
    lines = [
        "# Authority Radar 事件收件箱",
        "",
        f"> 生成时间（UTC）：{isoformat()}。这是确定性采集结果，不是事实结论；标记复核的条目不得直接执行。",
        "",
    ]
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row)
    if not rows:
        lines.extend(["本窗口没有新事件。采集器仍正常完成检查。", ""])
    for category, category_rows in grouped.items():
        lines.extend([f"## {CATEGORY_LABELS.get(category, category)}", ""])
        for row in category_rows:
            published = row["published_at"] or "未找到明确发布时间"
            review = "是" if row["requires_review"] else "否"
            lines.extend(
                [
                    f"### [{row['title']}]({row['url']})",
                    "",
                    f"- 发布时间：{published}",
                    f"- 来源层级：{row['source_tier']}",
                    f"- 置信度：{row['confidence']:.2f}",
                    f"- 影响等级：P{max(0, 4 - int(row['impact']))}",
                    f"- requires_review：{review}",
                    f"- event_id：`{row['event_key']}`",
                ]
            )
            if row["excerpt"]:
                lines.append(f"- 原始摘要：{row['excerpt']}")
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text("\n".join(lines), encoding="utf-8")
    temp_path.replace(path)


def export_health(
    connection: sqlite3.Connection,
    path: Path,
    run_id: int,
    sources: list[dict[str, Any]],
) -> None:
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    failures = connection.execute(
        """
        SELECT source_id, last_checked_at, last_error, failure_count, next_retry_at, last_status_code
        FROM source_state WHERE last_error IS NOT NULL
        """
    ).fetchall()
    states = {row["source_id"]: dict(row) for row in connection.execute("SELECT * FROM source_state")}
    enabled_sources = [source for source in sources if source.get("enabled", True)]
    manual_count = sum(source["type"] == "manual" for source in enabled_sources)
    checked_ids = set(states)
    payload = {
        "generated_at": isoformat(),
        "run": dict(run),
        "failing_sources": [dict(row) for row in failures],
        "coverage": {
            "configured": len(enabled_sources),
            "automated": len(enabled_sources) - manual_count,
            "manual": manual_count,
            "checked": len(checked_ids),
            "never_checked": [source["id"] for source in enabled_sources if source["id"] not in checked_ids],
            "healthy": sum(
                source["id"] in states and not states[source["id"]]["last_error"]
                for source in enabled_sources
            ),
            "failing": len(failures),
        },
        "event_counts": {
            row["category"]: row["count"]
            for row in connection.execute("SELECT category, COUNT(*) AS count FROM events GROUP BY category")
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def load_registry(path: Path) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    ids = [source["id"] for source in registry["sources"]]
    if len(ids) != len(set(ids)):
        raise ValueError("source ids must be unique")
    return registry


def run(args: argparse.Namespace) -> int:
    registry = load_registry(args.config)
    args.database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    init_database(connection)
    connection.execute(
        """
        UPDATE runs
        SET finished_at = ?, status = 'interrupted', errors_json = '[{"error":"collector stopped before completion"}]'
        WHERE status = 'running'
        """,
        (isoformat(),),
    )
    started_at = isoformat()
    cursor = connection.execute("INSERT INTO runs(started_at, status) VALUES (?, 'running')", (started_at,))
    run_id = int(cursor.lastrowid)
    connection.commit()

    checked = 0
    inserted = 0
    errors: list[dict[str, str]] = []
    now = utc_now()
    for source in registry["sources"]:
        if not source.get("enabled", True):
            continue
        state = get_state(connection, source["id"])
        if not is_due(state, source, now) and not args.force:
            continue
        checked += 1
        try:
            inserted += process_source(connection, source, state, now, args.bootstrap_hours)
        except Exception as exc:  # noqa: BLE001 - source errors are isolated by design
            message = normalize_text(str(exc))[:500]
            errors.append({"source_id": source["id"], "error": message})
            status_code = exc.code if isinstance(exc, urllib.error.HTTPError) else None
            update_state(connection, source["id"], success=False, error=message, status_code=status_code)
        connection.commit()

    status = "success" if not errors else "success_with_errors"
    connection.execute(
        """
        UPDATE runs SET finished_at = ?, status = ?, sources_checked = ?, events_new = ?, errors_json = ?
        WHERE run_id = ?
        """,
        (isoformat(), status, checked, inserted, json.dumps(errors, ensure_ascii=False), run_id),
    )
    connection.commit()
    export_markdown(connection, args.export, hours=args.export_hours, limit=args.export_limit)
    export_health(connection, args.health, run_id, registry["sources"])
    print(
        json.dumps(
            {"run_id": run_id, "status": status, "sources_checked": checked, "events_new": inserted, "errors": errors},
            ensure_ascii=False,
        )
    )
    connection.close()
    return 2 if errors and args.strict else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect high-authority events without an LLM dependency.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--bootstrap-hours", type=int, default=336)
    parser.add_argument("--export-hours", type=int, default=168)
    parser.add_argument("--export-limit", type=int, default=20)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Return a non-zero exit code when any source fails.")
    return parser


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
