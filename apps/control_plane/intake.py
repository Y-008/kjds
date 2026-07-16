from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from .domain import PassportType
from .evidence import EvidenceGrade


@dataclass(frozen=True, slots=True)
class PassportEvidencePayload:
    kind: PassportType
    facts: dict
    content: bytes
    filename: str
    content_type: str


class SkuEpisodeIntakeService:
    def __init__(self, *, commerce, evidence) -> None:
        self.commerce = commerce
        self.evidence = evidence

    def ingest(
        self,
        *,
        sku: str,
        name: str,
        effective_at: str,
        payloads: list[PassportEvidencePayload],
        created_by: str,
    ) -> dict:
        sku = sku.strip()
        name = name.strip()
        if not sku or not name:
            raise ValueError("SKU episode requires sku and name")
        by_kind = {payload.kind: payload for payload in payloads}
        if set(by_kind) != set(PassportType) or len(payloads) != len(PassportType):
            raise ValueError("SKU episode requires one evidence package for each passport type")
        for payload in payloads:
            if not payload.content:
                raise ValueError(f"{payload.kind.value} evidence file cannot be empty")
            if not isinstance(payload.facts, dict):
                raise ValueError(f"{payload.kind.value} facts must be an object")

        existing = next((product for product in self.commerce.list_products() if product.sku == sku), None)
        if existing is not None and existing.name != name:
            raise ValueError("SKU already exists with a different product name")
        product = existing or self.commerce.create_product(sku=sku, name=name)

        passports = []
        evidence_records = []
        for kind in PassportType:
            payload = by_kind[kind]
            digest = hashlib.sha256(payload.content).hexdigest()
            record = self.evidence.capture(
                content=payload.content,
                filename=payload.filename,
                content_type=payload.content_type,
                source="sku_episode_intake",
                source_ref=f"sku-episode://{sku}/{kind.value}/sha256/{digest}",
                grade=EvidenceGrade.A,
                effective_at=effective_at,
                effective_until=None,
                created_by=created_by,
                metadata={"sku": sku, "product_id": product.id, "passport_type": kind.value},
            )
            passport = self.commerce.add_passport(
                product_id=product.id,
                kind=kind,
                facts=payload.facts,
                evidence=[record.id],
                approved_by=None,
            )
            self.evidence.link(
                evidence_id=record.id,
                target_type="passport",
                target_id=passport.id,
                relationship="supports",
                created_by=created_by,
            )
            passports.append(passport)
            evidence_records.append(record)
        return {
            "product": asdict(product),
            "passports": [asdict(item) for item in passports],
            "evidence": [asdict(item) for item in evidence_records],
            "readiness": self.commerce.product_readiness(product.id),
        }
