"""Scenario-aware evidence class policy (BAS-104 follow-up).

Architecture guidance from the operator: the evidence layer is mandatory in
every scenario, but the full "three Passports" machinery is only required
where automation or regulation amplifies the cost of a wrong action:

- ``manual_small``: a few ordinary SKUs listed manually. Database + object
  storage with the six basic evidence roles is enough; the three-Passport
  workflow is not required.
- ``auto_scale``: daily automated selection/publishing of hundreds of SKUs.
  The structured evidence layer is the "brake system"; full Passports are
  required.
- ``regulated``: branded goods, 3C, food, cosmetics, mother-and-baby and
  medical categories. Certification, labelling and claims evidence is
  mandatory and strict.
- ``eu_export``: exports to the EU. The internal Passports are NOT the EU
  Digital Product Passport (DPP) and must never be presented as such; the
  class reserves a mapping seam for future DPP field alignment.

Classification is deterministic and explicit: category flags, target market
and operation mode are fixed inputs and an explicit ``evidence_class`` always
overrides inference. No model judgement is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CONTRACT_ID = "kjds-evidence-class-policy-v1"
POLICY_VERSION = "2026-08-02.1"


class EvidenceClass(StrEnum):
    MANUAL_SMALL = "manual_small"
    AUTO_SCALE = "auto_scale"
    REGULATED = "regulated"
    EU_EXPORT = "eu_export"


# The six basic evidence roles the operator defined for scenario one.  They
# are required in EVERY class; the classes differ in whether the full
# Passport machinery and certification requirements are added on top.
BASIC_EVIDENCE_ROLES: frozenset[str] = frozenset(
    {
        "supplier_identity",
        "purchase_link",
        "product_certificate",
        "sku_mapping",
        "image_source",
        "basic_qc_result",
    }
)

# Regulated category flags: 品牌商品、3C、食品、化妆品、母婴、医疗.
REGULATED_CATEGORY_FLAGS: frozenset[str] = frozenset(
    {
        "branded",
        "3c",
        "food",
        "cosmetics",
        "baby",
        "medical",
    }
)


@dataclass(frozen=True)
class EvidenceClassPolicy:
    requires_full_passports: bool
    requires_six_basics: bool
    regulated_certificates_required: bool
    independent_approval_required: bool
    dpp_mapping: str | None
    description: str


EVIDENCE_CLASS_POLICY: dict[EvidenceClass, EvidenceClassPolicy] = {
    EvidenceClass.MANUAL_SMALL: EvidenceClassPolicy(
        requires_full_passports=False,
        requires_six_basics=True,
        regulated_certificates_required=False,
        independent_approval_required=True,
        dpp_mapping=None,
        description=(
            "少量普通百货人工上架：数据库+对象存储保存六项基础证据，"
            "不要求三 Passport 工作流，发布仍需人工确认。"
        ),
    ),
    EvidenceClass.AUTO_SCALE: EvidenceClassPolicy(
        requires_full_passports=True,
        requires_six_basics=True,
        regulated_certificates_required=False,
        independent_approval_required=True,
        dpp_mapping=None,
        description=(
            "每日自动筛选/上架：自动化放大错误，结构化证据层作为刹车，"
            "要求三 Passport 与独立人工审批。"
        ),
    ),
    EvidenceClass.REGULATED: EvidenceClassPolicy(
        requires_full_passports=True,
        requires_six_basics=True,
        regulated_certificates_required=True,
        independent_approval_required=True,
        dpp_mapping=None,
        description=(
            "品牌/3C/食品/化妆品/母婴/医疗：许可、认证、标签与宣称证据"
            "强制且严格，未满足不得自动发布。"
        ),
    ),
    EvidenceClass.EU_EXPORT: EvidenceClassPolicy(
        requires_full_passports=True,
        requires_six_basics=True,
        regulated_certificates_required=False,
        independent_approval_required=True,
        dpp_mapping="dpp-alignment-pending",
        description=(
            "欧盟市场出口：内部 Passport 不等同于欧盟 DPP，预留映射缝，"
            "字段要求随目标品类法规后续对齐。"
        ),
    ),
}


def _normalize_flags(values: Any) -> set[str]:
    if not values:
        return set()
    if isinstance(values, str):
        values = [values]
    return {
        str(item).strip().lower()
        for item in values
        if str(item).strip()
    }


def classify_evidence_class(
    *,
    evidence_class: str | None = None,
    category_flags: Any = None,
    product_kind: str | None = None,
    operation_mode: str = "manual",
    target_market: str = "ru",
) -> EvidenceClass:
    """Deterministically classify the evidence class for a candidate.

    Explicit ``evidence_class`` wins; otherwise regulated category flags
    win, then EU target markets, then the operation mode.  Batch scanning is
    an automated pipeline, so its inferred default is ``auto_scale``
    (fail-closed); ``manual_small`` must be declared explicitly.
    """
    if evidence_class:
        try:
            return EvidenceClass(str(evidence_class).strip().lower())
        except ValueError:
            raise ValueError(
                "evidence_class must be one of "
                + ", ".join(sorted(item.value for item in EvidenceClass))
            ) from None
    flags = _normalize_flags(category_flags)
    if flags & REGULATED_CATEGORY_FLAGS:
        return EvidenceClass.REGULATED
    if product_kind:
        kind_flags = _normalize_flags([product_kind])
        if kind_flags & REGULATED_CATEGORY_FLAGS:
            return EvidenceClass.REGULATED
    market = str(target_market or "").strip().lower()
    if market.startswith("eu") or market == "europe":
        return EvidenceClass.EU_EXPORT
    if str(operation_mode or "").strip().lower() == "auto":
        return EvidenceClass.AUTO_SCALE
    return EvidenceClass.MANUAL_SMALL


def policy_for(evidence_class: str | EvidenceClass) -> EvidenceClassPolicy:
    try:
        cls = (
            evidence_class
            if isinstance(evidence_class, EvidenceClass)
            else EvidenceClass(str(evidence_class).strip().lower())
        )
    except ValueError:
        raise ValueError(
            "evidence_class must be one of "
            + ", ".join(sorted(item.value for item in EvidenceClass))
        ) from None
    return EVIDENCE_CLASS_POLICY[cls]


def contract() -> dict[str, Any]:
    """Frozen policy snapshot used for reporting and drift checks."""
    return {
        "contract_id": CONTRACT_ID,
        "policy_version": POLICY_VERSION,
        "basic_evidence_roles": sorted(BASIC_EVIDENCE_ROLES),
        "regulated_category_flags": sorted(REGULATED_CATEGORY_FLAGS),
        "classes": {
            cls.value: {
                "requires_full_passports": policy.requires_full_passports,
                "requires_six_basics": policy.requires_six_basics,
                "regulated_certificates_required": (
                    policy.regulated_certificates_required
                ),
                "independent_approval_required": (
                    policy.independent_approval_required
                ),
                "dpp_mapping": policy.dpp_mapping,
                "description": policy.description,
            }
            for cls, policy in sorted(EVIDENCE_CLASS_POLICY.items())
        },
    }
