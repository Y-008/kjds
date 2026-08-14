"""Governed Douyin operator research & runbook contract kernel (OPS-DY-001 prep-only slice).

Freezes the platform-specific operator layer on top of the BAS-178 social
intelligence workspace and analysis contracts: official OAuth / creator-center
as the primary source rank with dedicated browser as fallback, the seven Douyin
research baseline dimensions, the output taxonomy (reused from BAS-178), and
clearly-synthetic research questions / content hypotheses / campaign draft
templates plus the operator runbook and the source-interruption adapter
resolution loop. Real account binding, platform writes and any external write
are not admitted here; real execution requires an account grant and readback.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DOUYIN_OPERATIONS_CONTRACT = "kjds-douyin-operations-v1"
DOUYIN_RESEARCH_CONTRACT = "kjds-douyin-research-plan-v1"
DOUYIN_RUNBOOK_CONTRACT = "kjds-douyin-operator-runbook-v1"
DOUYIN_ADAPTER_LOOP_CONTRACT = "kjds-douyin-adapter-resolution-loop-v1"

PLATFORM = "douyin"
PRIMARY_SOURCE_RANK = "official_oauth_or_creator_center"
FALLBACK_SOURCE_RANK = "dedicated_browser"
SOURCE_RANKS = (PRIMARY_SOURCE_RANK, FALLBACK_SOURCE_RANK)

RESEARCH_BASELINE_DIMENSIONS = (
    "video_hooks",
    "pacing",
    "comment_intent",
    "creator_product_match",
    "live_short_video_funnel",
    "authorized_account_metrics",
    "content_campaign_baseline",
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

OPERATOR_MODES = ("SetupOAuth", "SetupBrowser", "Baseline", "Research", "Campaign", "Readback")

REAL_ACCOUNT_ADMITTED = False
REAL_WRITE_REQUIRES_READBACK = True
ACCOUNT_BINDING_REQUIRED = True

# Clearly-synthetic contract fixtures; never claims about real platform data.
RESEARCH_QUESTIONS = (
    {"id": "dy-rq-001", "dimension": "video_hooks", "question": "哪些三秒钩子在高互动短视频中可复用", "status": "FIXTURE"},
    {"id": "dy-rq-002", "dimension": "pacing", "question": "什么发布节奏与内容节奏可以持续", "status": "FIXTURE"},
    {"id": "dy-rq-003", "dimension": "comment_intent", "question": "评论区意图与异议集中在哪些点", "status": "FIXTURE"},
    {"id": "dy-rq-004", "dimension": "creator_product_match", "question": "哪些创作者与目标商品/卖家匹配", "status": "FIXTURE"},
    {"id": "dy-rq-005", "dimension": "live_short_video_funnel", "question": "直播与短视频漏斗在哪个环节流失", "status": "FIXTURE"},
    {"id": "dy-rq-006", "dimension": "authorized_account_metrics", "question": "授权账号哪些指标构成基线", "status": "FIXTURE"},
    {"id": "dy-rq-007", "dimension": "content_campaign_baseline", "question": "内容 campaign 基线如何建立", "status": "FIXTURE"},
)

CONTENT_HYPOTHESES = (
    {"id": "dy-ch-001", "hypothesis": "三秒钩子 + 过程复盘比硬广转化更高", "status": "FIXTURE"},
    {"id": "dy-ch-002", "hypothesis": "短平快节奏 + 可复现清单更适合短视频", "status": "FIXTURE"},
    {"id": "dy-ch-003", "hypothesis": "证据优先、受控动作比增长保证更可信", "status": "FIXTURE"},
)

CAMPAIGN_DRAFT_TEMPLATES = (
    {"id": "dy-cd-001", "format": "short_video", "template": "三秒钩子 + 过程复盘 + 止损结论", "status": "FIXTURE"},
    {"id": "dy-cd-002", "format": "live", "template": "问答 + 案例拆解 + 预约诊断", "status": "FIXTURE"},
    {"id": "dy-cd-003", "format": "creator_collab", "template": "创作者/商品匹配 + 受控任务 + 效果复读", "status": "FIXTURE"},
)

OPERATOR_RUNBOOK_STEPS = (
    {"step": 1, "mode": "SetupOAuth", "action": "官方 OAuth/创作者中心优先建立授权身份", "readback": "授权 scope 与 account ref 记录"},
    {"step": 2, "mode": "SetupBrowser", "action": "专用浏览器降级登录", "readback": "profile 隔离且 Cookie 不落仓"},
    {"step": 3, "mode": "Baseline", "action": "授权账号指标建立基线", "readback": "指标 content-addressed"},
    {"step": 4, "mode": "Research", "action": "采集视频钩子/节奏/评论/匹配/漏斗", "readback": "Observation content-addressed"},
    {"step": 5, "mode": "Campaign", "action": "内容 campaign 草案", "readback": "campaign spec content-addressed"},
    {"step": 6, "mode": "Readback", "action": "来源中断进入 Adapter 解决 Loop；写前读回、无 grant 不真实执行", "readback": "写后读回一致性核验"},
)

ADAPTER_RESOLUTION_LOOP = (
    {"step": 1, "phase": "detect", "action": "来源中断/漂移被识别", "gate": "source_interrupted"},
    {"step": 2, "phase": "quarantine", "action": "受影响记录隔离，不伪造", "gate": "conservation_holds"},
    {"step": 3, "phase": "diagnose", "action": "区分账号/权限/限流/平台变更", "gate": "root_cause_classified"},
    {"step": 4, "phase": "retry_or_fallback", "action": "有界重试或降级到专用浏览器", "gate": "bounded_retry"},
    {"step": 5, "phase": "readback", "action": "恢复后写前读回", "gate": "readback_verified"},
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


class DouyinOperationsError(ValueError):
    """Stable, non-sensitive contract failure for Douyin operator research/runbook."""


@dataclass(frozen=True)
class SourceBinding:
    status: str
    contract_id: str
    platform: str
    source_rank: str
    fallback_source_rank: str
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


@dataclass(frozen=True)
class AdapterLoop:
    contract_id: str
    platform: str
    steps: tuple[dict[str, str], ...]
    external_write_allowed: bool
    loop_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise DouyinOperationsError(f"{name}_invalid")
    if len(value) > maximum:
        raise DouyinOperationsError(f"{name}_too_long")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if IDEMPOTENCY_PATTERN.fullmatch(text) is None:
        raise DouyinOperationsError(f"{name}_invalid")
    return text


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise DouyinOperationsError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise DouyinOperationsError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise DouyinOperationsError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise DouyinOperationsError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise DouyinOperationsError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class GovernedDouyinOperations:
    """Deterministic Douyin operator research & runbook contract kernel."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def bind_source(self, *, source_rank: str | None = None) -> SourceBinding:
        rank = _text(source_rank or PRIMARY_SOURCE_RANK, "source_rank", maximum=80)
        if rank not in SOURCE_RANKS:
            raise DouyinOperationsError("source_rank_not_recognized")
        document = {
            "contract_id": DOUYIN_OPERATIONS_CONTRACT,
            "platform": PLATFORM,
            "source_rank": rank,
            "fallback_source_rank": FALLBACK_SOURCE_RANK,
            "real_account_admitted": REAL_ACCOUNT_ADMITTED,
            "external_write_allowed": False,
        }
        return SourceBinding(
            status="BOUND",
            contract_id=DOUYIN_OPERATIONS_CONTRACT,
            platform=PLATFORM,
            source_rank=rank,
            fallback_source_rank=FALLBACK_SOURCE_RANK,
            real_account_admitted=REAL_ACCOUNT_ADMITTED,
            external_write_allowed=False,
            binding_sha256=_hash(document),
        )

    def research_plan(self) -> ResearchPlan:
        document = {
            "contract_id": DOUYIN_RESEARCH_CONTRACT,
            "platform": PLATFORM,
            "baseline_dimensions": RESEARCH_BASELINE_DIMENSIONS,
            "questions": [dict(q) for q in RESEARCH_QUESTIONS],
            "output_taxonomy": OUTPUT_TAXONOMY,
            "synthetic_fixture": True,
            "external_write_allowed": False,
        }
        return ResearchPlan(
            contract_id=DOUYIN_RESEARCH_CONTRACT,
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
            "contract_id": DOUYIN_OPERATIONS_CONTRACT,
            "platform": PLATFORM,
            "hypotheses": [dict(h) for h in CONTENT_HYPOTHESES],
            "synthetic_fixture": True,
            "external_write_allowed": False,
        }
        return ContentHypothesesSet(
            contract_id=DOUYIN_OPERATIONS_CONTRACT,
            platform=PLATFORM,
            hypotheses=CONTENT_HYPOTHESES,
            synthetic_fixture=True,
            external_write_allowed=False,
            hypotheses_sha256=_hash(document),
        )

    def campaign_draft_templates(self) -> CampaignDraftTemplatesSet:
        document = {
            "contract_id": DOUYIN_OPERATIONS_CONTRACT,
            "platform": PLATFORM,
            "templates": [dict(t) for t in CAMPAIGN_DRAFT_TEMPLATES],
            "synthetic_fixture": True,
            "external_write_allowed": False,
        }
        return CampaignDraftTemplatesSet(
            contract_id=DOUYIN_OPERATIONS_CONTRACT,
            platform=PLATFORM,
            templates=CAMPAIGN_DRAFT_TEMPLATES,
            synthetic_fixture=True,
            external_write_allowed=False,
            templates_sha256=_hash(document),
        )

    def operator_runbook(self) -> OperatorRunbook:
        document = {
            "contract_id": DOUYIN_RUNBOOK_CONTRACT,
            "platform": PLATFORM,
            "modes": OPERATOR_MODES,
            "steps": [dict(s) for s in OPERATOR_RUNBOOK_STEPS],
            "real_write_requires_readback": REAL_WRITE_REQUIRES_READBACK,
            "account_binding_required": ACCOUNT_BINDING_REQUIRED,
            "external_write_allowed": False,
        }
        return OperatorRunbook(
            contract_id=DOUYIN_RUNBOOK_CONTRACT,
            platform=PLATFORM,
            modes=OPERATOR_MODES,
            steps=OPERATOR_RUNBOOK_STEPS,
            real_write_requires_readback=REAL_WRITE_REQUIRES_READBACK,
            account_binding_required=ACCOUNT_BINDING_REQUIRED,
            external_write_allowed=False,
            runbook_sha256=_hash(document),
        )

    def adapter_resolution_loop(self) -> AdapterLoop:
        document = {
            "contract_id": DOUYIN_ADAPTER_LOOP_CONTRACT,
            "platform": PLATFORM,
            "steps": [dict(s) for s in ADAPTER_RESOLUTION_LOOP],
            "external_write_allowed": False,
        }
        return AdapterLoop(
            contract_id=DOUYIN_ADAPTER_LOOP_CONTRACT,
            platform=PLATFORM,
            steps=ADAPTER_RESOLUTION_LOOP,
            external_write_allowed=False,
            loop_sha256=_hash(document),
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
        elif isinstance(obj, AdapterLoop):
            digest = obj.loop_sha256
        else:
            raise DouyinOperationsError("readback_target_invalid")
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
    "AdapterLoop",
    "CampaignDraftTemplatesSet",
    "ContentHypothesesSet",
    "OperatorRunbook",
    "ResearchPlan",
    "SourceBinding",
    "GovernedDouyinOperations",
    "DouyinOperationsError",
    "ACCOUNT_BINDING_REQUIRED",
    "ADAPTER_RESOLUTION_LOOP",
    "DOUYIN_ADAPTER_LOOP_CONTRACT",
    "DOUYIN_OPERATIONS_CONTRACT",
    "DOUYIN_RESEARCH_CONTRACT",
    "DOUYIN_RUNBOOK_CONTRACT",
    "FALLBACK_SOURCE_RANK",
    "OPERATOR_MODES",
    "OPERATOR_RUNBOOK_STEPS",
    "OUTPUT_TAXONOMY",
    "PLATFORM",
    "PRIMARY_SOURCE_RANK",
    "REAL_ACCOUNT_ADMITTED",
    "REAL_WRITE_REQUIRES_READBACK",
    "RESEARCH_BASELINE_DIMENSIONS",
    "RESEARCH_QUESTIONS",
    "SOURCE_RANKS",
    "ZERO_AUTHORITY_KEYS",
]
