from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

from scripts.authority_radar.collect import isoformat
from scripts.authority_radar.report import write_atomic

SYSTEM_PROMPT = """你是 KJDS 权威情报分析员。你只能使用用户消息里的证据，不浏览网页、不调用工具、不补造事实。
输出中文 Markdown，严格使用二级标题：Executive Signal、AI 前沿、企业端 AI、跨境电商与国内平台、Agent 基建、实验与审批。
每个判断要区分事实与推断；给出置信度。实验标 L0-L4：L0 只读采集，L1 本地草稿，L2 受控外部读取，L3 平台写操作需人工批准，L4 资金/法律/账号权限禁止自治。
每个事实判断必须原样引用至少一个 evidence 中的 event_id；全文至少引用两个不同 event_id。
requires_review 或失败来源只能列为待核验，不得写成确定结论。不要自我介绍。"""

REQUIRED_HEADINGS = (
    "## Executive Signal",
    "## AI 前沿",
    "## 企业端 AI",
    "## 跨境电商与国内平台",
    "## Agent 基建",
    "## 实验与审批",
)
VERSION_PATTERN = re.compile(
    r"\b(?:GPT|GLM|Gemini|Claude|Gemma|OpenClaw|n8n|MCP)[-\s:]?v?\d+(?:\.\d+){0,3}(?:-[A-Za-z0-9.]+)?",
    re.IGNORECASE,
)
EVENT_ID_PATTERN = re.compile(r"\b[a-f0-9]{64}\b")


def validate_analysis(evidence: str, analysis: str) -> list[str]:
    reasons = []
    for heading in REQUIRED_HEADINGS:
        if heading not in analysis:
            reasons.append(f"missing heading: {heading}")

    evidence_years = set(re.findall(r"\b20\d{2}\b", evidence))
    invented_years = sorted(set(re.findall(r"\b20\d{2}\b", analysis)) - evidence_years)
    if invented_years:
        reasons.append(f"years absent from evidence: {', '.join(invented_years)}")

    evidence_versions = {item.lower() for item in VERSION_PATTERN.findall(evidence)}
    invented_versions = sorted({item.lower() for item in VERSION_PATTERN.findall(analysis)} - evidence_versions)
    if invented_versions:
        reasons.append(f"versions absent from evidence: {', '.join(invented_versions)}")

    evidence_event_ids = set(EVENT_ID_PATTERN.findall(evidence))
    cited_event_ids = set(EVENT_ID_PATTERN.findall(analysis))
    if len(cited_event_ids & evidence_event_ids) < 2:
        reasons.append("fewer than two valid evidence event_ids cited")
    if cited_event_ids - evidence_event_ids:
        reasons.append("analysis contains event_ids absent from evidence")
    return reasons


def ollama_chat(endpoint: str, model: str, evidence: str, timeout: int) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": evidence},
        ],
        "options": {"temperature": 0.15},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read())
    content = result.get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("Ollama returned an empty analysis")
    return content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mirror", type=Path)
    parser.add_argument("--rejected", type=Path)
    parser.add_argument("--model", default="gemma4:26b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-chars", type=int, default=24000)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    health = args.health.read_text(encoding="utf-8")
    events = args.events.read_text(encoding="utf-8")
    evidence = f"采集健康：\n{health}\n\n事件收件箱：\n{events}"[: args.max_chars]
    try:
        candidate = ollama_chat(args.endpoint, args.model, evidence, args.timeout)
        rejection_reasons = validate_analysis(evidence, candidate)
        if rejection_reasons:
            status = "rejected"
            if args.rejected:
                write_atomic(args.rejected, candidate)
            reasons = "\n".join(f"- {reason}" for reason in rejection_reasons)
            analysis = (
                "## Candidate rejected by evidence gate\n\n"
                f"{reasons}\n\n"
                "- 候选分析没有晋级到长期记忆；请直接使用权威事件收件箱和晨间就绪战报。"
            )
        else:
            status = "success"
            analysis = candidate
    except Exception as exc:  # noqa: BLE001 - the deterministic layer must still publish a degraded artifact
        status = "degraded"
        analysis = f"## AI analysis unavailable\n\n- {type(exc).__name__}: {exc}\n- 确定性采集结果仍可使用。"

    document = "\n".join(
        [
            "# KJDS 权威 AI 决策雷达",
            "",
            f"> 生成时间（UTC）：{isoformat()}｜本地模型：{args.model}｜状态：{status}",
            "",
            analysis,
            "",
            "---",
            "本报告是决策输入，不是平台写操作、法律意见或资金授权。",
            "",
        ]
    )
    write_atomic(args.output, document)
    if args.mirror:
        write_atomic(args.mirror, document)
    if args.stdout:
        print(document)
    return 0 if status in {"success", "rejected"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
