from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from .domain import ContentAsset, ContentStatus, ContentType, ExperimentStatus, GrowthExperiment, utc_now
from .numeric_semantics import finite_decimal
from .repository import Repository

REQUIRED_QA = {"factual_grounding", "policy", "localization", "ip_rights", "brand"}
IMAGE_QA = {"product_fidelity", "source_provenance", "text_accuracy"}
QA_ORDER = (
    "factual_grounding",
    "policy",
    "localization",
    "ip_rights",
    "brand",
    "product_fidelity",
    "source_provenance",
    "text_accuracy",
)
IMAGE_GENERATION_MODES = {"retouch", "composite", "infographic"}
REQUIRED_IMAGE_ROLE_COUNT = 7


class ContentGrowthService:
    def __init__(
        self,
        repository: Repository,
        *,
        evidence_validator: Callable[[list[str]], None],
        evidence_lookup: Callable[[str], Any],
        image_readiness: Callable[[str], dict[str, Any]],
    ) -> None:
        self.repo = repository
        self.evidence_validator = evidence_validator
        self.evidence_lookup = evidence_lookup
        self.image_readiness = image_readiness

    def create_content_brief(
        self,
        *,
        product_id: str,
        content_type: ContentType,
        locale: str,
        channel: str,
        brief: dict,
    ) -> ContentAsset:
        self.repo.get_product(product_id)
        passports = self.repo.latest_passports(product_id)
        approved = {kind: passport for kind, passport in passports.items() if passport.is_approved}
        source_facts = {
            kind.value: {
                "passport_id": passport.id,
                "version": passport.version,
                "facts": passport.facts,
                "evidence_ids": passport.evidence,
            }
            for kind, passport in approved.items()
        }
        if len(source_facts) != 3:
            raise ValueError("Content generation requires all three approved product passports")
        brief = dict(brief)
        if content_type == ContentType.IMAGE:
            self._validate_image_brief(
                brief,
                approved_evidence={item for row in approved.values() for item in row.evidence},
                readiness=self.image_readiness(product_id),
            )
        asset = ContentAsset(product_id, content_type, locale, channel, brief, source_facts)
        with self.repo.transaction():
            self.repo.add_content_asset(asset)
            self.repo.append_event("content.brief_created", asset.id, {"type": content_type, "locale": locale})
        return asset

    def attach_generated_asset(self, asset_id: str, *, artifact_ref: str) -> ContentAsset:
        asset = self.repo.get_content_asset(asset_id)
        artifact_ref = artifact_ref.strip()
        if not artifact_ref:
            raise ValueError("Generated content must have an artifact reference")
        if asset.status not in {
            ContentStatus.BRIEF,
            ContentStatus.QUEUED,
            ContentStatus.QA_FAILED,
            ContentStatus.EXECUTION_FAILED,
        }:
            raise ValueError("Only a brief, queued, or failed asset can receive a generated artifact")
        self.evidence_validator([artifact_ref])
        if asset.content_type == ContentType.IMAGE:
            self._validate_image_artifact(asset, self.evidence_lookup(artifact_ref))
        asset.artifact_ref = artifact_ref
        asset.status = ContentStatus.GENERATED
        with self.repo.transaction():
            self.repo.save_content_asset(asset)
            self.repo.append_event("content.generated", asset.id, {"artifact_ref": artifact_ref})
        return asset

    def review_asset(self, asset_id: str, *, checks: list[dict], reviewed_by: str) -> ContentAsset:
        asset = self.repo.get_content_asset(asset_id)
        if asset.status != ContentStatus.GENERATED:
            raise ValueError("Only generated content can be reviewed")
        reviewed_by = reviewed_by.strip()
        if not reviewed_by:
            raise ValueError("Content QA requires a trusted reviewer identity")
        required = REQUIRED_QA | (IMAGE_QA if asset.content_type == ContentType.IMAGE else set())
        indexed: dict[str, dict[str, Any]] = {}
        evidence_ids: list[str] = []
        for item in checks:
            name = item.get("check")
            passed = item.get("passed")
            if not isinstance(name, str) or not name.strip() or not isinstance(passed, bool):
                raise ValueError("Each content QA result requires a check name and boolean passed value")
            name = name.strip()
            if name in indexed:
                raise ValueError(f"Duplicate content QA check: {name}")
            notes = item.get("notes")
            if not isinstance(notes, str) or not notes.strip():
                raise ValueError(f"Content QA check {name} requires review notes")
            item_evidence = item.get("evidence_ids", [])
            if (
                not isinstance(item_evidence, list)
                or any(not isinstance(value, str) or not value.strip() for value in item_evidence)
                or len(set(item_evidence)) != len(item_evidence)
            ):
                raise ValueError(f"Content QA check {name} has invalid or duplicate evidence IDs")
            normalized_evidence = [value.strip() for value in item_evidence]
            evidence_ids.extend(normalized_evidence)
            indexed[name] = {
                "check": name,
                "passed": passed,
                "notes": notes.strip(),
                "evidence_ids": normalized_evidence,
            }
        supplied = set(indexed)
        unknown = sorted(supplied - required)
        missing = sorted(required - supplied)
        if unknown:
            raise ValueError(f"Unknown content QA checks: {', '.join(unknown)}")
        if missing:
            raise ValueError(f"Content QA submission is incomplete: {', '.join(missing)}")
        if evidence_ids:
            self.evidence_validator(evidence_ids)
        reviewed_at = utc_now()
        asset.qa_results = [
            {**indexed[name], "reviewed_by": reviewed_by, "reviewed_at": reviewed_at}
            for name in QA_ORDER
            if name in indexed
        ]
        failed = [name for name in QA_ORDER if name in indexed and not indexed[name]["passed"]]
        asset.status = ContentStatus.QA_FAILED if failed else ContentStatus.APPROVED
        with self.repo.transaction():
            self.repo.save_content_asset(asset)
            self.repo.append_event(
                "content.reviewed",
                asset.id,
                {"status": asset.status, "reviewed_by": reviewed_by, "failed_checks": failed},
            )
        return asset

    def create_experiment(
        self,
        *,
        product_id: str,
        channel: str,
        hypothesis: str,
        primary_metric: str,
        budget_cap_cny: Decimal,
        stop_loss_cny: Decimal,
        variants: list[str],
    ) -> GrowthExperiment:
        self.repo.get_product(product_id)
        budget_cap_cny = finite_decimal(budget_cap_cny, "Experiment budget")
        stop_loss_cny = finite_decimal(stop_loss_cny, "Experiment stop loss")
        if budget_cap_cny <= 0 or stop_loss_cny <= 0 or stop_loss_cny > budget_cap_cny:
            raise ValueError("Experiment requires a positive budget and stop loss within that budget")
        if len(variants) < 2:
            raise ValueError("Experiment requires at least two variants")
        experiment = GrowthExperiment(
            product_id, channel, hypothesis, primary_metric, budget_cap_cny, stop_loss_cny, variants
        )
        with self.repo.transaction():
            self.repo.add_experiment(experiment)
            self.repo.append_event("experiment.created", experiment.id, {"metric": primary_metric})
        return experiment

    def start_experiment(self, experiment_id: str) -> GrowthExperiment:
        experiment = self.repo.get_experiment(experiment_id)
        if experiment.status != ExperimentStatus.DRAFT:
            raise ValueError("Only draft experiments can start")
        approved_assets = [
            item
            for item in self.repo.content_assets_for_product(experiment.product_id)
            if item.product_id == experiment.product_id
            and item.id in experiment.variants
            and item.status == ContentStatus.APPROVED
        ]
        if len(approved_assets) != len(experiment.variants):
            raise ValueError("All experiment variants must be approved content assets")
        experiment.status = ExperimentStatus.RUNNING
        with self.repo.transaction():
            self.repo.save_experiment(experiment)
            self.repo.append_event("experiment.started", experiment.id, {})
        return experiment

    def _validate_image_brief(
        self,
        brief: dict,
        *,
        approved_evidence: set[str],
        readiness: dict[str, Any],
    ) -> None:
        roles = readiness.get("roles")
        if (
            readiness.get("ready_for_full_production") is not True
            or not isinstance(roles, list)
            or len(roles) != REQUIRED_IMAGE_ROLE_COUNT
            or any(item.get("status") != "approved" for item in roles if isinstance(item, dict))
            or any(not isinstance(item, dict) for item in roles)
        ):
            raise ValueError("Image brief requires all seven source and rights roles to be approved")
        mode = brief.get("generation_mode")
        if mode not in IMAGE_GENERATION_MODES:
            raise ValueError(f"Image generation_mode must be one of: {', '.join(sorted(IMAGE_GENERATION_MODES))}")
        if brief.get("preserve_product_facts") is not True:
            raise ValueError("Image brief must lock product facts and appearance")
        source_ids = self._evidence_ids(brief, "source_asset_evidence_ids")
        rights_ids = self._evidence_ids(brief, "rights_evidence_ids")
        approved_pairs = {
            item.get("source_asset_evidence_id"): item.get("rights_evidence_id")
            for item in roles
            if item.get("source_asset_evidence_id") and item.get("rights_evidence_id")
        }
        if any(source_id not in approved_pairs for source_id in source_ids):
            raise ValueError("Image brief source evidence is not an approved product media role")
        paired_rights = {approved_pairs[source_id] for source_id in source_ids}
        if set(rights_ids) != paired_rights:
            raise ValueError("Image brief rights evidence must exactly match its selected source assets")
        referenced = set(source_ids + rights_ids)
        if not referenced.issubset(approved_evidence):
            raise ValueError("Image source and rights evidence must belong to approved product passports")
        self.evidence_validator(sorted(referenced))

    @staticmethod
    def _evidence_ids(brief: dict, field: str) -> list[str]:
        value = brief.get(field)
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError(f"Image brief requires non-empty {field}")
        normalized = [item.strip() for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"Image brief contains duplicate {field}")
        return normalized

    @staticmethod
    def _validate_image_artifact(asset: ContentAsset, evidence: Any) -> None:
        if not str(evidence.content_type).startswith("image/"):
            raise ValueError("Image content asset requires image evidence")
        metadata = evidence.metadata
        source_ids = metadata.get("source_asset_evidence_ids")
        required_sources = asset.brief["source_asset_evidence_ids"]
        if (
            not isinstance(source_ids, list)
            or any(not isinstance(item, str) or not item.strip() for item in source_ids)
            or len(source_ids) != len(set(source_ids))
            or set(source_ids) != set(required_sources)
        ):
            raise ValueError("Generated image provenance does not match its approved source assets")
        required_metadata = {
            "content_asset_id": asset.id,
            "generation_mode": asset.brief["generation_mode"],
        }
        for key, expected in required_metadata.items():
            if metadata.get(key) != expected:
                raise ValueError(f"Generated image evidence has invalid {key}")
        process = str(metadata.get("process", "")).strip()
        generated_at = str(metadata.get("generated_at", "")).strip()
        if not process or not generated_at:
            raise ValueError("Generated image evidence requires process and generated_at metadata")
        try:
            parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Generated image evidence generated_at must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("Generated image evidence generated_at must include a timezone")
