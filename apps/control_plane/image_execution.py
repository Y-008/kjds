from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .content_growth import ContentGrowthService
from .domain import ContentAsset, ContentStatus, ContentType
from .evidence import EvidenceGrade, EvidenceService
from .providers import ComfyUIProvider
from .repository import Repository

TEMPLATE_ID = "ozon-retouch-v1"


class ComfyImageExecutionService:
    def __init__(
        self,
        *,
        repository: Repository,
        content: ContentGrowthService,
        evidence: EvidenceService,
        provider: ComfyUIProvider,
    ) -> None:
        self.repo = repository
        self.content = content
        self.evidence = evidence
        self.provider = provider

    def queue(self, asset_id: str, *, requested_by: str) -> ContentAsset:
        asset = self.repo.get_content_asset(asset_id)
        if asset.content_type != ContentType.IMAGE:
            raise ValueError("Only image content assets can use ComfyUI")
        if asset.status == ContentStatus.QUEUED:
            return asset
        if asset.status not in {ContentStatus.BRIEF, ContentStatus.QA_FAILED, ContentStatus.EXECUTION_FAILED}:
            raise ValueError("Only a brief or failed image asset can be queued")
        if asset.brief.get("generation_mode") != "retouch":
            raise ValueError(f"{TEMPLATE_ID} only executes retouch briefs")
        source_ids = asset.brief.get("source_asset_evidence_ids")
        if not isinstance(source_ids, list) or len(source_ids) != 1:
            raise ValueError(f"{TEMPLATE_ID} requires exactly one approved source image")
        source_id = source_ids[0]
        self.evidence.require_valid([source_id, *asset.brief["rights_evidence_ids"]])
        source_content, source = self.evidence.content(source_id)
        extension = self._extension(source.content_type)
        uploaded = self.provider.upload_image(
            content=source_content,
            filename=f"{asset.id}{extension}",
            content_type=source.content_type,
            subfolder=f"kjds/{asset.id}",
        )
        input_name = self._uploaded_name(uploaded)
        client_id = f"kjds-{asset.id}"
        queued = self.provider.queue_workflow(
            workflow=self._workflow(input_name=input_name, asset_id=asset.id),
            client_id=client_id,
        )
        prompt_id = str(queued.get("prompt_id", "")).strip()
        if not prompt_id:
            raise ValueError("ComfyUI did not return a prompt_id")
        asset.status = ContentStatus.QUEUED
        asset.artifact_ref = None
        asset.qa_results = []
        asset.generation = {
            "executor": "comfyui",
            "template_id": TEMPLATE_ID,
            "prompt_id": prompt_id,
            "client_id": client_id,
            "source_asset_evidence_ids": source_ids,
            "requested_by": requested_by,
            "queued_at": datetime.now(UTC).isoformat(),
        }
        with self.repo.transaction():
            self.repo.save_content_asset(asset)
            self.repo.append_event(
                "content.generation_queued",
                asset.id,
                {"executor": "comfyui", "template_id": TEMPLATE_ID, "prompt_id": prompt_id},
                actor_id=requested_by,
            )
        return asset

    def sync(self, asset_id: str, *, requested_by: str) -> ContentAsset:
        asset = self.repo.get_content_asset(asset_id)
        if asset.status != ContentStatus.QUEUED:
            return asset
        prompt_id = str(asset.generation.get("prompt_id", "")).strip()
        if not prompt_id:
            raise ValueError("Queued image asset is missing its ComfyUI prompt_id")
        history = self.provider.history(prompt_id)
        result = history.get(prompt_id)
        if not isinstance(result, dict):
            return asset
        output = self._first_image(result.get("outputs"))
        if output is None:
            status = result.get("status", {})
            status_text = str(status.get("status_str", "")).strip().lower() if isinstance(status, dict) else ""
            failure_code = (
                "execution_error"
                if status_text in {"error", "failed"}
                else "completed_without_image"
            )
            if isinstance(status, dict) and (
                status.get("completed") is True or status_text in {"error", "failed"}
            ):
                asset.status = ContentStatus.EXECUTION_FAILED
                asset.generation = {
                    **asset.generation,
                    "failed_at": datetime.now(UTC).isoformat(),
                    "failure_code": failure_code,
                }
                with self.repo.transaction():
                    self.repo.save_content_asset(asset)
                    self.repo.append_event(
                        "content.generation_failed",
                        asset.id,
                        {"prompt_id": prompt_id, "failure_code": failure_code},
                        actor_id=requested_by,
                    )
            return asset

        image_bytes, content_type = self.provider.download_image(
            filename=output["filename"],
            subfolder=output.get("subfolder", ""),
            image_type=output.get("type", "output"),
        )
        generated_at = datetime.now(UTC).isoformat()
        record = self.evidence.capture(
            content=image_bytes,
            filename=output["filename"],
            content_type=content_type,
            source="comfyui",
            source_ref=f"comfyui://prompt/{prompt_id}/{output['filename']}",
            grade=EvidenceGrade.B,
            effective_at=generated_at,
            effective_until=None,
            created_by=requested_by,
            metadata={
                "retention_class": "operational",
                "content_asset_id": asset.id,
                "generation_mode": asset.brief["generation_mode"],
                "template_id": TEMPLATE_ID,
                "prompt_id": prompt_id,
                "source_asset_evidence_ids": asset.brief["source_asset_evidence_ids"],
                "process": f"comfyui:{TEMPLATE_ID}",
                "generated_at": generated_at,
            },
        )
        self.evidence.link(
            evidence_id=record.id,
            target_type="content_asset",
            target_id=asset.id,
            relationship="generated_artifact",
            created_by=requested_by,
        )
        generated = self.content.attach_generated_asset(asset.id, artifact_ref=record.id)
        generated.generation = {
            **asset.generation,
            "completed_at": generated_at,
            "output_evidence_id": record.id,
        }
        with self.repo.transaction():
            self.repo.save_content_asset(generated)
            self.repo.append_event(
                "content.generation_completed",
                asset.id,
                {"prompt_id": prompt_id, "output_evidence_id": record.id},
                actor_id=requested_by,
                source_evidence_id=record.id,
            )
        return generated

    @staticmethod
    def _workflow(*, input_name: str, asset_id: str) -> dict[str, Any]:
        return {
            "1": {"class_type": "LoadImage", "inputs": {"image": input_name}},
            "2": {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": {
                    "image": ["1", 0],
                    "upscale_method": "lanczos",
                    "megapixels": 4.0,
                    "resolution_steps": 1,
                },
            },
            "3": {
                "class_type": "SaveImage",
                "inputs": {"images": ["2", 0], "filename_prefix": f"kjds/{asset_id}/{asset_id}"},
            },
        }

    @staticmethod
    def _extension(content_type: str) -> str:
        try:
            return {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
        except KeyError as exc:
            raise ValueError("Controlled ComfyUI template requires JPEG, PNG, or WebP") from exc

    @staticmethod
    def _uploaded_name(uploaded: dict) -> str:
        name = str(uploaded.get("name", "")).strip()
        subfolder = str(uploaded.get("subfolder", "")).strip().replace("\\", "/").strip("/")
        if not name or Path(name).name != name:
            raise ValueError("ComfyUI returned an invalid uploaded filename")
        return f"{subfolder}/{name}" if subfolder else name

    @staticmethod
    def _first_image(outputs: Any) -> dict[str, str] | None:
        if not isinstance(outputs, dict):
            return None
        for node in outputs.values():
            images = node.get("images") if isinstance(node, dict) else None
            if isinstance(images, list):
                for image in images:
                    if isinstance(image, dict) and isinstance(image.get("filename"), str):
                        return image
        return None
