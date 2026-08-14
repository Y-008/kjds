from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .media_workbench import TEMPLATE_CATALOG
from .security import Principal


class ScopedContentMediaFactoryWorkspace:
    """Project exact-scope ContentAsset execution, QA and delivery state."""

    CONTRACT_ID = "kjds-native-exact-scope-content-media-factory-v1"
    ARTIFACT_CONTRACT_ID = "kjds-media-steward-artifact-v1"
    PRODUCT_CONTENT_CONTRACT_ID = "kjds-scoped-product-content-v1"
    READ_SOURCE_CONTRACT_ID = "kjds-scoped-media-read-source-v1"
    STAGES = frozenset(
        {
            "brief",
            "source_rights_ready",
            "queued",
            "executing",
            "generated",
            "qa_pending",
            "qa_failed",
            "delivery_ready",
            "blocked",
        }
    )
    EXECUTION_STATUSES = frozenset(
        {
            "queued",
            "claimed",
            "generated",
            "approved",
            "qa_failed",
            "blocked",
            "failed",
            "execution_failed",
            "published",
        }
    )
    TRANSITIONS = {
        "queued": frozenset(
            {
                "claimed",
                "generated",
                "approved",
                "qa_failed",
                "failed",
                "execution_failed",
            }
        ),
        "claimed": frozenset({"claimed", "generated", "failed"}),
        "generated": frozenset(
            {"generated", "approved", "qa_failed", "failed"}
        ),
        "approved": frozenset({"approved", "published"}),
        "qa_failed": frozenset(
            {"qa_failed", "generated", "approved", "failed"}
        ),
        "blocked": frozenset({"blocked"}),
        "failed": frozenset({"failed"}),
        "execution_failed": frozenset({"execution_failed", "failed"}),
        "published": frozenset({"published"}),
    }
    REQUIRED_IMAGE_ROLES = (
        "hero",
        "dimensions",
        "benefits",
        "proof",
        "use_cases",
        "package",
        "aftersales",
    )
    REQUIRED_VIDEO_RATIOS = ("9:16", "1:1", "16:9")
    ROLE_ALIASES = {
        "main": "hero",
        "primary": "hero",
        "size": "dimensions",
        "dimension": "dimensions",
        "benefit": "benefits",
        "evidence": "proof",
        "use_case": "use_cases",
        "usage": "use_cases",
        "packaging": "package",
        "after_sales": "aftersales",
    }

    def __init__(self, *, product_content, media_workbench) -> None:
        self.product_content = product_content
        self.media_workbench = media_workbench

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        page_size: int = 50,
        cursor: str | None = None,
        query: str | None = None,
        stage: str | None = None,
        product_id: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= page_size <= 200:
            raise ValueError(
                "Media factory page_size must be between 1 and 200"
            )
        if stage is not None and stage not in self.STAGES:
            raise ValueError("Media factory stage filter is invalid")
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        normalized_query = str(query or "").strip().casefold()
        normalized_cursor = str(cursor or "").strip() or None
        if context["status"] != "ready":
            return self._result(
                context=context,
                status=context["status"],
                groups=[],
                total_groups=0,
                page_size=page_size,
                cursor=normalized_cursor,
                next_cursor=None,
                query=normalized_query,
                stage=stage,
                source_gaps=[
                    f"media_factory_{context['reason']}"
                ],
                blockers=[
                    self._blocker(str(context["reason"]))
                ],
                raw_read=False,
            )

        content = self.product_content.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            product_id=product_id,
        )
        conflicts = self._product_content_conflicts(
            projection=content,
            context=context,
        )
        if conflicts or content.get("status") == "blocked":
            gaps = sorted(
                {
                    *conflicts,
                    *self._strings(content.get("source_gaps")),
                }
            )
            return self._result(
                context=context,
                status="blocked",
                groups=[],
                total_groups=0,
                page_size=page_size,
                cursor=normalized_cursor,
                next_cursor=None,
                query=normalized_query,
                stage=stage,
                source_gaps=gaps,
                blockers=[
                    *[self._blocker(reason) for reason in conflicts],
                    *self._blockers(content.get("blockers")),
                ],
                upstream={
                    "product_content_snapshot_sha256": content.get(
                        "snapshot_sha256"
                    )
                },
            )

        product_rows = content.get("products", [])
        asset_ids = sorted(
            {
                str(asset.get("id") or "").strip()
                for product in product_rows
                for asset in product.get("content_assets", [])
                if str(asset.get("id") or "").strip()
            }
        )
        sources = self.media_workbench.read_sources(
            asset_ids=asset_ids,
            as_of=context["cutoff"],
        )
        source_conflicts = self._source_conflicts(
            projection=sources,
            context=context,
            asset_ids=asset_ids,
        )
        if source_conflicts:
            return self._result(
                context=context,
                status="blocked",
                groups=[],
                total_groups=0,
                page_size=page_size,
                cursor=normalized_cursor,
                next_cursor=None,
                query=normalized_query,
                stage=stage,
                source_gaps=source_conflicts,
                blockers=[
                    self._blocker(reason) for reason in source_conflicts
                ],
                raw_read=bool(sources.get("raw_read")),
                upstream={
                    "product_content_snapshot_sha256": content.get(
                        "snapshot_sha256"
                    ),
                    "media_source_snapshot_sha256": sources.get(
                        "snapshot_sha256"
                    ),
                },
            )

        raw_assets = self._unique_by_id(sources["assets"], "asset")
        executions_by_asset: dict[str, list[dict[str, Any]]] = {}
        for execution in sources["executions"]:
            executions_by_asset.setdefault(
                str(execution.get("asset_id") or ""), []
            ).append(execution)
        events_by_execution: dict[str, list[dict[str, Any]]] = {}
        for event in sources["events"]:
            events_by_execution.setdefault(
                str(event.get("execution_id") or ""), []
            ).append(event)
        manifests_by_asset: dict[str, list[dict[str, Any]]] = {}
        for manifest in sources["manifests"]:
            manifests_by_asset.setdefault(
                str(manifest.get("asset_id") or ""), []
            ).append(manifest)

        groups = [
            self._group(
                product=product,
                raw_assets=raw_assets,
                executions_by_asset=executions_by_asset,
                events_by_execution=events_by_execution,
                manifests_by_asset=manifests_by_asset,
                cutoff=context["cutoff"],
            )
            for product in product_rows
        ]
        groups.sort(key=self._group_sort_key)
        if normalized_query:
            groups = [
                group
                for group in groups
                if normalized_query in self._search_text(group)
            ]
        if stage is not None:
            groups = [
                group
                for group in groups
                if group["stage"] == stage
                or any(
                    asset["stage"] == stage
                    for asset in group["assets"]
                )
            ]
        total_groups = len(groups)
        total_counts = self._counts(groups)
        if normalized_cursor:
            cursor_key = self._decode_cursor(normalized_cursor)
            groups = [
                group
                for group in groups
                if self._group_sort_key(group) > cursor_key
            ]
        page = groups[:page_size]
        next_cursor = (
            self._encode_cursor(self._group_sort_key(page[-1]))
            if page and len(groups) > page_size
            else None
        )
        source_gaps = sorted(
            {
                *self._strings(content.get("source_gaps")),
                *(
                    gap
                    for group in page
                    for gap in group["source_gaps"]
                ),
            }
        )
        blockers = [
            *self._blockers(content.get("blockers")),
            *(
                blocker
                for group in page
                for blocker in group["blockers"]
            ),
        ]
        status = (
            "no_data"
            if not product_rows
            else "blocked"
            if total_counts["blocked"] == total_groups and total_groups
            else "partial"
            if source_gaps
            or total_counts["delivery_ready"] != total_groups
            else "ready"
        )
        return self._result(
            context=context,
            status=status,
            groups=page,
            total_groups=total_groups,
            page_size=page_size,
            cursor=normalized_cursor,
            next_cursor=next_cursor,
            query=normalized_query,
            stage=stage,
            source_gaps=source_gaps,
            blockers=blockers,
            raw_read=bool(sources.get("raw_read")),
            total_counts=total_counts,
            upstream={
                "product_content_snapshot_sha256": content[
                    "snapshot_sha256"
                ],
                "media_source_snapshot_sha256": sources[
                    "snapshot_sha256"
                ],
            },
        )

    def snapshot_scoped(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: str | datetime,
    ) -> dict[str, Any]:
        cutoff = (
            as_of
            if isinstance(as_of, datetime)
            else self._time(as_of)
        )
        if cutoff is None:
            raise ValueError(
                "Media factory as_of must be a timezone-aware timestamp"
            )
        return self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )

    def _group(
        self,
        *,
        product: dict[str, Any],
        raw_assets: dict[str, dict[str, Any]],
        executions_by_asset: dict[str, list[dict[str, Any]]],
        events_by_execution: dict[str, list[dict[str, Any]]],
        manifests_by_asset: dict[str, list[dict[str, Any]]],
        cutoff: datetime,
    ) -> dict[str, Any]:
        product_value = product.get("product", {})
        assets = [
            self._asset(
                projected=projected,
                raw=raw_assets.get(str(projected.get("id") or "")),
                product_id=str(product_value.get("id") or ""),
                executions=executions_by_asset.get(
                    str(projected.get("id") or ""), []
                ),
                events_by_execution=events_by_execution,
                manifests=manifests_by_asset.get(
                    str(projected.get("id") or ""), []
                ),
                cutoff=cutoff,
            )
            for projected in product.get("content_assets", [])
        ]
        assets.sort(key=lambda item: item["id"])
        coverage = self._coverage(assets)
        gaps = {
            *self._strings(product.get("source_gaps")),
            *(
                gap
                for asset in assets
                for gap in asset["source_gaps"]
            ),
        }
        if not assets:
            gaps.add("content_asset_missing")
        if coverage["image"]["missing_roles"]:
            gaps.add("image_role_coverage_incomplete")
        if coverage["video"]["present"] and coverage["video"][
            "missing_ratios"
        ]:
            gaps.add("video_ratio_coverage_incomplete")
        blockers = [
            *self._blockers(product.get("blockers")),
            *(
                blocker
                for asset in assets
                for blocker in asset["blockers"]
            ),
        ]
        if any(asset["stage"] == "blocked" for asset in assets):
            stage = "blocked"
        elif (
            assets
            and all(
                asset["stage"] == "delivery_ready"
                for asset in assets
            )
            and not coverage["image"]["missing_roles"]
            and not coverage["video"]["missing_ratios"]
        ):
            stage = "delivery_ready"
        elif assets:
            stage = min(
                (asset["stage"] for asset in assets),
                key=self._stage_rank,
            )
        else:
            stage = "brief"
        owner, next_action = self._owner_next(stage)
        payload = {
            "product": product_value,
            "product_content_snapshot_sha256": product.get(
                "snapshot_sha256"
            ),
            "stage": stage,
            "assets": assets,
            "coverage": coverage,
            "readiness": {
                "source_rights_ready": bool(assets)
                and all(
                    asset["readiness"]["source_rights_ready"]
                    for asset in assets
                ),
                "all_qa_passed": bool(assets)
                and all(
                    asset["readiness"]["qa_passed"]
                    for asset in assets
                ),
                "delivery_manifest_ready": bool(assets)
                and all(
                    asset["readiness"]["delivery_manifest_ready"]
                    for asset in assets
                ),
                "listing_media_ready": stage == "delivery_ready",
            },
            "source_gaps": sorted(gaps),
            "blockers": self._dedupe_blockers(blockers),
            "owner": owner,
            "sla": "before Listing media selection or publish review",
            "next": next_action,
            "next_workspace": "/media-factory",
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _asset(
        self,
        *,
        projected: dict[str, Any],
        raw: dict[str, Any] | None,
        product_id: str,
        executions: list[dict[str, Any]],
        events_by_execution: dict[str, list[dict[str, Any]]],
        manifests: list[dict[str, Any]],
        cutoff: datetime,
    ) -> dict[str, Any]:
        asset_id = str(projected.get("id") or "")
        issues: list[str] = []
        if raw is None:
            issues.append("content_asset_source_missing")
        else:
            if not isinstance(raw.get("brief"), dict):
                issues.append("content_asset_brief_invalid")
            if not isinstance(raw.get("source_facts"), dict):
                issues.append("content_asset_source_facts_invalid")
            if not isinstance(raw.get("generation"), dict):
                issues.append("content_asset_generation_invalid")
            expected = {
                "product_id": product_id,
                "content_type": projected.get("content_type"),
                "locale": projected.get("locale"),
                "channel": projected.get("channel"),
                "status": projected.get("status"),
                "artifact_ref": projected.get("artifact_ref"),
            }
            for field, value in expected.items():
                if raw.get(field) != value:
                    issues.append(f"content_asset_{field}_drift")
            if len(raw.get("qa_results", [])) != projected.get(
                "qa_check_count"
            ):
                issues.append("content_asset_qa_count_drift")
            if self._time(raw.get("created_at")) != self._time(
                projected.get("created_at")
            ):
                issues.append("content_asset_created_at_drift")
            if self._future_asset_state(raw, cutoff=cutoff):
                issues.append("content_asset_future_state_unprovable")
            template = self._template(raw)
            if template.get("kind") != raw.get("content_type"):
                issues.append("content_asset_template_kind_mismatch")
            qa_results = raw.get("qa_results")
            if (
                raw.get("status") == "approved"
                and (
                    not isinstance(qa_results, list)
                    or not qa_results
                    or not all(
                        isinstance(item, dict)
                        and item.get("passed") is True
                        for item in qa_results
                    )
                )
            ):
                issues.append("content_asset_qa_state_invalid")
            if (
                raw.get("status") == "qa_failed"
                and (
                    not isinstance(qa_results, list)
                    or not any(
                        isinstance(item, dict)
                        and item.get("passed") is False
                        for item in qa_results
                    )
                )
            ):
                issues.append("content_asset_qa_state_invalid")
            if raw.get("status") in {"generated", "approved"} and not str(
                raw.get("artifact_ref") or ""
            ).strip():
                issues.append("content_asset_artifact_missing")
        evidence_ids = self._strings(projected.get("evidence_ids"))
        evidence_ready = bool(projected.get("evidence_ready"))
        if evidence_ids and not evidence_ready:
            issues.append("content_asset_evidence_invalid")

        safe_executions: list[dict[str, Any]] = []
        if raw is not None:
            attempts = sorted(
                executions,
                key=lambda item: (
                    int(item.get("attempt") or 0),
                    str(item.get("queued_at") or ""),
                    str(item.get("id") or ""),
                ),
            )
            if [item.get("attempt") for item in attempts] != list(
                range(1, len(attempts) + 1)
            ):
                issues.append("media_execution_attempt_sequence_invalid")
            prior_time: datetime | None = None
            for execution in attempts:
                queued_at = self._time(execution.get("queued_at"))
                if (
                    prior_time is not None
                    and queued_at is not None
                    and queued_at < prior_time
                ):
                    issues.append(
                        "media_execution_attempt_time_invalid"
                    )
                prior_time = queued_at or prior_time
                safe, execution_issues = self._execution(
                    asset=raw,
                    execution=execution,
                    events=events_by_execution.get(
                        str(execution.get("id") or ""), []
                    ),
                    cutoff=cutoff,
                )
                issues.extend(execution_issues)
                if safe is not None:
                    safe_executions.append(safe)
        safe_executions.sort(
            key=lambda item: (
                int(item["attempt"]),
                item["queued_at"],
                item["id"],
            )
        )
        latest = safe_executions[-1] if safe_executions else None

        latest_manifest = None
        if raw is not None and manifests:
            selected = max(
                manifests,
                key=lambda item: (
                    str(item.get("created_at") or ""),
                    str(item.get("id") or ""),
                ),
            )
            latest_manifest, manifest_issues = self._manifest(
                asset=raw,
                manifest=selected,
                executions=safe_executions,
                cutoff=cutoff,
            )
            issues.extend(manifest_issues)

        issues = sorted(set(issues))
        if issues:
            return self._blocked_asset(
                asset_id=asset_id,
                projected=projected,
                issues=issues,
            )
        assert raw is not None
        qa_results = raw.get("qa_results")
        qa_results = qa_results if isinstance(qa_results, list) else []
        qa_passed = bool(qa_results) and all(
            item.get("passed") is True
            for item in qa_results
            if isinstance(item, dict)
        )
        source_rights_ready = bool(evidence_ids) and evidence_ready
        manifest_ready = bool(
            latest_manifest
            and latest_manifest.get("listing_eligible") is True
        )
        stage = self._asset_stage(
            status=str(raw.get("status") or ""),
            source_rights_ready=source_rights_ready,
            latest_execution=latest,
            manifest_ready=manifest_ready,
        )
        gaps: list[str] = []
        template = self._template(raw)
        if template["status"] != "admitted" or not template.get(
            "fixed_workflow", False
        ):
            stage = "blocked"
            gaps.append("content_asset_template_not_admitted")
        if not evidence_ids:
            gaps.append("content_asset_evidence_missing")
        if not source_rights_ready:
            gaps.append("content_asset_source_rights_not_ready")
        if raw.get("status") == "approved" and not latest_manifest:
            gaps.append("delivery_manifest_missing")
        if latest and latest["status"] in {
            "blocked",
            "failed",
            "execution_failed",
        }:
            gaps.append("media_execution_failed_or_blocked")
        owner, next_action = self._owner_next(stage)
        return {
            "id": asset_id,
            "product_id": product_id,
            "content_type": raw["content_type"],
            "locale": raw["locale"],
            "channel": raw["channel"],
            "status": raw["status"],
            "artifact_ref": raw.get("artifact_ref"),
            "brief": raw.get("brief", {}),
            "source_facts": raw.get("source_facts", {}),
            "qa_results": qa_results,
            "generation": raw.get("generation", {}),
            "created_at": raw["created_at"],
            "template": template,
            "role": self._role(raw),
            "aspect_ratios": self._ratios(raw),
            "stage": stage,
            "latest_execution": latest,
            "execution_timeline": safe_executions,
            "delivery_manifest": latest_manifest,
            "readiness": {
                "source_rights_ready": source_rights_ready,
                "template_admitted": template["status"] == "admitted"
                and bool(template.get("fixed_workflow")),
                "execution_retry_allowed": bool(
                    latest
                    and latest["status"]
                    in {"blocked", "failed", "execution_failed"}
                )
                or raw["status"] in {
                    "qa_failed",
                    "execution_failed",
                },
                "qa_passed": raw["status"] == "approved"
                and qa_passed,
                "delivery_manifest_ready": manifest_ready,
            },
            "evidence_ids": evidence_ids,
            "source_gaps": sorted(set(gaps)),
            "blockers": [],
            "owner": owner,
            "sla": "before Listing media selection or publish review",
            "next": next_action,
            "next_workspace": "/media-factory",
        }

    def _execution(
        self,
        *,
        asset: dict[str, Any],
        execution: dict[str, Any],
        events: list[dict[str, Any]],
        cutoff: datetime,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        issues: list[str] = []
        if execution.get("asset_id") != asset.get("id"):
            issues.append("media_execution_asset_mismatch")
        template = self._template(asset)
        if execution.get("media_kind") != asset.get("content_type"):
            issues.append("media_execution_kind_mismatch")
        if execution.get("template_id") != template["id"]:
            issues.append("media_execution_template_drift")
        expected_input = self._hash(
            {
                "asset_id": asset.get("id"),
                "product_id": asset.get("product_id"),
                "content_type": asset.get("content_type"),
                "brief": asset.get("brief", {}),
                "template_id": template["id"],
            }
        )
        if execution.get("input_sha256") != expected_input:
            issues.append("media_execution_input_hash_drift")
        queued_at = self._time(execution.get("queued_at"))
        if queued_at is None or queued_at > cutoff:
            issues.append("media_execution_time_invalid")
        for field in (
            "lease_expires_at",
            "started_at",
            "completed_at",
        ):
            value = execution.get(field)
            parsed = self._time(value)
            if value is not None and (
                parsed is None or parsed > cutoff
            ):
                issues.append(f"media_execution_{field}_invalid")
        try:
            cost = Decimal(str(execution.get("cost", {}).get("amount")))
            if not cost.is_finite() or cost < 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            issues.append("media_execution_cost_invalid")
        currency = str(
            execution.get("cost", {}).get("currency") or ""
        )
        if (
            len(currency) != 3
            or not currency.isascii()
            or not currency.isalpha()
            or currency != currency.upper()
        ):
            issues.append("media_execution_currency_invalid")
        status = str(execution.get("status") or "")
        if status not in self.EXECUTION_STATUSES:
            issues.append("media_execution_status_invalid")

        ordered = sorted(
            events,
            key=lambda item: (
                int(item.get("sequence") or 0),
                str(item.get("occurred_at") or ""),
                str(item.get("id") or ""),
            ),
        )
        if not ordered:
            issues.append("media_execution_event_missing")
        previous_status: str | None = None
        previous_time: datetime | None = None
        for index, event in enumerate(ordered, start=1):
            event_time = self._time(event.get("occurred_at"))
            if event.get("execution_id") != execution.get("id"):
                issues.append("media_execution_event_parent_mismatch")
            if event.get("sequence") != index:
                issues.append("media_execution_event_sequence_invalid")
            if event_time is None or (
                queued_at is not None and event_time < queued_at
            ):
                issues.append("media_execution_event_time_invalid")
            if (
                previous_time is not None
                and event_time is not None
                and event_time < previous_time
            ):
                issues.append("media_execution_event_time_invalid")
            from_status = event.get("from_status")
            to_status = str(event.get("to_status") or "")
            if index == 1:
                if from_status is not None:
                    issues.append(
                        "media_execution_event_initial_state_invalid"
                    )
                if to_status not in {
                    "queued",
                    "blocked",
                    "generated",
                    "failed",
                    "execution_failed",
                }:
                    issues.append(
                        "media_execution_event_transition_invalid"
                    )
            else:
                if from_status != previous_status:
                    issues.append(
                        "media_execution_event_transition_invalid"
                    )
                if to_status not in self.TRANSITIONS.get(
                    str(previous_status), frozenset()
                ):
                    issues.append(
                        "media_execution_event_transition_invalid"
                    )
            if not self._event_type_matches(event):
                issues.append("media_execution_event_type_invalid")
            previous_status = to_status
            previous_time = event_time or previous_time
        if ordered and previous_status != status:
            issues.append("media_execution_latest_state_mismatch")
        if execution.get("external_side_effect") is not False:
            issues.append("media_execution_side_effect_contract_invalid")
        if issues:
            return None, sorted(set(issues))
        return {
            **execution,
            "events": ordered,
            "event_count": len(ordered),
        }, []

    def _manifest(
        self,
        *,
        asset: dict[str, Any],
        manifest: dict[str, Any],
        executions: list[dict[str, Any]],
        cutoff: datetime,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        issues: list[str] = []
        payload = manifest.get("payload")
        if not isinstance(payload, dict):
            return None, ["media_manifest_payload_invalid"]
        if manifest.get("asset_id") != asset.get("id"):
            issues.append("media_manifest_asset_mismatch")
        for field, expected in (
            ("contract_id", "kjds-media-delivery-manifest-v1"),
            ("manifest_id", manifest.get("id")),
            ("asset_id", asset.get("id")),
            ("product_id", asset.get("product_id")),
            ("content_type", asset.get("content_type")),
        ):
            if payload.get(field) != expected:
                issues.append(f"media_manifest_{field}_mismatch")
        row_time = self._time(manifest.get("created_at"))
        payload_time = self._time(payload.get("created_at"))
        if (
            row_time is None
            or payload_time is None
            or row_time > cutoff
            or payload_time > cutoff
            or abs((row_time - payload_time).total_seconds()) > 5
        ):
            issues.append("media_manifest_time_invalid")
        if payload.get("external_marketplace_write") is not False:
            issues.append("media_manifest_external_write_invalid")
        stored_sha = str(manifest.get("manifest_sha256") or "")
        if (
            payload.get("manifest_sha256") != stored_sha
            or self._hash(
                {
                    key: value
                    for key, value in payload.items()
                    if key != "manifest_sha256"
                }
            )
            != stored_sha
        ):
            issues.append("media_manifest_hash_invalid")
        evidence_ids = sorted(
            {
                str(value).strip()
                for value in [
                    asset.get("artifact_ref"),
                    *self._mapping_values(
                        asset.get("generation", {}).get(
                            "outputs", {}
                        )
                    ),
                    *self._mapping_values(
                        asset.get("generation", {}).get(
                            "auxiliaries", {}
                        )
                    ),
                ]
                if str(value or "").strip()
            }
        )
        state = {
            "asset_id": asset.get("id"),
            "product_id": asset.get("product_id"),
            "content_type": asset.get("content_type"),
            "status": asset.get("status"),
            "artifact_evidence_ids": evidence_ids,
            "qa_results": asset.get("qa_results", []),
            "generation": asset.get("generation", {}),
        }
        if self._hash(state) != manifest.get("asset_state_sha256"):
            issues.append("media_manifest_asset_state_drift")
        if payload.get("artifact_evidence_ids") != evidence_ids:
            issues.append("media_manifest_evidence_drift")
        execution_id = str(manifest.get("execution_id") or "")
        execution = next(
            (
                item
                for item in executions
                if item.get("id") == execution_id
            ),
            None,
        )
        if execution_id and execution is None:
            issues.append("media_manifest_execution_mismatch")
        if execution is not None:
            if payload.get("input_sha256") != execution.get(
                "input_sha256"
            ):
                issues.append("media_manifest_input_hash_drift")
            if payload.get("template_id") != execution.get(
                "template_id"
            ):
                issues.append("media_manifest_template_drift")
            if payload.get("latency_ms") != execution.get("latency_ms"):
                issues.append("media_manifest_latency_drift")
            if payload.get("cost") != execution.get("cost"):
                issues.append("media_manifest_cost_drift")
        qa_results = asset.get("qa_results")
        qa_passed = isinstance(qa_results, list) and bool(
            qa_results
        ) and all(
            isinstance(item, dict) and item.get("passed") is True
            for item in qa_results
        )
        if (
            asset.get("status") != "approved"
            or not qa_passed
            or payload.get("qa_status") != "passed"
            or payload.get("listing_eligible") is not True
        ):
            issues.append("media_manifest_listing_eligibility_invalid")
        if payload.get("encoder_version") != asset.get(
            "generation", {}
        ).get("encoder_version"):
            issues.append("media_manifest_encoder_drift")
        if issues:
            return None, sorted(set(issues))
        return payload, []

    def _result(
        self,
        *,
        context: dict[str, Any],
        status: str,
        groups: list[dict[str, Any]],
        total_groups: int,
        page_size: int,
        cursor: str | None,
        next_cursor: str | None,
        query: str,
        stage: str | None,
        source_gaps: list[str],
        blockers: list[dict[str, Any]],
        raw_read: bool,
        total_counts: dict[str, int] | None = None,
        upstream: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        counts = total_counts or self._counts(groups)
        assets = [
            asset
            for group in groups
            for asset in group["assets"]
        ]
        executions = [
            execution
            for asset in assets
            for execution in asset.get("execution_timeline", [])
        ]
        manifests = [
            asset["delivery_manifest"]
            for asset in assets
            if asset.get("delivery_manifest")
        ]
        deduped_blockers = self._dedupe_blockers(blockers)
        core = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "query": {
                "page_size": page_size,
                "cursor": cursor,
                "next_cursor": next_cursor,
                "search": query or None,
                "stage": stage,
            },
            "counts": {
                **counts,
                "total_product_groups": total_groups,
                "page_product_groups": len(groups),
            },
            "product_groups": groups,
            "templates": [
                dict(template) for template in TEMPLATE_CATALOG
            ],
            "assets": assets,
            "executions": executions,
            "manifests": manifests,
            "summary": {
                "asset_count": counts["assets"],
                "execution_count": counts["executions"],
                "failed_count": counts["failed_executions"],
                "blocked_count": counts["blocked_assets"],
                "manifest_count": counts["manifests"],
            },
            "source_gaps": sorted(set(source_gaps)),
            "blockers": deduped_blockers,
            "upstream_authority": upstream or {},
            "control_envelope": {
                "read_only": True,
                "scoped_input_read": raw_read,
                "client_recalculation_allowed": False,
                "postgres_lease_only": True,
                "redis_kafka_temporal_used": False,
                "fixed_templates_only": True,
                "external_video_provider_enabled": False,
                "listing_requires_all_qa_passed": True,
                "asset_created": False,
                "job_created": False,
                "qa_decided": False,
                "manifest_created": False,
                "listing_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_marketplace_write_allowed": False,
                "external_write_allowed": False,
            },
            "external_write_allowed": False,
        }
        input_hash = self._hash(core)
        suggestions = [
            {
                "product_id": group["product"].get("id"),
                "stage": group["stage"],
                "owner": group["owner"],
                "next": group["next"],
            }
            for group in groups
            if group["stage"] != "delivery_ready"
        ]
        artifact_core = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "version": "1",
            "scope": context["scope"],
            "as_of": context["cutoff"].isoformat(),
            "input_snapshot_sha256": input_hash,
            "suggestions": suggestions,
            "authority": (
                "decision_support_and_internal_task_suggestion_only"
            ),
            "owner": "content-operations",
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "asset_or_job_creation_allowed": False,
            "qa_or_manifest_creation_allowed": False,
            "external_write_allowed": False,
        }
        core["agent_artifact"] = {
            **artifact_core,
            "artifact_sha256": self._hash(artifact_core),
        }
        core["snapshot_sha256"] = self._hash(core)
        return core

    @classmethod
    def _product_content_conflicts(
        cls,
        *,
        projection: dict[str, Any],
        context: dict[str, Any],
    ) -> list[str]:
        conflicts: list[str] = []
        if projection.get("contract_id") != (
            cls.PRODUCT_CONTENT_CONTRACT_ID
        ):
            conflicts.append("product_content_contract_conflict")
        if projection.get("status") not in {
            "ready",
            "partial",
            "no_data",
            "blocked",
        }:
            conflicts.append("product_content_status_conflict")
        if projection.get("scope") != context["scope"]:
            conflicts.append("product_content_scope_conflict")
        if projection.get("as_of") != context["cutoff"].isoformat():
            conflicts.append("product_content_as_of_conflict")
        if not isinstance(projection.get("products"), list):
            conflicts.append("product_content_products_invalid")
        if not cls._valid_snapshot(projection):
            conflicts.append("product_content_snapshot_integrity_invalid")
        return sorted(set(conflicts))

    @classmethod
    def _source_conflicts(
        cls,
        *,
        projection: dict[str, Any],
        context: dict[str, Any],
        asset_ids: list[str],
    ) -> list[str]:
        conflicts: list[str] = []
        if projection.get("contract_id") != cls.READ_SOURCE_CONTRACT_ID:
            conflicts.append("media_source_contract_conflict")
        if projection.get("as_of") != context["cutoff"].isoformat():
            conflicts.append("media_source_as_of_conflict")
        if projection.get("authorized_asset_ids") != asset_ids:
            conflicts.append("media_source_asset_authority_conflict")
        if not cls._valid_snapshot(projection):
            conflicts.append("media_source_snapshot_integrity_invalid")
        truncated = projection.get("truncated")
        if not isinstance(truncated, dict):
            conflicts.append("media_source_truncation_contract_invalid")
        else:
            expected_truncation = {
                "assets",
                "executions",
                "events",
                "manifests",
            }
            if (
                set(truncated) != expected_truncation
                or any(
                    not isinstance(value, bool)
                    for value in truncated.values()
                )
            ):
                conflicts.append(
                    "media_source_truncation_contract_invalid"
                )
            elif any(truncated.values()):
                conflicts.append("media_source_projection_truncated")
        for field in ("assets", "executions", "events", "manifests"):
            if not isinstance(projection.get(field), list):
                conflicts.append(f"media_source_{field}_invalid")
        assets = projection.get("assets")
        executions = projection.get("executions")
        events = projection.get("events")
        manifests = projection.get("manifests")
        if all(
            isinstance(value, list)
            for value in (assets, executions, events, manifests)
        ):
            asset_row_ids = [
                str(item.get("id") or "")
                for item in assets
                if isinstance(item, dict)
            ]
            if (
                len(asset_row_ids) != len(assets)
                or len(asset_row_ids) != len(set(asset_row_ids))
                or sorted(asset_row_ids) != asset_ids
            ):
                conflicts.append("media_source_asset_rows_conflict")
            execution_ids = [
                str(item.get("id") or "")
                for item in executions
                if isinstance(item, dict)
            ]
            execution_asset_ids = {
                str(item.get("asset_id") or "")
                for item in executions
                if isinstance(item, dict)
            }
            if (
                len(execution_ids) != len(executions)
                or len(execution_ids) != len(set(execution_ids))
                or not execution_asset_ids <= set(asset_ids)
            ):
                conflicts.append(
                    "media_source_execution_rows_conflict"
                )
            event_ids = [
                str(item.get("id") or "")
                for item in events
                if isinstance(item, dict)
            ]
            event_execution_ids = {
                str(item.get("execution_id") or "")
                for item in events
                if isinstance(item, dict)
            }
            if (
                len(event_ids) != len(events)
                or len(event_ids) != len(set(event_ids))
                or not event_execution_ids <= set(execution_ids)
            ):
                conflicts.append("media_source_event_rows_conflict")
            manifest_ids = [
                str(item.get("id") or "")
                for item in manifests
                if isinstance(item, dict)
            ]
            manifest_asset_ids = {
                str(item.get("asset_id") or "")
                for item in manifests
                if isinstance(item, dict)
            }
            manifest_execution_ids = {
                str(item.get("execution_id") or "")
                for item in manifests
                if isinstance(item, dict)
                and item.get("execution_id") is not None
            }
            if (
                len(manifest_ids) != len(manifests)
                or len(manifest_ids) != len(set(manifest_ids))
                or not manifest_asset_ids <= set(asset_ids)
                or not manifest_execution_ids <= set(execution_ids)
            ):
                conflicts.append(
                    "media_source_manifest_rows_conflict"
                )
        if asset_ids and projection.get("raw_read") is not True:
            conflicts.append("media_source_raw_read_missing")
        if not asset_ids and projection.get("raw_read") is not False:
            conflicts.append("media_source_unnecessary_raw_read")
        return sorted(set(conflicts))

    @classmethod
    def _coverage(
        cls, assets: list[dict[str, Any]]
    ) -> dict[str, Any]:
        valid = [
            asset for asset in assets if asset["stage"] != "blocked"
        ]
        image_roles = sorted(
            {
                asset["role"]
                for asset in valid
                if asset.get("content_type") == "image"
                and asset.get("role")
            }
        )
        ready_roles = sorted(
            {
                asset["role"]
                for asset in valid
                if asset.get("content_type") == "image"
                and asset.get("role")
                and asset["readiness"]["delivery_manifest_ready"]
            }
        )
        video_ratios = sorted(
            {
                ratio
                for asset in valid
                if asset.get("content_type") == "video"
                for ratio in asset.get("aspect_ratios", [])
            }
        )
        ready_ratios = sorted(
            {
                ratio
                for asset in valid
                if asset.get("content_type") == "video"
                and asset["readiness"]["delivery_manifest_ready"]
                for ratio in asset.get("aspect_ratios", [])
            }
        )
        return {
            "image": {
                "required_roles": list(cls.REQUIRED_IMAGE_ROLES),
                "observed_roles": image_roles,
                "delivery_ready_roles": ready_roles,
                "missing_roles": sorted(
                    set(cls.REQUIRED_IMAGE_ROLES) - set(ready_roles)
                ),
            },
            "video": {
                "present": any(
                    asset.get("content_type") == "video"
                    for asset in valid
                ),
                "required_ratios": list(cls.REQUIRED_VIDEO_RATIOS),
                "observed_ratios": video_ratios,
                "delivery_ready_ratios": ready_ratios,
                "missing_ratios": (
                    sorted(
                        set(cls.REQUIRED_VIDEO_RATIOS)
                        - set(ready_ratios)
                    )
                    if any(
                        asset.get("content_type") == "video"
                        for asset in valid
                    )
                    else []
                ),
            },
        }

    @staticmethod
    def _counts(groups: list[dict[str, Any]]) -> dict[str, int]:
        assets = [
            asset for group in groups for asset in group["assets"]
        ]
        executions = [
            execution
            for asset in assets
            for execution in asset.get("execution_timeline", [])
        ]
        return {
            "assets": len(assets),
            "image_assets": sum(
                asset.get("content_type") == "image"
                for asset in assets
            ),
            "video_assets": sum(
                asset.get("content_type") == "video"
                for asset in assets
            ),
            "executions": len(executions),
            "failed_executions": sum(
                execution.get("status")
                in {"failed", "blocked", "execution_failed"}
                for execution in executions
            ),
            "manifests": sum(
                bool(asset.get("delivery_manifest"))
                for asset in assets
            ),
            "blocked_assets": sum(
                asset["stage"] == "blocked" for asset in assets
            ),
            "delivery_ready": sum(
                group["stage"] == "delivery_ready"
                for group in groups
            ),
            "blocked": sum(
                group["stage"] == "blocked" for group in groups
            ),
        }

    @classmethod
    def _asset_stage(
        cls,
        *,
        status: str,
        source_rights_ready: bool,
        latest_execution: dict[str, Any] | None,
        manifest_ready: bool,
    ) -> str:
        if manifest_ready and status == "approved":
            return "delivery_ready"
        if status == "qa_failed":
            return "qa_failed"
        if status in {"execution_failed"}:
            return "blocked"
        if latest_execution is not None:
            execution_status = latest_execution["status"]
            if execution_status == "claimed":
                return "executing"
            if execution_status == "queued":
                return "queued"
            if execution_status in {
                "blocked",
                "failed",
                "execution_failed",
            }:
                return "blocked"
            if execution_status in {"generated", "approved"}:
                return (
                    "qa_pending"
                    if status == "generated"
                    else "generated"
                )
        if status == "generated":
            return "qa_pending"
        if status == "approved":
            return "generated"
        if source_rights_ready:
            return "source_rights_ready"
        return "brief"

    @classmethod
    def _blocked_asset(
        cls,
        *,
        asset_id: str,
        projected: dict[str, Any],
        issues: list[str],
    ) -> dict[str, Any]:
        blockers = [cls._blocker(issue) for issue in issues]
        return {
            "id": asset_id,
            "product_id": None,
            "content_type": projected.get("content_type"),
            "locale": None,
            "channel": None,
            "status": "blocked",
            "artifact_ref": None,
            "brief": {},
            "source_facts": {},
            "qa_results": [],
            "generation": {},
            "created_at": None,
            "template": None,
            "role": None,
            "aspect_ratios": [],
            "stage": "blocked",
            "latest_execution": None,
            "execution_timeline": [],
            "delivery_manifest": None,
            "readiness": {
                "source_rights_ready": False,
                "template_admitted": False,
                "execution_retry_allowed": False,
                "qa_passed": False,
                "delivery_manifest_ready": False,
            },
            "evidence_ids": [],
            "source_gaps": issues,
            "blockers": blockers,
            "owner": "content-evidence-governance",
            "sla": "before Listing media selection or publish review",
            "next": (
                "Repair the scoped ContentAsset, Evidence, execution "
                "timeline or Manifest authority and rerun projection."
            ),
            "next_workspace": "/media-factory",
        }

    @classmethod
    def _template(cls, asset: dict[str, Any]) -> dict[str, Any]:
        brief = asset.get("brief")
        brief = brief if isinstance(brief, dict) else {}
        requested = str(brief.get("template_id") or "").strip()
        if not requested:
            requested = (
                "ozon-retouch-v1"
                if asset.get("content_type") == "image"
                else "kjds-ffmpeg-product-video-v1"
            )
        for template in TEMPLATE_CATALOG:
            if template["id"] == requested:
                return dict(template)
        return {
            "id": requested,
            "kind": asset.get("content_type"),
            "version": "unknown",
            "status": "blocked",
            "executor": "unknown",
            "fixed_workflow": False,
        }

    @classmethod
    def _role(cls, asset: dict[str, Any]) -> str | None:
        if asset.get("content_type") != "image":
            return None
        brief = asset.get("brief")
        brief = brief if isinstance(brief, dict) else {}
        value = str(
            brief.get("role") or brief.get("variant") or ""
        ).strip().casefold()
        return cls.ROLE_ALIASES.get(value, value) or None

    @classmethod
    def _ratios(cls, asset: dict[str, Any]) -> list[str]:
        if asset.get("content_type") != "video":
            return []
        brief = asset.get("brief")
        brief = brief if isinstance(brief, dict) else {}
        values = brief.get("aspect_ratios")
        if not isinstance(values, list):
            return []
        return sorted(
            {
                str(value).strip()
                for value in values
                if str(value).strip()
            }
        )

    @classmethod
    def _future_asset_state(
        cls, asset: dict[str, Any], *, cutoff: datetime
    ) -> bool:
        generation = asset.get("generation")
        generation = generation if isinstance(generation, dict) else {}
        for field, value in generation.items():
            if not str(field).endswith("_at") or value is None:
                continue
            parsed = cls._time(value)
            if parsed is None or parsed > cutoff:
                return True
        qa_results = asset.get("qa_results")
        if not isinstance(qa_results, list):
            return True
        for item in qa_results:
            if not isinstance(item, dict):
                return True
            reviewed_at = item.get("reviewed_at")
            parsed_review = cls._time(reviewed_at)
            if reviewed_at is not None and (
                parsed_review is None or parsed_review > cutoff
            ):
                return True
        return False

    @classmethod
    def _event_type_matches(cls, event: dict[str, Any]) -> bool:
        event_type = str(event.get("event_type") or "")
        to_status = str(event.get("to_status") or "")
        if event_type == "synced":
            return to_status in cls.EXECUTION_STATUSES
        return event_type == to_status or (
            event_type == "queued" and to_status == "queued"
        )

    @staticmethod
    def _owner_next(stage: str) -> tuple[str, str]:
        if stage == "brief":
            return (
                "content-operations",
                "Create an Evidence-backed media brief and source-rights package.",
            )
        if stage == "source_rights_ready":
            return (
                "media-operator",
                "Queue the admitted fixed workflow through the scoped mutation endpoint.",
            )
        if stage in {"queued", "executing"}:
            return (
                "media-operator",
                "Observe the PostgreSQL lease and append-only execution timeline.",
            )
        if stage in {"generated", "qa_pending"}:
            return (
                "content-reviewer",
                "Perform independent QA with Evidence for every required check.",
            )
        if stage == "qa_failed":
            return (
                "content-operations",
                "Repair failed QA findings, generate a new artifact and re-review.",
            )
        if stage == "delivery_ready":
            return (
                "listing-operator",
                "Select the immutable Delivery Manifest in Listing review.",
            )
        return (
            "content-evidence-governance",
            "Repair the latest authority conflict before any media or Listing action.",
        )

    @staticmethod
    def _stage_rank(stage: str) -> int:
        order = {
            "brief": 0,
            "source_rights_ready": 1,
            "queued": 2,
            "executing": 3,
            "generated": 4,
            "qa_pending": 5,
            "qa_failed": 6,
            "delivery_ready": 7,
            "blocked": 8,
        }
        return order.get(stage, 99)

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
        authority_sha256 = str(
            entity_scope.get("authority_sha256") or ""
        ).strip()
        entity_present = bool(entity_scope.get("entity_ref"))
        ready = (
            entity_scope.get("status") == "ready"
            and entity_present
            and len(authority_sha256) == 64
        )
        invalid_ready = (
            entity_scope.get("status") == "ready"
            and (not entity_present or len(authority_sha256) != 64)
        )
        return {
            "status": (
                "ready"
                if ready
                else "blocked"
                if entity_scope.get("status") == "blocked"
                or invalid_ready
                else "no_data"
            ),
            "reason": (
                None
                if ready
                else "entity_scope_authority_invalid"
                if invalid_ready
                else entity_scope.get(
                    "reason", "entity_scope_authority_missing"
                )
            ),
            "cutoff": cutoff,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": (
                    str(entity_scope["entity_ref"]) if ready else None
                ),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    authority_sha256 if ready else None
                ),
            },
        }

    @staticmethod
    def _group_sort_key(
        group: dict[str, Any],
    ) -> tuple[str, str]:
        product = group.get("product", {})
        return (
            str(product.get("sku") or ""),
            str(product.get("id") or ""),
        )

    @classmethod
    def _search_text(cls, group: dict[str, Any]) -> str:
        product = group.get("product", {})
        return " ".join(
            [
                str(product.get("sku") or ""),
                str(product.get("name") or ""),
                str(product.get("id") or ""),
                *(
                    " ".join(
                        [
                            str(asset.get("id") or ""),
                            str(asset.get("content_type") or ""),
                            str(asset.get("role") or ""),
                            str(
                                (
                                    asset.get("template") or {}
                                ).get("id")
                                or ""
                            ),
                        ]
                    )
                    for asset in group.get("assets", [])
                ),
            ]
        ).casefold()

    @staticmethod
    def _unique_by_id(
        values: list[dict[str, Any]], label: str
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for value in values:
            identifier = str(value.get("id") or "")
            if not identifier or identifier in result:
                raise ValueError(f"Media {label} source IDs are invalid")
            result[identifier] = value
        return result

    @staticmethod
    def _mapping_values(value: Any) -> list[Any]:
        return list(value.values()) if isinstance(value, dict) else []

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return sorted(
            {
                str(item).strip()
                for item in value
                if isinstance(item, str) and item.strip()
            }
        )

    @staticmethod
    def _blockers(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            item
            for item in value
            if isinstance(item, dict) and item.get("code")
        ]

    @staticmethod
    def _blocker(code: str) -> dict[str, Any]:
        return {
            "code": code,
            "severity": (
                "P0"
                if any(
                    marker in code
                    for marker in (
                        "conflict",
                        "invalid",
                        "drift",
                        "mismatch",
                        "truncated",
                        "future",
                    )
                )
                else "P1"
            ),
            "owner": (
                "identity-governance"
                if "entity_scope" in code
                else "content-evidence-governance"
            ),
            "sla": "before Listing media selection or publish review",
            "next": (
                "Repair the exact-scope Product, ContentAsset, Evidence, "
                "execution timeline or Manifest authority and rerun."
            ),
            "next_workspace": (
                "/authority-intake"
                if "entity_scope" in code
                else "/media-factory"
            ),
        }

    @staticmethod
    def _dedupe_blockers(
        blockers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for blocker in blockers:
            code = str(blocker.get("code") or "")
            owner = str(blocker.get("owner") or "")
            if code:
                result[(code, owner)] = blocker
        return [result[key] for key in sorted(result)]

    @staticmethod
    def _encode_cursor(value: tuple[str, str]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).decode()

    @staticmethod
    def _decode_cursor(value: str) -> tuple[str, str]:
        try:
            decoded = json.loads(
                base64.urlsafe_b64decode(value.encode())
            )
            if (
                not isinstance(decoded, list)
                or len(decoded) != 2
                or not all(
                    isinstance(item, str) for item in decoded
                )
            ):
                raise ValueError
            return decoded[0], decoded[1]
        except (
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError("Media factory cursor is invalid") from exc

    @classmethod
    def _valid_snapshot(cls, value: dict[str, Any]) -> bool:
        claimed = str(value.get("snapshot_sha256") or "")
        if len(claimed) != 64:
            return False
        return cls._hash(
            {
                key: child
                for key, child in value.items()
                if key != "snapshot_sha256"
            }
        ) == claimed

    @staticmethod
    def _time(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None
                else value.astimezone(UTC)
            )
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
