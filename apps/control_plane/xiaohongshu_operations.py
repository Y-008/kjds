"""Governed Xiaohongshu operator research & runbook contract kernel (OPS-XHS-001 prep-only slice).

Freezes the platform-specific operator layer on top of the BAS-178 social
intelligence workspace and analysis contracts: the pinned ``xiaohongshu-cli``
source binding, the seven research baseline dimensions, the output taxonomy
(reused from the BAS-178 analysis outputs), and clearly-synthetic research
questions / content hypotheses / campaign draft templates plus the operator
runbook. Real account binding, platform writes and any external write are not
admitted here; real execution requires an account grant and readback.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

XHS_OPERATIONS_CONTRACT = "kjds-xiaohongshu-operations-v1"
XHS_RESEARCH_CONTRACT = "kjds-xiaohongshu-research-plan-v1"
XHS_RUNBOOK_CONTRACT = "kjds-xiaohongshu-operator-runbook-v1"

PLATFORM = "xiaohongshu"
CLI_VERSION = "0.6.4"
CLI_UPSTREAM = "https://github.com/jackwener/xiaohongshu-cli.git"
CLI_PINNED_COMMIT = "4d63f3c0c85ccd9054fa8e96d7f761aaf2507449"
SOURCE_RANK = "operator_cli_or_browser"

RESEARCH_BASELINE_DIMENSIONS = (
    "search",
    "notes",
    "comments_and_sub_comments",
    "users",
    "topics",
    "notifications",
    "owned_content",
)

# Reused from the BAS-178 analysis outputs; this kernel does not re-implement them.
OUTPUT_TAXONOMY = (
    "seller_segmentation",
    "comment_intent",
    "content_structure",
    "product_demand",
    "calendar",
    "campaign_drafts",
)

OPERATOR_MODES = ("Setup", "Doctor", "LoginQr", "LoginBrowser", "Run", "Test")

REAL_ACCOUNT_ADMITTED = False
REAL_WRITE_REQUIRES_READBACK = True
ACCOUNT_BINDING_REQUIRED = True

# Clearly-synthetic contract fixtures; never claims about real platform data.
RESEARCH_QUESTIONS = (
    {"id": "xhs-rq-001", "dimension": "search", "question": "哪些关键词指向 Ozon 出海卖家的真实痛点", "status": "FIXTURE"},
    {"id": "xhs-rq-002", "dimension": "notes", "question": "哪些笔记结构带来高互动且可被卖家复用", "status": "FIXTURE"},
    {"id": "xhs-rq-003", "dimension": "comments_and_sub_comments", "question": "评论区高频意图与异议集中在哪些点", "status": "FIXTURE"},
    {"id": "xhs-rq-004", "dimension": "users", "question": "哪些账号类型构成目标卖家/服务商/创作者", "status": "FIXTURE"},
    {"id": "xhs-rq-005", "dimension": "topics", "question": "哪些话题与俄罗斯 Ozon 出海形成内容日历", "status": "FIXTURE"},
    {"id": "xhs-rq-006", "dimension": "notifications", "question": "平台通知与规则变化如何影响内容策略", "status": "FIXTURE"},
    {"id": "xhs-rq-007", "dimension": "owned_content", "question": "自有内容基线如何与竞品与需求对齐", "status": "FIXTURE"},
)

CONTENT_HYPOTHESES = (
    {"id": "xhs-ch-001", "hypothesis": "痛点与补证型笔记比纯种草更能吸引出海卖家", "status": "FIXTURE"},
    {"id": "xhs-ch-002", "hypothesis": "分步可复现的运营清单比宏大叙事转化更高", "status": "FIXTURE"},
    {"id": "xhs-ch-003", "hypothesis": "证据优先而非增长保证的 framing 更可信", "status": "FIXTURE"},
)

CAMPAIGN_DRAFT_TEMPLATES = (
    {"id": "xhs-cd-001", "format": "note", "template": "痛点 + 证据 + 受控动作 + 下一动作", "status": "FIXTURE"},
    {"id": "xhs-cd-002", "format": "video", "template": "三秒钩子 + 过程复盘 + 止损结论", "status": "FIXTURE"},
    {"id": "xhs-cd-003", "format": "live", "template": "问答 + 案例拆解 + 预约诊断", "status": "FIXTURE"},
)

OPERATOR_RUNBOOK_STEPS = (
    {"step": 1, "mode": "Setup", "action": "隔离安装并固定 xiaohongshu-cli checkout", "readback": "git rev-parse HEAD == pinned commit"},
    {"step": 2, "mode": "Doctor", "action": "校验工具链与运行时健康", "readback": "Doctor 退出码为 0"},
    {"step": 3, "mode": "LoginQr", "action": "专用二维码账号建立基线", "readback": "记录 account ref 与 campaign grant"},
    {"step": 4, "mode": "LoginBrowser", "action": "显式 CookieSource 降级登录", "readback": "Cookie 仅写入隔离 profile"},
    {"step": 5, "mode": "Run", "action": "按研究计划采集搜索/笔记/评论/用户/话题/通知/自有内容", "readback": "采集记录 content-addressed 入 Observation"},
    {"step": 6, "mode": "Test", "action": "写前必须读回；无 grant 不真实执行", "readback": "写后读回一致性核验"},
)

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

SENSITIVE_MARKERS = (
    "authorization:",
    "bearer ",
    "cookie=",
    "api_key=",
    "access_token=",
    "refresh_token=",
    "client_secret=",
    "password=",
    "private_key=",
    "sk-",
)

ZERO_AUTHORITY_KEYS = frozenset(
    {
        "formal_fact",
        "finance_entry",
        "approval",
        "permit",
        "pilot",
        "outbox",
        "canonical_graph_write",
        "dependency_install",
        "network",
        "external_write",
        "platform_write",
    }
)


class XiaohongshuOperationsError(ValueError):
    """Stable, non-sensitive contract failure for Xiaohongshu operator research/runbook."""


@dataclass(frozen=True)
class SourceBinding:
    status: str
    contract_id: str
    platform: str
    version: str
    upstream: str
    pinned_commit: str
    source_rank: str
    real_account_admitted: bool
    external_write_allowed: bool
    binding_sha256: str


@dataclass(frozen=True)
class ResearchPlan:
    contract_id: str
    platform: str
    baseline_dimensions: tuple[str, ...]
    questions: tuple[dict[str, str], ...]
    output_taxonomy: tuple[str, ...]
    synthetic_fixture: bool
    external_write_allowed: bool
    plan_sha256: str


@dataclass(frozen=True)
class ContentHypothesesSet:
    contract_id: str
    platform: str
    hypotheses: tuple[dict[str, str], ...]
    synthetic_fixture: bool
    external_write_allowed: bool
    hypotheses_sha256: str


@dataclass(frozen=True)
class CampaignDraftTemplatesSet:
    contract_id: str
    platform: str
    templates: tuple[dict[str, str], ...]
    synthetic_fixture: bool
    external_write_allowed: bool
    templates_sha256: str


@dataclass(frozen=True)
class OperatorRunbook:
    contract_id: str
    platform: str
    modes: tuple[str, ...]
    steps: tuple[dict[str, Any], ...]
    real_write_requires_readback: bool
    account_binding_required: bool
    external_write_allowed: bool
    runbook_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise XiaohongshuOperationsError(f"{name}_invalid")
    if len(value) > maximum:
        raise XiaohongshuOperationsError(f"{name}_too_long")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if IDEMPOTENCY_PATTERN.fullmatch(text) is None:
        raise XiaohongshuOperationsError(f"{name}_invalid")
    return text


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise XiaohongshuOperationsError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise XiaohongshuOperationsError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise XiaohongshuOperationsError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise XiaohongshuOperationsError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise XiaohongshuOperationsError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class GovernedXiaohongshuOperations:
    """Deterministic Xiaohongshu operator research & runbook contract kernel."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def bind_source(self, *, version: str | None = None, commit: str | None = None) -> SourceBinding:
        version = _text(version or CLI_VERSION, "version", maximum=40)
        commit = _text(commit or CLI_PINNED_COMMIT, "commit", maximum=64)
        if version != CLI_VERSION:
            raise XiaohongshuOperationsError("cli_version_mismatch")
        if commit != CLI_PINNED_COMMIT:
            raise XiaohongshuOperationsError("cli_commit_mismatch")
        document = {
            "contract_id": XHS_OPERATIONS_CONTRACT,
            "platform": PLATFORM,
            "version": version,
            "upstream": CLI_UPSTREAM,
            "pinned_commit": commit,
            "source_rank": SOURCE_RANK,
            "real_account_admitted": REAL_ACCOUNT_ADMITTED,
            "external_write_allowed": False,
        }
        return SourceBinding(
            status="BOUND",
            contract_id=XHS_OPERATIONS_CONTRACT,
            platform=PLATFORM,
            version=version,
            upstream=CLI_UPSTREAM,
            pinned_commit=commit,
            source_rank=SOURCE_RANK,
            real_account_admitted=REAL_ACCOUNT_ADMITTED,
            external_write_allowed=False,
            binding_sha256=_hash(document),
        )

    def research_plan(self) -> ResearchPlan:
        document = {
            "contract_id": XHS_RESEARCH_CONTRACT,
            "platform": PLATFORM,
            "baseline_dimensions": RESEARCH_BASELINE_DIMENSIONS,
            "questions": [dict(q) for q in RESEARCH_QUESTIONS],
            "output_taxonomy": OUTPUT_TAXONOMY,
            "synthetic_fixture": True,
            "external_write_allowed": False,
        }
        return ResearchPlan(
            contract_id=XHS_RESEARCH_CONTRACT,
            platform=PLATFORM,
            baseline_dimensions=RESEARCH_BASELINE_DIMENSIONS,
            questions=RESEARCH_QUESTIONS,
            output_taxonomy=OUTPUT_TAXONOMY,
            synthetic_fixture=True,
            external_write_allowed=False,
            plan_sha256=_hash(document),
        )

    def content_hypotheses(self) -> ContentHypothesesSet:
        document = {
            "contract_id": XHS_OPERATIONS_CONTRACT,
            "platform": PLATFORM,
            "hypotheses": [dict(h) for h in CONTENT_HYPOTHESES],
            "synthetic_fixture": True,
            "external_write_allowed": False,
        }
        return ContentHypothesesSet(
            contract_id=XHS_OPERATIONS_CONTRACT,
            platform=PLATFORM,
            hypotheses=CONTENT_HYPOTHESES,
            synthetic_fixture=True,
            external_write_allowed=False,
            hypotheses_sha256=_hash(document),
        )

    def campaign_draft_templates(self) -> CampaignDraftTemplatesSet:
        document = {
            "contract_id": XHS_OPERATIONS_CONTRACT,
            "platform": PLATFORM,
            "templates": [dict(t) for t in CAMPAIGN_DRAFT_TEMPLATES],
            "synthetic_fixture": True,
            "external_write_allowed": False,
        }
        return CampaignDraftTemplatesSet(
            contract_id=XHS_OPERATIONS_CONTRACT,
            platform=PLATFORM,
            templates=CAMPAIGN_DRAFT_TEMPLATES,
            synthetic_fixture=True,
            external_write_allowed=False,
            templates_sha256=_hash(document),
        )

    def operator_runbook(self) -> OperatorRunbook:
        document = {
            "contract_id": XHS_RUNBOOK_CONTRACT,
            "platform": PLATFORM,
            "modes": OPERATOR_MODES,
            "steps": [dict(s) for s in OPERATOR_RUNBOOK_STEPS],
            "real_write_requires_readback": REAL_WRITE_REQUIRES_READBACK,
            "account_binding_required": ACCOUNT_BINDING_REQUIRED,
            "external_write_allowed": False,
        }
        return OperatorRunbook(
            contract_id=XHS_RUNBOOK_CONTRACT,
            platform=PLATFORM,
            modes=OPERATOR_MODES,
            steps=OPERATOR_RUNBOOK_STEPS,
            real_write_requires_readback=REAL_WRITE_REQUIRES_READBACK,
            account_binding_required=ACCOUNT_BINDING_REQUIRED,
            external_write_allowed=False,
            runbook_sha256=_hash(document),
        )

    def readback(self, obj: Any, *, observed: str | None = None) -> dict[str, Any]:
        if isinstance(obj, SourceBinding):
            digest = obj.binding_sha256
        elif isinstance(obj, ResearchPlan):
            digest = obj.plan_sha256
        elif isinstance(obj, ContentHypothesesSet):
            digest = obj.hypotheses_sha256
        elif isinstance(obj, CampaignDraftTemplatesSet):
            digest = obj.templates_sha256
        elif isinstance(obj, OperatorRunbook):
            digest = obj.runbook_sha256
        else:
            raise XiaohongshuOperationsError("readback_target_invalid")
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        integrity_ok = observed_hash == digest
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "CampaignDraftTemplatesSet",
    "ContentHypothesesSet",
    "OperatorRunbook",
    "ResearchPlan",
    "SourceBinding",
    "GovernedXiaohongshuOperations",
    "XiaohongshuOperationsError",
    "ACCOUNT_BINDING_REQUIRED",
    "CLI_PINNED_COMMIT",
    "CLI_UPSTREAM",
    "CLI_VERSION",
    "OPERATOR_MODES",
    "OPERATOR_RUNBOOK_STEPS",
    "OUTPUT_TAXONOMY",
    "PLATFORM",
    "REAL_ACCOUNT_ADMITTED",
    "REAL_WRITE_REQUIRES_READBACK",
    "RESEARCH_BASELINE_DIMENSIONS",
    "RESEARCH_QUESTIONS",
    "SOURCE_RANK",
    "XHS_OPERATIONS_CONTRACT",
    "XHS_RESEARCH_CONTRACT",
    "XHS_RUNBOOK_CONTRACT",
    "ZERO_AUTHORITY_KEYS",
]
