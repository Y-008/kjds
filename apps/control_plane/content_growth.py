from __future__ import annotations

from decimal import Decimal

from .domain import ContentAsset, ContentStatus, ContentType, ExperimentStatus, GrowthExperiment
from .repository import Repository

REQUIRED_QA = {"factual_grounding", "policy", "localization", "ip_rights", "brand"}


class ContentGrowthService:
    def __init__(self, repository: Repository) -> None:
        self.repo = repository

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
        source_facts = {kind.value: passport.facts for kind, passport in passports.items() if passport.is_approved}
        if len(source_facts) != 3:
            raise ValueError("Content generation requires all three approved product passports")
        asset = ContentAsset(product_id, content_type, locale, channel, brief, source_facts)
        self.repo.add_content_asset(asset)
        self.repo.append_event("content.brief_created", asset.id, {"type": content_type, "locale": locale})
        return asset

    def attach_generated_asset(self, asset_id: str, *, artifact_ref: str) -> ContentAsset:
        asset = self.repo.get_content_asset(asset_id)
        if not artifact_ref.strip():
            raise ValueError("Generated content must have an artifact reference")
        asset.artifact_ref = artifact_ref
        asset.status = ContentStatus.GENERATED
        self.repo.save_content_asset(asset)
        self.repo.append_event("content.generated", asset.id, {"artifact_ref": artifact_ref})
        return asset

    def review_asset(self, asset_id: str, *, checks: list[dict]) -> ContentAsset:
        asset = self.repo.get_content_asset(asset_id)
        checked = {item.get("check") for item in checks if item.get("passed") is True}
        asset.qa_results = checks
        asset.status = ContentStatus.APPROVED if REQUIRED_QA.issubset(checked) else ContentStatus.QA_FAILED
        self.repo.save_content_asset(asset)
        self.repo.append_event("content.reviewed", asset.id, {"status": asset.status})
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
        if budget_cap_cny <= 0 or stop_loss_cny <= 0 or stop_loss_cny > budget_cap_cny:
            raise ValueError("Experiment requires a positive budget and stop loss within that budget")
        if len(variants) < 2:
            raise ValueError("Experiment requires at least two variants")
        experiment = GrowthExperiment(
            product_id, channel, hypothesis, primary_metric, budget_cap_cny, stop_loss_cny, variants
        )
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
        self.repo.save_experiment(experiment)
        self.repo.append_event("experiment.started", experiment.id, {})
        return experiment
