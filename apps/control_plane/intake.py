from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from .domain import PassportType
from .evidence import EvidenceGrade

PRODUCT_MEDIA_ROLES = (
    "front_main",
    "back",
    "side",
    "detail",
    "accessories",
    "packaging",
    "scale_reference",
)
PRODUCT_MEDIA_SOURCE_KINDS = {"sample_photo", "supplier_authorized"}
PRODUCT_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
PRODUCT_RIGHTS_TYPES = {"application/pdf", "text/plain", "image/jpeg", "image/png"}


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
        scope_authority: dict | None = None,
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

        if scope_authority is None:
            products = self.commerce.list_products()
        else:
            products = self.commerce.repo.list_products_scoped(
                tenant_ref=scope_authority["tenant_ref"],
                entity_ref=scope_authority["entity_ref"],
                store_ref=scope_authority["store_ref"],
                as_of=scope_authority["as_of"],
            )
        existing = next(
            (product for product in products if product.sku == sku),
            None,
        )
        if existing is not None and existing.name != name:
            raise ValueError("SKU already exists with a different product name")
        product = existing or self.commerce.create_product(
            sku=sku,
            name=name,
            tenant_ref=(
                scope_authority["tenant_ref"]
                if scope_authority
                else None
            ),
            entity_ref=(
                scope_authority["entity_ref"]
                if scope_authority
                else None
            ),
            store_ref=(
                scope_authority["store_ref"]
                if scope_authority
                else None
            ),
            scope_grant_authority_sha256=(
                scope_authority["scope_grant_authority_sha256"]
                if scope_authority
                else None
            ),
            scope_as_of=(
                scope_authority["as_of"].isoformat()
                if scope_authority
                else None
            ),
            created_by=created_by if scope_authority else None,
        )

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


