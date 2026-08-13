from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from .domain import ContentStatus, PassportType, Product, ProductStatus
from .media_jobs import (
    EDITING_MAX_SCENE_DURATION_MS,
    EDITING_MAX_TIMELINE_DURATION_MS,
    EDITING_TARGET_CHANNELS,
    FFMPEG_RENDER_PROFILE_SHA256,
    canonical_json,
    sha256_bytes,
)
from .security import Principal


class ScopedProductContentAuthority:
    """Project PIM/content facts and build a scoped Listing approval plan."""

    CONTRACT_ID = "kjds-scoped-product-content-v1"
    APPROVAL_PLAN_CONTRACT_ID = "kjds-listing-approval-plan-v1"

    def __init__(
        self,
        *,
        repository,
        scoped_catalog,
        scoped_evidence,
        sourcing,
        evidence=None,
        media_jobs=None,
    ) -> None:
        self.repository = repository
        self.scoped_catalog = scoped_catalog
        self.scoped_evidence = scoped_evidence
        self.sourcing = sourcing
        self.evidence = evidence
        self.media_jobs = media_jobs

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        product_id: str | None = None,
        catalog_projection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if context["status"] != "ready":
            return self._empty(context=context)
        catalog = catalog_projection or self.scoped_catalog.latest(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            limit=1000,
        )
        if catalog["status"] == "blocked":
            return self._result(
                context=context,
                status="blocked",
                products=[],
                excluded={"catalog_authority_blocked": 1},
                source_gaps=catalog["source_gaps"],
                blockers=catalog["blockers"],
                raw_read=False,
            )
        products, excluded = self._resolve_products(
            context=context,
            catalog=catalog,
            product_id=product_id,
        )
        if not products:
            reason = (
                "scoped_product_not_found"
                if product_id
                else "scoped_products_not_available"
            )
            return self._result(
                context=context,
                status="no_data",
                products=[],
                excluded=excluded,
                source_gaps=[reason],
                blockers=[self._blocker(reason, owner="pim-governance")],
            )

        projected = [
            self._project_product(product=product, context=context)
            for product in products
        ]
        hard_blockers = [
            blocker
            for item in projected
            for blocker in item["blockers"]
            if blocker["severity"] == "P0"
        ]
        if hard_blockers:
            status = "blocked"
        elif all(
            item["readiness"]["content_draft_allowed"]
            for item in projected
        ):
            status = "ready"
        else:
            status = "partial"
        return self._result(
            context=context,
            status=status,
            products=projected,
            excluded=excluded,
            source_gaps=sorted(
                {
                    gap
                    for item in projected
                    for gap in item["source_gaps"]
                }
            ),
            blockers=[
                blocker
                for item in projected
                for blocker in item["blockers"]
            ],
        )

    def project_catalog(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        catalog_projection: dict[str, Any],
    ) -> dict[str, Any]:
        return self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            catalog_projection=catalog_projection,
        )

    def require_product(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        product_id: str,
    ) -> tuple[Product, dict[str, Any]]:
        projection = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            product_id=product_id,
        )
        if not projection["products"]:
            raise KeyError("Unknown product in authorized operating scope")
        product = self._product_from_projection(projection["products"][0])
        return product, projection

    def require_evidence(
        self,
        *,
        evidence_ids: list[str],
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        normalized = sorted(
            {str(item).strip() for item in evidence_ids if str(item).strip()}
        )
        if len(normalized) != len(evidence_ids) or not normalized:
            raise ValueError(
                "Product/content mutation requires unique scoped Evidence"
            )
        projection = self.scoped_evidence.project_targets(
            evidence_ids=normalized,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        records = {
            item["evidence_id"]: item
            for item in projection["records"]
            if item["evidence_id"] in normalized
        }
        if (
            projection["status"] != "ready"
            or projection["invalid_evidence_ids"]
            or set(records) != set(normalized)
            or any(
                item["scope_binding"]["status"] != "ready"
                for item in records.values()
            )
        ):
            raise ValueError(
                "Product/content Evidence is not current and bound to the "
                "exact tenant/entity/store scope"
            )
        return projection

    def require_asset(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        asset_id: str,
    ):
        projection = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        allowed_product_ids = [
            item["product"]["id"] for item in projection["products"]
        ]
        if not allowed_product_ids:
            raise KeyError(
                "Unknown content asset in authorized operating scope"
            )
        asset = self.repository.get_content_asset_for_products(
            asset_id=asset_id,
            product_ids=allowed_product_ids,
            as_of=as_of,
        )
        product_projection = next(
            item
            for item in projection["products"]
            if item["product"]["id"] == asset.product_id
        )
        return asset, product_projection, projection

    def read_editing_source(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        scope: Any,
        as_of: datetime,
    ) -> dict[str, Any]:
        """Build a source receipt only from current scoped assets and Evidence."""

        if self.media_jobs is None or self.evidence is None:
            raise RuntimeError("editing_source_authority_not_admitted")
        if as_of.tzinfo is None:
            raise ValueError("editing_source_as_of_timezone_required")
        expected_scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": str(scope.entity_ref),
            "store_ref": store_ref,
            "authority_sha256": str(scope.authority_sha256),
            "subject_actor_id": principal.actor_id,
        }
        actual_scope = {
            "tenant_ref": str(scope.tenant_ref),
            "entity_ref": str(scope.entity_ref),
            "store_ref": str(scope.store_ref),
            "authority_sha256": str(scope.authority_sha256),
            "subject_actor_id": str(scope.subject_actor_id),
        }
        current_scope = self.media_jobs.current_scope(
            principal=principal,
            store_ref=store_ref,
        )
        server_scope = {
            "tenant_ref": str(current_scope.tenant_ref),
            "entity_ref": str(current_scope.entity_ref),
            "store_ref": str(current_scope.store_ref),
            "authority_sha256": str(current_scope.authority_sha256),
            "subject_actor_id": str(current_scope.subject_actor_id),
        }
        if actual_scope != expected_scope or server_scope != actual_scope:
            raise PermissionError("editing_source_scope_binding_invalid")
        worker = self.media_jobs.read_worker_input(
            principal=principal,
            store_ref=store_ref,
            job_ref=job_ref,
        )
        payload = worker.payload
        tool_name = worker.tool_name
        if tool_name == "media.video_render":
            reference_refs = list(payload["source_asset_refs"])
            audio_refs = list(payload["audio_asset_refs"])
            if (
                len(audio_refs) != 1
                or payload.get("render_profile_sha256")
                != FFMPEG_RENDER_PROFILE_SHA256
            ):
                raise ValueError("editing_source_render_profile_invalid")
            analysis_evidence_ref = None
        elif tool_name == "media.video_blueprint":
            reference_refs = list(payload["reference_asset_refs"])
            audio_refs = list(payload["audio_asset_refs"])
            analysis_evidence_ref = payload.get("analysis_evidence_ref")
            if (
                not isinstance(analysis_evidence_ref, str)
                or len(audio_refs) != 1
                or payload.get("render_profile_sha256")
                != FFMPEG_RENDER_PROFILE_SHA256
                or payload.get("target_channels")
                != list(EDITING_TARGET_CHANNELS)
            ):
                raise ValueError("editing_source_analysis_ref_invalid")
        else:
            raise ValueError("editing_source_tool_not_admitted")
        campaign_refs = list(payload["campaign_content_asset_refs"])
        role_refs = [*campaign_refs, *reference_refs, *audio_refs]
        if len(role_refs) != len(set(role_refs)):
            raise ValueError("editing_source_asset_roles_overlap")
        all_refs = list(dict.fromkeys([*campaign_refs, *reference_refs, *audio_refs]))
        if not all_refs:
            raise ValueError("editing_source_assets_required")

        def asset_id(value: str) -> str:
            prefix = "content-asset://"
            return value[len(prefix) :] if value.startswith(prefix) else value

        assets = []
        assets_by_ref: dict[str, Any] = {}
        for ref in all_refs:
            asset = self.repository.get_content_asset_scoped(
                asset_id=asset_id(ref),
                tenant_ref=actual_scope["tenant_ref"],
                entity_ref=actual_scope["entity_ref"],
                store_ref=actual_scope["store_ref"],
                as_of=as_of,
            )
            if (
                asset.status is not ContentStatus.APPROVED
                or not asset.artifact_ref
            ):
                raise ValueError("editing_source_asset_not_approved")
            assets.append(asset)
            assets_by_ref[ref] = asset
        product_ids = {asset.product_id for asset in assets}
        if len(product_ids) != 1:
            raise ValueError("editing_source_product_scope_conflict")
        evidence_ids = [str(asset.artifact_ref) for asset in assets]
        blueprint_ref = payload.get("editing_blueprint_ref")
        if blueprint_ref is not None:
            evidence_ids.append(
                blueprint_ref.removeprefix("evidence://")
            )
        if analysis_evidence_ref is not None:
            evidence_ids.append(
                analysis_evidence_ref.removeprefix("evidence://")
            )
        self.require_evidence(
            evidence_ids=evidence_ids,
            principal=principal,
            entity_scope={
                "status": "ready",
                "entity_ref": actual_scope["entity_ref"],
                "authority_sha256": actual_scope["authority_sha256"],
            },
            store_ref=store_ref,
            as_of=as_of,
        )
        records = [self.evidence.get(evidence_id) for evidence_id in evidence_ids]
        if any(record.metadata.get("rights_status") != "approved" for record in records):
            raise ValueError("editing_source_rights_not_approved")

        input_artifacts: list[dict[str, str]] = []
        records_by_id = {record.id: record for record in records}
        for ref in all_refs:
            asset = assets_by_ref[ref]
            record = records_by_id[str(asset.artifact_ref)]
            content, content_record = self.evidence.content(record.id)
            if (
                content_record.sha256 != record.sha256
                or sha256_bytes(content) != record.sha256
            ):
                raise ValueError("editing_source_artifact_drifted")
            if ref in reference_refs:
                role = "reference_video"
                if asset.content_type.value != "video" or not record.content_type.startswith(
                    "video/"
                ):
                    raise ValueError("editing_source_video_artifact_invalid")
            elif ref in audio_refs:
                role = "audio"
                if not record.content_type.startswith("audio/"):
                    raise ValueError("editing_source_audio_artifact_invalid")
            else:
                role = "campaign"
            input_artifacts.append(
                {
                    "content_asset_ref": ref,
                    "evidence_ref": f"evidence://{record.id}",
                    "evidence_sha256": record.sha256,
                    "content_type": record.content_type,
                    "role": role,
                }
            )

        blueprint = None
        analysis_record = None
        analysis_receipt = None
        source_video_artifacts = [
            {
                "content_asset_ref": artifact["content_asset_ref"],
                "evidence_ref": artifact["evidence_ref"],
                "evidence_sha256": artifact["evidence_sha256"],
            }
            for artifact in input_artifacts
            if artifact["role"] == "reference_video"
        ]
        if blueprint_ref is not None:
            content, blueprint_record = self.evidence.content(
                blueprint_ref.removeprefix("evidence://")
            )
            try:
                blueprint = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("editing_source_blueprint_invalid") from exc
            if (
                not isinstance(blueprint, dict)
                or content != canonical_json(blueprint)
                or blueprint.get("contract_id") != "kjds-editing-blueprint-v1"
                or not isinstance(blueprint.get("scenes"), list)
                or not isinstance(blueprint.get("analysis_receipt"), dict)
            ):
                raise ValueError("editing_source_blueprint_invalid")
            scenes = blueprint["scenes"]
            subtitle_ref = blueprint.get("subtitle_asset_ref")
            target_channels = blueprint.get("target_channels", payload["target_channels"])
            if (
                blueprint.get("render_profile_sha256")
                != FFMPEG_RENDER_PROFILE_SHA256
                or blueprint.get("campaign_asset_refs") != campaign_refs
                or blueprint.get("reference_asset_refs") != reference_refs
                or blueprint.get("audio_asset_ref") != audio_refs[0]
                or blueprint.get("target_channels")
                != list(EDITING_TARGET_CHANNELS)
            ):
                raise ValueError("editing_source_render_profile_invalid")
            if (
                blueprint_record.source != "governed-media-job-blueprint"
                or blueprint_record.grade.value != "B"
                or blueprint_record.sha256 != sha256_bytes(content)
            ):
                raise ValueError("editing_source_blueprint_not_governed")
            analysis_receipt = dict(blueprint["analysis_receipt"])
            analysis_evidence_ref = analysis_receipt.get("evidence_ref")
            if not isinstance(analysis_evidence_ref, str) or not analysis_evidence_ref.startswith(
                "evidence://"
            ):
                raise ValueError("editing_source_analysis_ref_invalid")
            self.require_evidence(
                evidence_ids=[analysis_evidence_ref.removeprefix("evidence://")],
                principal=principal,
                entity_scope={
                    "status": "ready",
                    "entity_ref": actual_scope["entity_ref"],
                    "authority_sha256": actual_scope["authority_sha256"],
                },
                store_ref=store_ref,
                as_of=as_of,
            )
            analysis_content, analysis_record = self.evidence.content(
                analysis_evidence_ref.removeprefix("evidence://")
            )
            try:
                analysis = json.loads(analysis_content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("editing_source_analysis_invalid") from exc
            analysis_semantic_sha = str(analysis_receipt.get("semantic_sha256"))
            observed_at = str(analysis_receipt.get("observed_at"))
        else:
            if not analysis_evidence_ref.startswith("evidence://"):
                raise ValueError("editing_source_analysis_link_invalid")
            content, analysis_record = self.evidence.content(
                analysis_evidence_ref.removeprefix("evidence://")
            )
            try:
                analysis = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("editing_source_analysis_invalid") from exc
            if (
                not isinstance(analysis, dict)
                or content != canonical_json(analysis)
                or analysis.get("contract_id")
                != "kjds-reference-video-analysis-v1"
                or not isinstance(analysis.get("scenes"), list)
                or not isinstance(analysis.get("source_video_artifacts"), list)
            ):
                raise ValueError("editing_source_analysis_invalid")
            scenes = analysis["scenes"]
            subtitle_ref = analysis.get("subtitle_asset_ref")
            target_channels = analysis.get("target_channels", payload["target_channels"])
            analysis_semantic_sha = sha256_bytes(canonical_json(analysis))
            if (
                payload.get("analysis_contract_sha256")
                != analysis_semantic_sha
            ):
                raise ValueError("editing_source_analysis_contract_drifted")
            observed_at = analysis_record.effective_at
            analysis_receipt = {
                "contract_id": "kjds-reference-video-analysis-v1",
                "source_snapshot_sha256": "0" * 64,
                "semantic_sha256": analysis_semantic_sha,
                "observed_at": observed_at,
                "evidence_ref": f"evidence://{analysis_record.id}",
                "evidence_sha256": analysis_record.sha256,
                "source_video_artifacts": source_video_artifacts,
            }

        if not isinstance(analysis, dict) or analysis.get(
            "contract_id"
        ) != "kjds-reference-video-analysis-v1":
            raise ValueError("editing_source_analysis_invalid")
        analysis_sha = sha256_bytes(canonical_json(analysis))
        analysis_run_ref = analysis_record.metadata.get("analysis_run_ref")
        expected_analysis_metadata = {
            "rights_status": "approved",
            "contract_id": "kjds-reference-video-analysis-v1",
            "tenant_ref": actual_scope["tenant_ref"],
            "entity_ref": actual_scope["entity_ref"],
            "store_ref": actual_scope["store_ref"],
            "scope_grant_authority_sha256": actual_scope["authority_sha256"],
            "subject_actor_id": actual_scope["subject_actor_id"],
            "analysis_run_ref": analysis_run_ref,
            "analysis_contract_sha256": analysis_sha,
            "source_video_artifacts_sha256": sha256_bytes(
                canonical_json(source_video_artifacts)
            ),
            "schema_version": "1.0.0",
            "observed_at": analysis_record.effective_at,
        }
        if (
            analysis_record.content_type != "application/json"
            or analysis_record.sha256 != sha256_bytes(analysis_content if blueprint is not None else content)
            or (analysis_content if blueprint is not None else content)
            != canonical_json(analysis)
            or analysis_record.sha256 != analysis_sha
            or analysis_record.source != "governed-reference-video-analysis"
            or analysis_record.source_ref
            != f"reference-analysis://{analysis_run_ref}/{analysis_sha}"
            or analysis.get("source_video_artifacts") != source_video_artifacts
            or analysis_record.metadata != expected_analysis_metadata
            or analysis_receipt.get("semantic_sha256") != analysis_sha
            or analysis_receipt.get("evidence_sha256") != analysis_sha
            or analysis_receipt.get("evidence_ref")
            != f"evidence://{analysis_record.id}"
            or analysis_receipt.get("evidence_sha256") != analysis_record.sha256
            or analysis_receipt.get("source_video_artifacts")
            != source_video_artifacts
        ):
            raise ValueError("editing_source_analysis_binding_invalid")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("editing_source_scenes_invalid")
        caption_ids: list[str] = []
        scene_source_refs: set[str] = set()
        previous_end = 0
        rendered_duration_ms = 0
        for index, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                raise ValueError("editing_source_scene_invalid")
            source_asset_ref = scene.get("source_asset_ref")
            caption_ref = scene.get("caption_ref")
            if source_asset_ref not in reference_refs:
                raise ValueError("editing_source_scene_asset_invalid")
            source_start = scene.get("source_start_ms")
            source_end = scene.get("source_end_ms")
            timeline_start = scene.get("timeline_start_ms")
            timeline_end = scene.get("timeline_end_ms")
            transition = scene.get("transition")
            if (
                any(
                    isinstance(value, bool) or not isinstance(value, int)
                    for value in (
                        source_start,
                        source_end,
                        timeline_start,
                        timeline_end,
                    )
                )
                or source_start < 0
                or source_end <= source_start
                or timeline_start != previous_end
                or timeline_end <= timeline_start
                or source_end - source_start != timeline_end - timeline_start
                or source_end - source_start > EDITING_MAX_SCENE_DURATION_MS
                or timeline_end > EDITING_MAX_TIMELINE_DURATION_MS
                or transition not in {"cut", "fade", "crossfade"}
                or (index == 0 and transition == "crossfade")
                or (
                    transition == "crossfade"
                    and (
                        timeline_end - timeline_start <= 250
                        or rendered_duration_ms < 250
                    )
                )
            ):
                raise ValueError("editing_source_scene_timeline_invalid")
            previous_end = timeline_end
            rendered_duration_ms += timeline_end - timeline_start
            if transition == "crossfade":
                rendered_duration_ms -= 250
            scene_source_refs.add(str(source_asset_ref))
            if (
                not isinstance(caption_ref, str)
                or not caption_ref.startswith("evidence://")
                or len(caption_ref) > 500
            ):
                raise ValueError("editing_source_scene_caption_invalid")
            caption_ids.append(caption_ref.removeprefix("evidence://"))
        if scene_source_refs != set(reference_refs):
            raise ValueError("editing_source_scene_asset_conservation_invalid")
        if len(set(caption_ids)) != len(caption_ids):
            raise ValueError("editing_source_scene_caption_duplicate")
        self.require_evidence(
            evidence_ids=caption_ids,
            principal=principal,
            entity_scope={
                "status": "ready",
                "entity_ref": actual_scope["entity_ref"],
                "authority_sha256": actual_scope["authority_sha256"],
            },
            store_ref=store_ref,
            as_of=as_of,
        )
        caption_records = [self.evidence.get(evidence_id) for evidence_id in caption_ids]
        if any(
            record.metadata.get("rights_status") != "approved"
            for record in caption_records
        ):
            raise ValueError("editing_source_rights_not_approved")
        if subtitle_ref is not None:
            if (
                not isinstance(subtitle_ref, str)
                or not subtitle_ref.startswith("evidence://")
                or len(subtitle_ref) > 500
            ):
                raise ValueError("editing_source_subtitle_ref_invalid")
            self.require_evidence(
                evidence_ids=[subtitle_ref.removeprefix("evidence://")],
                principal=principal,
                entity_scope={
                    "status": "ready",
                    "entity_ref": actual_scope["entity_ref"],
                    "authority_sha256": actual_scope["authority_sha256"],
                },
                store_ref=store_ref,
                as_of=as_of,
            )
        if target_channels != list(EDITING_TARGET_CHANNELS):
            raise ValueError("editing_source_target_channels_invalid")
        from .editing_blueprint import (
            analysis_receipt_snapshot_sha256,
            source_snapshot_sha256,
        )

        scope_binding = sha256_bytes(canonical_json(actual_scope))
        source = {
            "contract_id": "kjds-editing-source-receipt-v1",
            "contract_version": "1.0.0",
            "scope": actual_scope,
            "scope_binding_sha256": scope_binding,
            "rights_status": "approved",
            "product_id": next(iter(product_ids)),
            "campaign_asset_refs": campaign_refs,
            "reference_asset_refs": reference_refs,
            "input_artifacts": input_artifacts,
            "analysis_receipt": analysis_receipt,
            "source_snapshot_sha256": "0" * 64,
            "scenes": scenes,
            "audio_asset_ref": audio_refs[0] if audio_refs else None,
            "subtitle_asset_ref": subtitle_ref,
            "target_channels": target_channels,
            "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
            "editing_blueprint": blueprint,
            "editing_blueprint_sha256": (
                sha256_bytes(canonical_json(blueprint))
                if blueprint is not None
                else None
            ),
        }
        source["analysis_receipt"]["source_snapshot_sha256"] = (
            analysis_receipt_snapshot_sha256(source["analysis_receipt"])
        )
        snapshot_sha = source_snapshot_sha256(source)
        source["source_snapshot_sha256"] = snapshot_sha
        return source

    def listing_approval_plan(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        product_id: str,
        offer_id: str,
        scenario_id: str,
        content_asset_ids: list[str],
        listing_data: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if context["status"] != "ready":
            return self._approval_plan(
                context=context,
                allowed=False,
                reasons=[context["reason"]],
                evidence_ids=[],
                product_snapshot_sha256=None,
                evidence_authority_sha256=None,
                inputs={
                    "product_id": product_id,
                    "offer_id": offer_id,
                    "scenario_id": scenario_id,
                    "content_asset_ids": sorted(content_asset_ids),
                    "listing_data": listing_data,
                },
            )
        product_projection = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            product_id=product_id,
        )
        reasons: list[str] = []
        if not product_projection["products"]:
            reasons.append("scoped_product_not_found")
            product_item = None
        else:
            product_item = product_projection["products"][0]
            if not product_item["readiness"]["passport_approved"]:
                reasons.append("approved_passports_incomplete")
            if not product_item["readiness"]["media_qa_ready"]:
                reasons.append("approved_media_qa_incomplete")

        if not content_asset_ids or len(set(content_asset_ids)) != len(
            content_asset_ids
        ):
            reasons.append("content_asset_selection_invalid")
        selected_assets: list[dict[str, Any]] = []
        if product_item is not None:
            assets_by_id = {
                item["id"]: item for item in product_item["content_assets"]
            }
            selected_assets = [
                assets_by_id[item]
                for item in content_asset_ids
                if item in assets_by_id
            ]
            if (
                len(selected_assets) != len(content_asset_ids)
                or any(
                    item["status"] != ContentStatus.APPROVED.value
                    or not item["artifact_ref"]
                    or not item["evidence_ready"]
                    for item in selected_assets
                )
            ):
                reasons.append("content_assets_not_approved_in_scope")

        evidence_ids = sorted(
            {
                evidence_id
                for item in selected_assets
                for evidence_id in item["evidence_ids"]
            }
        )
        try:
            offer = self.sourcing.store.get_offer(offer_id)
            scenario = self.sourcing.store.get_scenario(scenario_id)
        except KeyError:
            offer = None
            scenario = None
            reasons.append("supplier_economics_not_found")
        if offer is not None and offer.product_id != product_id:
            reasons.append("supplier_offer_product_mismatch")
        if scenario is not None and (
            offer is None or scenario.offer_id != offer.id
        ):
            reasons.append("profit_scenario_offer_mismatch")
        if scenario is not None:
            evidence_ids.extend(scenario.evidence)
            evidence_ids.extend(scenario.cost_evidence.values())
            if scenario.cm3_cny <= 0:
                reasons.append("positive_cm3_required")
            try:
                self.sourcing.require_release_ready(scenario)
            except (KeyError, RuntimeError, ValueError):
                reasons.append("formal_cost_evidence_incomplete")
        if offer is not None:
            evidence_ids.append(offer.evidence_ref)
        if product_item is not None:
            evidence_ids.extend(product_item["evidence_ids"])
        evidence_ids = sorted(
            {item.strip() for item in evidence_ids if item.strip()}
        )

        required = {
            "title",
            "description",
            "category_id",
            "attributes",
            "images",
        }
        if not isinstance(listing_data, dict) or required - set(listing_data):
            reasons.append("listing_payload_incomplete")
        elif [
            item["artifact_ref"] for item in selected_assets
        ] != listing_data.get("images"):
            reasons.append("listing_images_do_not_match_selected_assets")

        evidence_authority_sha256 = None
        if evidence_ids:
            try:
                evidence_projection = self.require_evidence(
                    evidence_ids=evidence_ids,
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=context["cutoff"],
                )
                evidence_authority_sha256 = evidence_projection[
                    "binding_authority_sha256"
                ]
            except ValueError:
                reasons.append("listing_evidence_not_scoped")
        else:
            reasons.append("listing_evidence_missing")

        return self._approval_plan(
            context=context,
            allowed=not reasons,
            reasons=sorted(set(reasons)),
            evidence_ids=evidence_ids,
            product_snapshot_sha256=(
                product_item["snapshot_sha256"]
                if product_item is not None
                else None
            ),
            evidence_authority_sha256=evidence_authority_sha256,
            inputs={
                "product_id": product_id,
                "offer_id": offer_id,
                "scenario_id": scenario_id,
                "content_asset_ids": content_asset_ids,
                "listing_data": listing_data,
            },
        )

    def _resolve_products(
        self,
        *,
        context: dict[str, Any],
        catalog: dict[str, Any],
        product_id: str | None,
    ) -> tuple[list[tuple[Product, str]], dict[str, int]]:
        scope = context["scope"]
        native = self.repository.list_products_scoped(
            tenant_ref=scope["tenant_ref"],
            entity_ref=scope["entity_ref"],
            store_ref=scope["store_ref"],
            as_of=context["cutoff"],
        )
        catalog_ids = sorted(
            {
                str(item.get("canonical_product_id") or "").strip()
                for item in catalog.get("items", [])
                if str(item.get("canonical_product_id") or "").strip()
            }
        )
        resolved: dict[str, tuple[Product, str]] = {
            item.id: (item, "native_product_scope") for item in native
        }
        excluded: dict[str, int] = {}
        for candidate_id in catalog_ids:
            if candidate_id in resolved:
                continue
            try:
                candidate = self.repository.get_product(candidate_id)
            except KeyError:
                excluded["catalog_product_missing"] = (
                    excluded.get("catalog_product_missing", 0) + 1
                )
                continue
            if candidate.scope_complete:
                excluded["native_catalog_scope_conflict"] = (
                    excluded.get("native_catalog_scope_conflict", 0) + 1
                )
                continue
            resolved[candidate.id] = (
                candidate,
                "scoped_catalog_canonical_binding",
            )
        if product_id is not None:
            item = resolved.get(product_id)
            return ([item] if item else []), excluded
        return [
            resolved[key] for key in sorted(resolved)
        ], excluded

    def _project_product(
        self,
        *,
        product: tuple[Product, str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        value, authority = product
        passports = self.repository.latest_passports(
            value.id,
            as_of=context["cutoff"],
        )
        assets = self.repository.content_assets_for_product(
            value.id,
            as_of=context["cutoff"],
        )
        evidence_ids = sorted(
            {
                *(
                    evidence_id
                    for passport in passports.values()
                    for evidence_id in passport.evidence
                ),
                *self._evidence_ids([asdict(asset) for asset in assets]),
            }
        )
        evidence_projection = self.scoped_evidence.project_targets(
            evidence_ids=evidence_ids,
            principal=context["principal"],
            entity_scope=context["entity_scope"],
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
        )
        ready_evidence = {
            item["evidence_id"]
            for item in evidence_projection["records"]
            if item["scope_binding"]["status"] == "ready"
            and item["evidence_id"]
            not in evidence_projection["invalid_evidence_ids"]
        }
        passport_rows = []
        for kind in PassportType:
            passport = passports.get(kind)
            item_evidence = set(passport.evidence) if passport else set()
            passport_rows.append(
                {
                    "kind": kind.value,
                    "id": passport.id if passport else None,
                    "version": passport.version if passport else None,
                    "status": (
                        "approved"
                        if passport
                        and passport.is_approved
                        and item_evidence
                        and item_evidence <= ready_evidence
                        else "blocked"
                        if passport
                        and (
                            passport.is_blocked
                            or bool(item_evidence - ready_evidence)
                        )
                        else "draft"
                        if passport
                        else "missing"
                    ),
                    "missing_fields": (
                        passport.missing_required_facts
                        if passport
                        else []
                    ),
                    "evidence_ids": sorted(item_evidence),
                    "evidence_ready": bool(item_evidence)
                    and item_evidence <= ready_evidence,
                    "approved_by": (
                        passport.approved_by if passport else None
                    ),
                }
            )
        asset_rows = []
        for asset in assets:
            item_evidence = self._evidence_ids(asdict(asset))
            asset_rows.append(
                {
                    "id": asset.id,
                    "content_type": asset.content_type.value,
                    "locale": asset.locale,
                    "channel": asset.channel,
                    "status": asset.status.value,
                    "artifact_ref": asset.artifact_ref,
                    "evidence_ids": sorted(item_evidence),
                    "evidence_ready": bool(item_evidence)
                    and item_evidence <= ready_evidence,
                    "qa_check_count": len(asset.qa_results),
                    "created_at": asset.created_at,
                }
            )
        passport_approved = all(
            item["status"] == "approved" for item in passport_rows
        )
        approved_assets = [
            item
            for item in asset_rows
            if item["status"] == ContentStatus.APPROVED.value
            and item["artifact_ref"]
            and item["evidence_ready"]
        ]
        source_gaps = []
        if not passport_approved:
            source_gaps.append("approved_passports_incomplete")
        if not approved_assets:
            source_gaps.append("approved_media_qa_incomplete")
        blocked_evidence = bool(
            evidence_projection["invalid_evidence_ids"]
            or any(
                item["scope_binding"]["status"] == "blocked"
                for item in evidence_projection["records"]
            )
        )
        blockers = (
            [
                self._blocker(
                    "product_content_evidence_scope_conflict",
                    owner="evidence-governance",
                    severity="P0",
                )
            ]
            if blocked_evidence
            else []
        )
        readiness = {
            "product_identity_ready": True,
            "passport_draft_allowed": True,
            "passport_approved": passport_approved,
            "content_draft_allowed": passport_approved,
            "media_qa_ready": bool(approved_assets),
            "listing_draft_allowed": False,
            "approval_plan_allowed": False,
            "approval_created": False,
            "permit_created": False,
            "external_write_allowed": False,
        }
        payload = {
            "product": {
                "id": value.id,
                "sku": value.sku,
                "name": value.name,
                "market": value.market,
                "channel": value.channel,
                "status": value.status.value,
                "created_at": value.created_at,
            },
            "scope_authority": authority,
            "passports": passport_rows,
            "content_assets": asset_rows,
            "evidence_ids": evidence_ids,
            "evidence_authority_sha256": evidence_projection.get(
                "binding_authority_sha256"
            ),
            "readiness": readiness,
            "source_gaps": source_gaps,
            "blockers": blockers,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _approval_plan(
        self,
        *,
        context: dict[str, Any],
        allowed: bool,
        reasons: list[str],
        evidence_ids: list[str],
        product_snapshot_sha256: str | None,
        evidence_authority_sha256: str | None,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        frozen = {
            "contract_id": self.APPROVAL_PLAN_CONTRACT_ID,
            "scope": context["scope"],
            "as_of": context["cutoff"].isoformat(),
            "inputs": inputs,
            "product_snapshot_sha256": product_snapshot_sha256,
            "evidence_authority_sha256": evidence_authority_sha256,
            "evidence_ids": evidence_ids,
            "reasons": reasons,
        }
        return {
            **frozen,
            "status": "ready" if allowed else "blocked",
            "allowed": allowed,
            "approval_plan_sha256": self._hash(frozen),
            "blockers": [
                self._blocker(reason, owner=self._owner(reason))
                for reason in reasons
            ],
            "control_envelope": {
                "read_only_plan": True,
                "listing_draft_created": False,
                "approval_created": False,
                "permit_created": False,
                "pilot_started": False,
                "external_write_allowed": False,
            },
        }

    def _result(
        self,
        *,
        context: dict[str, Any],
        status: str,
        products: list[dict[str, Any]],
        excluded: dict[str, int],
        source_gaps: list[str],
        blockers: list[dict[str, Any]],
        raw_read: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "products": products,
            "counts": {
                "included_products": len(products),
                "approved_passport_sets": sum(
                    item["readiness"]["passport_approved"]
                    for item in products
                ),
                "content_draft_ready": sum(
                    item["readiness"]["content_draft_allowed"]
                    for item in products
                ),
                "media_qa_ready": sum(
                    item["readiness"]["media_qa_ready"]
                    for item in products
                ),
                "listing_approval_plan_ready": 0,
            },
            "excluded": {
                "count": sum(excluded.values()),
                "by_reason": dict(sorted(excluded.items())),
                "details_disclosed": False,
            },
            "source_gaps": sorted(set(source_gaps)),
            "blockers": self._dedupe_blockers(blockers),
            "control_envelope": {
                "read_only": True,
                "raw_product_content_read": raw_read,
                "content_draft_allowed": any(
                    item["readiness"]["content_draft_allowed"]
                    for item in products
                ),
                "listing_draft_allowed": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _empty(self, *, context: dict[str, Any]) -> dict[str, Any]:
        reason = str(context["reason"])
        return self._result(
            context=context,
            status=context["status"],
            products=[],
            excluded={},
            source_gaps=[f"product_content_{reason}"],
            blockers=[self._blocker(reason, owner="identity-governance")],
            raw_read=False,
        )

    @staticmethod
    def _context(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        cutoff = as_of.astimezone(UTC)
        ready = (
            entity_scope.get("status") == "ready"
            and bool(entity_scope.get("entity_ref"))
        )
        status = (
            "ready"
            if ready
            else "blocked"
            if entity_scope.get("status") == "blocked"
            else "no_data"
        )
        return {
            "status": status,
            "reason": (
                None
                if ready
                else entity_scope.get(
                    "reason",
                    "entity_scope_authority_missing",
                )
            ),
            "cutoff": cutoff,
            "principal": principal,
            "entity_scope": entity_scope,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": (
                    str(entity_scope["entity_ref"]) if ready else None
                ),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": entity_scope.get(
                    "authority_sha256"
                ),
            },
        }

    @staticmethod
    def _product_from_projection(value: dict[str, Any]) -> Product:
        product = value["product"]
        return Product(
            sku=product["sku"],
            name=product["name"],
            market=product["market"],
            channel=product["channel"],
            status=ProductStatus(product["status"]),
            id=product["id"],
            created_at=product["created_at"],
        )

    @classmethod
    def _evidence_ids(cls, value: Any) -> set[str]:
        result: set[str] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key in {"artifact_ref", "evidence_ref"}
                    or key.endswith("evidence_id")
                ) and isinstance(child, str):
                    normalized = child.strip()
                    if normalized:
                        result.add(normalized)
                elif key.endswith("evidence_ids") and isinstance(child, list):
                    result.update(
                        item.strip()
                        for item in child
                        if isinstance(item, str) and item.strip()
                    )
                else:
                    result.update(cls._evidence_ids(child))
        elif isinstance(value, list):
            for child in value:
                result.update(cls._evidence_ids(child))
        return result

    @staticmethod
    def _owner(reason: str) -> str:
        if "evidence" in reason:
            return "evidence-governance"
        if "profit" in reason or "cm3" in reason or "offer" in reason:
            return "finance-sourcing"
        if "content" in reason or "media" in reason:
            return "content-governance"
        return "pim-governance"

    @staticmethod
    def _blocker(
        code: str,
        *,
        owner: str,
        severity: str = "P1",
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "owner": owner,
            "sla": "before content draft or Listing approval request",
            "next": (
                "Repair the exact scoped Product, Passport, content, "
                "economics or Evidence authority and rerun the plan."
            ),
            "next_workspace": "/commerce-os",
        }

    @staticmethod
    def _dedupe_blockers(
        blockers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for blocker in blockers:
            result[(blocker["code"], blocker["owner"])] = blocker
        return [result[key] for key in sorted(result)]

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
