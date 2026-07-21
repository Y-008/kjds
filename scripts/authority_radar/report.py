from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from scripts.authority_radar.collect import CATEGORY_LABELS, isoformat


def render_report(connection: sqlite3.Connection) -> str:
    connection.row_factory = sqlite3.Row
    last_collection = connection.execute(
        "SELECT * FROM runs WHERE sources_checked > 0 ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    latest_run = connection.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    failing = connection.execute(
        "SELECT source_id, last_checked_at, last_error FROM source_state WHERE last_error IS NOT NULL ORDER BY source_id"
    ).fetchall()
    source_count = connection.execute("SELECT COUNT(*) FROM source_state").fetchone()[0]
    event_count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    categories = connection.execute(
        "SELECT category, COUNT(*) AS count FROM events GROUP BY category ORDER BY count DESC"
    ).fetchall()
    top_events = connection.execute(
        """
        SELECT title, url, category, source_tier, confidence, impact, requires_review, published_at
        FROM events
        ORDER BY impact DESC, COALESCE(published_at, discovered_at) DESC
        LIMIT 8
        """
    ).fetchall()

    lines = [
        "# KJDS 晨间就绪战报",
        "",
        f"> 生成时间（UTC）：{isoformat()}",
        "",
        "## Result",
        "",
        f"- 最新调度：{latest_run['status'] if latest_run else 'unknown'}",
        f"- 最近实际采集：{last_collection['status'] if last_collection else 'unknown'}",
        f"- 已建立来源状态：{source_count}",
        f"- 累计去重事件：{event_count}",
        f"- 当前失败来源：{len(failing)}",
        "",
        "## Coverage",
        "",
    ]
    if categories:
        for row in categories:
            lines.append(f"- {CATEGORY_LABELS.get(row['category'], row['category'])}：{row['count']}")
    else:
        lines.append("- 暂无事件；采集器仍保留运行记录。")

    lines.extend(["", "## High-signal events", ""])
    for row in top_events:
        review = "；需复核" if row["requires_review"] else ""
        published = row["published_at"] or "未找到明确发布时间"
        lines.append(
            f"- [{row['title']}]({row['url']})｜{published}｜{row['source_tier']}｜"
            f"置信度 {row['confidence']:.2f}｜影响 {row['impact']}{review}"
        )
    if not top_events:
        lines.append("- 无。")

    lines.extend(["", "## Uncertainty", ""])
    if failing:
        for row in failing:
            lines.append(f"- `{row['source_id']}`：{row['last_error']}（{row['last_checked_at']}）")
    else:
        lines.append("- 当前没有已知采集失败。")

    lines.extend(
        [
            "",
            "## Needs Review",
            "",
            "- 页面变化信号、反爬摘要及二手材料必须人工核验后才能进入经营结论。",
            "- 平台商品、价格、广告、订单、客户消息、资金和账户权限写操作一律不得自动执行。",
            "",
        ]
    )
    return "\n".join(lines)


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mirror", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    connection = sqlite3.connect(args.database)
    report = render_report(connection)
    connection.close()
    write_atomic(args.output, report)
    if args.mirror:
        write_atomic(args.mirror, report)
    if args.stdout:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