class ProductMediaEvidenceService:
    def __init__(self, *, commerce, evidence) -> None:
        self.commerce = commerce
        self.evidence = evidence

    def ingest(
        self,
        *,
        product_id: str,
        variant_id: str,
        asset_role: str,
        source_kind: str,
        source_ref: str,
        effective_at: str,
        image_content: bytes,
        image_filename: str,
        image_content_type: str,
        rights_content: bytes,
        rights_filename: str,
        rights_content_type: str,
        created_by: str,
        authorized_product=None,
    ) -> dict:
        product = (
            authorized_product
            if authorized_product is not None
            else self.commerce.repo.get_product(product_id)
        )
        if product.id != product_id:
            raise ValueError("Authorized Product does not match product_id")
        variant_id = variant_id.strip()
        asset_role = asset_role.strip()
        source_kind = source_kind.strip()
        source_ref = source_ref.strip()
        if not variant_id or len(variant_id) > 100:
            raise ValueError("Product media requires a variant_id of at most 100 characters")
        if asset_role not in PRODUCT_MEDIA_ROLES:
            raise ValueError(f"Product media asset_role must be one of: {', '.join(PRODUCT_MEDIA_ROLES)}")
        if source_kind not in PRODUCT_MEDIA_SOURCE_KINDS:
            raise ValueError("Product media source_kind must be sample_photo or supplier_authorized")
        if not source_ref or len(source_ref) > 500:
            raise ValueError("Product media requires a source_ref of at most 500 characters")
        self._validate_file(image_content, image_content_type, PRODUCT_IMAGE_TYPES, "Product image")
        self._validate_file(rights_content, rights_content_type, PRODUCT_RIGHTS_TYPES, "Rights evidence")
        latest_quality = self.commerce.repo.latest_passports(product.id).get(PassportType.QUALITY)
        if latest_quality is None:
            raise ValueError("Product media requires an existing Quality Passport")

        identity = f"{product.sku}/{variant_id}/{asset_role}"
        rights_digest = hashlib.sha256(rights_content).hexdigest()
        rights_record = self.evidence.capture(
            content=rights_content,
            filename=rights_filename,
            content_type=rights_content_type,
            source="product_media_rights",
            source_ref=f"product-media://{identity}/rights/{rights_digest}",
            grade=EvidenceGrade.A,
            effective_at=effective_at,
            effective_until=None,
            created_by=created_by,
            metadata={
                "retention_class": "compliance",
                "media_kind": "rights",
                "product_id": product.id,
                "sku": product.sku,
                "variant_id": variant_id,
                "asset_role": asset_role,
                "source_kind": source_kind,
                "source_ref": source_ref,
            },
        )
        image_digest = hashlib.sha256(image_content).hexdigest()
        image_record = self.evidence.capture(
            content=image_content,
            filename=image_filename,
            content_type=image_content_type,
            source="product_media",
            source_ref=f"product-media://{identity}/asset/{image_digest}",
            grade=EvidenceGrade.A if source_kind == "sample_photo" else EvidenceGrade.B,
            effective_at=effective_at,
            effective_until=None,
            created_by=created_by,
            metadata={
                "retention_class": "operational",
                "media_kind": "source_asset",
                "product_id": product.id,
                "sku": product.sku,
                "variant_id": variant_id,
                "asset_role": asset_role,
                "source_kind": source_kind,
                "source_ref": source_ref,
                "rights_evidence_id": rights_record.id,
            },
        )
        for record, relationship in ((image_record, "source_asset"), (rights_record, "media_rights")):
            self.evidence.link(
                evidence_id=record.id,
                target_type="product",
                target_id=product.id,
                relationship=relationship,
                created_by=created_by,
            )
        self.evidence.link(
            evidence_id=rights_record.id,
            target_type="evidence",
            target_id=image_record.id,
            relationship="authorizes",
            created_by=created_by,
        )

        combined_evidence = list(dict.fromkeys([*latest_quality.evidence, image_record.id, rights_record.id]))
        if image_record.id in latest_quality.evidence and rights_record.id in latest_quality.evidence:
            passport = latest_quality
        else:
            passport = self.commerce.add_passport(
                product_id=product.id,
                kind=PassportType.QUALITY,
                facts=latest_quality.facts,
                evidence=combined_evidence,
                approved_by=None,
            )
        for evidence_id in passport.evidence:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type="passport",
                target_id=passport.id,
                relationship="supports",
                created_by=created_by,
            )
        return {
            "product": asdict(product),
            "source_asset": asdict(image_record),
            "rights_evidence": asdict(rights_record),
            "quality_passport": asdict(passport),
            "media_readiness": self.readiness(product.id),
        }

    def readiness(self, product_id: str) -> dict:
        product = self.commerce.repo.get_product(product_id)
        passports = self.commerce.repo.latest_passports(product.id)
        quality = passports.get(PassportType.QUALITY)
        quality_evidence = set(quality.evidence if quality else [])
        approved_quality_evidence = set(quality.evidence if quality and quality.is_approved else [])
        records = []
        for evidence_id in quality_evidence:
            record = self.evidence.get(evidence_id)
            if record.metadata.get("product_id") == product.id:
                records.append(record)
        records.sort(key=lambda item: (item.recorded_at, item.id), reverse=True)
        rights_by_id = {
            item.id: item
            for item in records
            if item.metadata.get("media_kind") == "rights"
        }

        roles = []
        for role in PRODUCT_MEDIA_ROLES:
            pair = None
            for image in records:
                if image.metadata.get("media_kind") != "source_asset" or image.metadata.get("asset_role") != role:
                    continue
                rights = rights_by_id.get(image.metadata.get("rights_evidence_id"))
                if rights is None or rights.metadata.get("asset_role") != role:
                    continue
                try:
                    self.evidence.require_valid([image.id, rights.id])
                except (KeyError, ValueError):
                    continue
                pair = (image, rights)
                break
            if pair is None:
                roles.append({"role": role, "status": "missing", "source_asset_evidence_id": None, "rights_evidence_id": None})
                continue
            image, rights = pair
            approved = image.id in approved_quality_evidence and rights.id in approved_quality_evidence
            roles.append(
                {
                    "role": role,
                    "status": "approved" if approved else "captured_pending_passport",
                    "source_asset_evidence_id": image.id,
                    "rights_evidence_id": rights.id,
                }
            )

        all_passports_approved = len(passports) == len(PassportType) and all(
            passport.is_approved for passport in passports.values()
        )
        approved_roles = [item["role"] for item in roles if item["status"] == "approved"]
        missing_roles = [item["role"] for item in roles if item["status"] == "missing"]
        pending_roles = [item["role"] for item in roles if item["status"] == "captured_pending_passport"]
        ready_for_full_production = all_passports_approved and len(approved_roles) == len(PRODUCT_MEDIA_ROLES)
        if missing_roles:
            next_action = f"Upload source image and rights evidence for: {', '.join(missing_roles)}"
        elif pending_roles or not all_passports_approved:
            next_action = "Approve the latest Passport versions before creating image briefs"
        else:
            next_action = "Create a locked retouch, composite, or infographic brief"
        return {
            "product": asdict(product),
            "required_roles": list(PRODUCT_MEDIA_ROLES),
            "roles": roles,
            "approved_role_count": len(approved_roles),
            "missing_roles": missing_roles,
            "pending_passport_roles": pending_roles,
            "all_passports_approved": all_passports_approved,
            "ready_for_full_production": ready_for_full_production,
            "automatic_generation": False,
            "next_action": next_action,
        }

    @staticmethod
    def _validate_file(content: bytes, content_type: str, allowed: set[str], label: str) -> None:
        if not content:
            raise ValueError(f"{label} cannot be empty")
        if content_type not in allowed:
            raise ValueError(f"{label} has unsupported content type: {content_type}")
        signatures = {
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP",
            "application/pdf": content.startswith(b"%PDF-"),
            "text/plain": b"\x00" not in content[:1024],
        }
        if not signatures[content_type]:
            raise ValueError(f"{label} content does not match its declared type")
