from types import SimpleNamespace
from unittest import TestCase

from apps.control_plane.action_policies import ActionPolicyError
from apps.control_plane.content_growth import ContentGrowthService
from apps.control_plane.domain import ContentAsset, ContentStatus, ContentType
from apps.control_plane.image_execution import TEMPLATE_ID, ComfyImageExecutionService
from apps.control_plane.repository import InMemoryRepository


class FakeEvidence:
    def __init__(self):
        self.records = {
            "evd_source": SimpleNamespace(
                id="evd_source",
                filename="source.png",
                content_type="image/png",
                metadata={},
            ),
            "evd_rights": SimpleNamespace(
                id="evd_rights",
                filename="rights.pdf",
                content_type="application/pdf",
                metadata={},
            ),
        }
        self.captured = None

    def require_valid(self, _):
        return None

    def content(self, evidence_id):
        return b"source-image", self.records[evidence_id]

    def get(self, evidence_id):
        return self.records[evidence_id]

    def capture(self, **kwargs):
        record = SimpleNamespace(id="evd_output", content_type=kwargs["content_type"], metadata=kwargs["metadata"])
        self.records[record.id] = record
        self.captured = kwargs
        return record

    def link(self, **_):
        return None


class FakeComfyUI:
    def __init__(self):
        self.upload_calls = 0
        self.queue_calls = 0
        self.workflow = None
        self.history_payload = {}

    def upload_image(self, **_):
        self.upload_calls += 1
        return {"name": "asset.png", "subfolder": "kjds/asset", "type": "input"}

    def queue_workflow(self, *, workflow, client_id):
        self.queue_calls += 1
        self.workflow = workflow
        return {"prompt_id": "prompt-1", "number": 1, "node_errors": {}}

    def history(self, prompt_id):
        return self.history_payload

    def download_image(self, **_):
        return b"generated-image", "image/png"


class ImageExecutionTest(TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.evidence = FakeEvidence()
        self.provider = FakeComfyUI()
        self.content = ContentGrowthService(
            self.repo,
            evidence_validator=self.evidence.require_valid,
            evidence_lookup=self.evidence.get,
            image_readiness=lambda _: {},
        )
        self.asset = ContentAsset(
            "product-1",
            ContentType.IMAGE,
            "ru-RU",
            "OZON",
            {
                "goal": "Ozon main image",
                "generation_mode": "retouch",
                "preserve_product_facts": True,
                "source_asset_evidence_ids": ["evd_source"],
                "rights_evidence_ids": ["evd_rights"],
            },
            {},
        )
        self.repo.add_content_asset(self.asset)
        self.service = ComfyImageExecutionService(
            repository=self.repo,
            content=self.content,
            evidence=self.evidence,
            provider=self.provider,
        )

    def test_queue_is_idempotent_and_sync_captures_generated_evidence(self):
        queued = self.service.queue(self.asset.id, requested_by="operator-1")
        repeated = self.service.queue(self.asset.id, requested_by="operator-1")

        self.assertEqual(queued.status, ContentStatus.QUEUED)
        self.assertEqual(repeated.generation["prompt_id"], "prompt-1")
        self.assertEqual(self.provider.queue_calls, 1)
        self.assertEqual(
            {node["class_type"] for node in self.provider.workflow.values()},
            {"LoadImage", "ImageScaleToTotalPixels", "SaveImage"},
        )

        self.provider.history_payload = {
            "prompt-1": {
                "outputs": {
                    "3": {
                        "images": [
                            {"filename": "asset_00001_.png", "subfolder": "kjds/asset", "type": "output"}
                        ]
                    }
                },
                "status": {"completed": True, "status_str": "success"},
            }
        }
        generated = self.service.sync(self.asset.id, requested_by="operator-1")

        self.assertEqual(generated.status, ContentStatus.GENERATED)
        self.assertEqual(generated.artifact_ref, "evd_output")
        self.assertEqual(generated.generation["template_id"], TEMPLATE_ID)
        self.assertEqual(self.evidence.captured["metadata"]["content_asset_id"], self.asset.id)
        self.assertEqual(self.evidence.captured["metadata"]["source_asset_evidence_ids"], ["evd_source"])

    def test_completed_prompt_without_image_fails_closed(self):
        self.service.queue(self.asset.id, requested_by="operator-1")
        self.provider.history_payload = {
            "prompt-1": {"outputs": {}, "status": {"completed": True, "status_str": "error"}}
        }

        failed = self.service.sync(self.asset.id, requested_by="operator-1")

        self.assertEqual(failed.status, ContentStatus.EXECUTION_FAILED)
        self.assertEqual(failed.generation["failure_code"], "execution_error")

    def test_execution_authorization_denial_prevents_provider_call(self):
        with self.assertRaisesRegex(ActionPolicyError, "Executor identity"):
            self.service.queue(self.asset.id, requested_by="comfyui_worker")

        self.assertEqual(self.provider.upload_calls, 0)
        self.assertEqual(self.provider.queue_calls, 0)
        self.assertEqual(self.asset.status, ContentStatus.BRIEF)
        denied = [
            event
            for event in self.repo.events
            if event["type"] == "governance.action_authorization_evaluated"
            and event["payload"]["allowed"] is False
        ]
        self.assertEqual(denied[-1]["payload"]["audit_code"], "EXECUTOR_INDEPENDENCE_REQUIRED")
