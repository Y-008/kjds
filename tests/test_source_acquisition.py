from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.action_policies import (
    ActionAuthorizationService,
    ActionPolicyRegistry,
)
from apps.control_plane.connectors import ConnectorRegistry
from apps.control_plane.evidence import EvidenceService
from apps.control_plane.research_inbox import ResearchInboxService
from apps.control_plane.source_acquisition import SourceAcquisitionService
from apps.control_plane.source_connector_adapters import (
    ASSET_MANIFEST_CONTRACT,
    SOURCE_LISTING_CONTRACT,
    SUPPLIER_MESSAGE_CONTRACT,
    Cli1688CatalogConnector,
    Cli1688MessageConnector,
    ConnectorAdapterError,
    OpenCli1688Connector,
    SourceSearch,
    SourceTarget,
    cli_message_records,
    cli_offer_record,
    cli_search_records,
    opencli_asset_record,
    opencli_item_record,
    parse_source_searches,
    parse_source_targets,
)
from apps.control_plane.source_connectors import source_connector_catalog
from apps.control_plane.sql_repository import Base

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "external_contracts"
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "docs" / "project" / "registries" / "action_policy_registry.json"


def fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class FakeRepository:
    def __init__(self):
        self.events = []

    def append_event(self, event_type, aggregate_id, payload, actor_id):
        self.events.append(
            {
                "type": event_type,
                "aggregate_id": aggregate_id,
                "payload": payload,
                "actor_id": actor_id,
            }
        )


class SequenceConnector:
    name = "fixture-1688"

    def __init__(self, records):
        self.records = records

    def pull(self, *, cursor=None):
        return self.records, cursor

    def healthcheck(self):
        return {
            "name": self.name,
            "platform": "1688",
            "status": "ready",
            "external_write_allowed": False,
        }


def service_for(records):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    inbox = ResearchInboxService(evidence=evidence)
    connectors = ConnectorRegistry()
    connectors.register(SequenceConnector(records))
    repository = FakeRepository()
    service = SourceAcquisitionService(
        connectors=connectors,
        research_inbox=inbox,
        action_authorization=ActionAuthorizationService(ActionPolicyRegistry(REGISTRY_PATH)),
        repository=repository,
    )
    return service, repository


def test_1688_contract_parsers_accept_fixed_desensitized_samples():
    target = SourceTarget("candidate://compression-main", "900000000001", "fixture-seller")
    item = opencli_item_record(
        fixture("1688_opencli_item_v1.json"),
        target=target,
        occurred_at="2026-07-25T00:00:00+00:00",
    )
    assets = opencli_asset_record(
        fixture("1688_opencli_assets_v1.json"),
        target=target,
        occurred_at="2026-07-25T00:00:00+00:00",
    )
    messages = cli_message_records(
        fixture("1688_cli_messages_v1.json"),
        target=target,
        fallback_time="2026-07-25T00:00:00+00:00",
    )

    assert item.record_type == SOURCE_LISTING_CONTRACT
    assert item.payload["fact_status"] == "research_signal"
    assert item.payload["material_text"] == "材质：涤纶"
    assert item.payload["current_stock_text"] == "500"
    assert item.payload["delivery_time_text"] == "72小时内发货"
    assert item.payload["packaging_oem_text"] == "支持来样定制；支持贴牌"
    assert "gross_weight_text" in item.payload["unknown_fields"]
    assert "asset_use_authorization_text" in item.payload["unknown_fields"]
    assert assets.record_type == ASSET_MANIFEST_CONTRACT
    assert assets.payload["rights_status"] == "requires_review"
    assert assets.payload["source_urls"] == [
        "https://cdn.example.invalid/900000000001-main.jpg",
        "https://cdn.example.invalid/900000000001-video.mp4",
    ]
    assert len(messages) == 2
    assert {item.external_id for item in messages} == {"fixture-message-001"}
    assert all(item.record_type == SUPPLIER_MESSAGE_CONTRACT for item in messages)


def test_1688_cli_search_and_offer_parsers_preserve_real_sku_fields_as_research():
    search = SourceSearch("candidate://compression-main", "真空压缩收纳袋", 5)
    target = SourceTarget("candidate://compression-main", "900000000001")

    discoveries = cli_search_records(
        fixture("1688_cli_search_v1.json"),
        search=search,
        occurred_at="2026-07-25T00:00:00+00:00",
    )
    offer = cli_offer_record(
        fixture("1688_cli_offer_v1.json"),
        target=target,
        occurred_at="2026-07-25T00:00:00+00:00",
    )

    assert len(discoveries) == 2
    assert all(item.payload["search_ads_excluded"] is True for item in discoveries)
    assert offer.payload["sku_combinations_text"] == "灰色>大号；蓝色>大号"
    assert offer.payload["package_dimensions_text"].startswith("灰色>大号:40×30×5")
    assert offer.payload["current_stock_text"] == "2个SKU页面库存合计500"
    assert offer.payload["material_text"] == "材质：涤纶"
    assert offer.payload["listed_piece_weight_text"] == "包装记录重量0.8；运费模板单位重量0.8"
    assert "gross_weight_text" in offer.payload["unknown_fields"]
    assert offer.payload["fact_status"] == "research_signal"


def test_1688_contract_parser_fails_closed_on_schema_drift():
    target = SourceTarget("candidate://compression-main", "900000000001")
    with pytest.raises(ConnectorAdapterError) as caught:
        opencli_item_record(
            fixture("1688_opencli_item_schema_drift_v1.json"),
            target=target,
            occurred_at="2026-07-25T00:00:00+00:00",
        )
    assert caught.value.code == "CONNECTOR_SCHEMA_DRIFT"


def test_source_acquisition_is_idempotent_across_observation_times():
    target = SourceTarget("candidate://compression-main", "900000000001")
    first_record = opencli_item_record(
        fixture("1688_opencli_item_v1.json"),
        target=target,
        occurred_at="2026-07-25T00:00:00+00:00",
    )
    service, repository = service_for([first_record])
    first = service.pull(connector_name="fixture-1688", cursor=None, actor_id="operator-1")

    service.connectors.get("fixture-1688").records = [replace(first_record, occurred_at="2026-07-25T12:00:00+00:00")]
    second = service.pull(connector_name="fixture-1688", cursor=None, actor_id="operator-1")

    assert first["evidence_count"] == 1
    assert first["duplicate_count"] == 0
    assert second["evidence_count"] == 1
    assert second["duplicate_count"] == 1
    assert len(repository.events) == 2
    assert all(item["payload"]["action_id"] == "source_discover" for item in repository.events)
    assert second["guardrails"]["external_write_allowed"] is False
    assert second["guardrails"]["automatic_procurement"] is False


def test_source_target_limits_are_enforced_before_any_browser_call():
    too_many_suppliers = [
        {"candidate_ref": "candidate://one", "offer_id": str(900000000000 + index)} for index in range(1, 7)
    ]
    with pytest.raises(ValueError, match="at most 5"):
        parse_source_targets(json.dumps(too_many_suppliers))

    with pytest.raises(ValueError, match="between 1 and 5"):
        parse_source_searches(
            json.dumps(
                [
                    {
                        "candidate_ref": "candidate://compression-main",
                        "keyword": "真空压缩收纳袋",
                        "max_results": 6,
                    }
                ]
            )
        )


def test_connector_catalog_reports_missing_runtime_tools_truthfully():
    catalog = source_connector_catalog()
    opencli = next(item for item in catalog if item["name"] == "opencli-1688")

    assert opencli["status"] == "not_automated"
    assert opencli["error_code"] == "CONNECTOR_NOT_REGISTERED"
    assert opencli["external_write_allowed"] is False
    assert opencli["last_success_at"] is None


def test_duplicate_message_records_do_not_duplicate_evidence():
    target = SourceTarget("candidate://compression-main", "900000000001")
    records = cli_message_records(
        fixture("1688_cli_messages_v1.json"),
        target=target,
        fallback_time=datetime.now(UTC).isoformat(),
    )
    service, _ = service_for(records)

    result = service.pull(connector_name="fixture-1688", cursor=None, actor_id="operator-1")

    assert result["record_count"] == 2
    assert result["evidence_count"] == 1
    assert result["duplicate_count"] == 1


def test_supplier_message_personal_and_session_data_is_redacted_before_evidence():
    target = SourceTarget("candidate://compression-main", "900000000001")
    records = cli_message_records(
        {
            "conversation": "private-session-reference",
            "messages": [
                {
                    "sender": "seller",
                    "time": "2026-07-25T08:00:00+08:00",
                    "content": "电话 13800138000，邮箱 seller@example.com，微信:abcde123，https://example.com/a?token=x",
                    "messageId": "fixture-message-sensitive",
                }
            ],
        },
        target=target,
        fallback_time="2026-07-25T00:00:00+00:00",
    )

    payload = records[0].payload
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["content_redacted"] is True
    assert payload["conversation_ref_hash"] != "private-session-reference"
    assert "13800138000" not in serialized
    assert "seller@example.com" not in serialized
    assert "abcde123" not in serialized
    assert "token=x" not in serialized


def test_asset_version_is_downloaded_once_and_hashed():
    class DownloadRunner:
        def __init__(self):
            self.download_calls = 0

        def run_json(self, arguments, *, timeout_seconds=60):
            if arguments[1] == "item":
                return fixture("1688_opencli_item_v1.json")
            if arguments[1] == "assets":
                return fixture("1688_opencli_assets_v1.json")
            if arguments[1] == "download":
                self.download_calls += 1
                output = Path(arguments[arguments.index("--output") + 1])
                target = output / "900000000001"
                target.mkdir(parents=True)
                (target / "900000000001_main_01.jpg").write_bytes(b"fixture image")
                return [{"index": 1, "type": "image", "status": "downloaded", "size": 13}]
            raise AssertionError(arguments)

    runtime_test_root = Path(__file__).resolve().parents[1] / ".runtime" / "test-assets"
    runtime_test_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=runtime_test_root) as temporary:
        runner = DownloadRunner()
        connector = OpenCli1688Connector(
            runner=runner,
            targets=(SourceTarget("candidate://compression-main", "900000000001"),),
            asset_download_root=temporary,
        )

        first, _ = connector.pull()
        second, _ = connector.pull()
        first_assets = next(item for item in first if item.record_type == ASSET_MANIFEST_CONTRACT)
        second_assets = next(item for item in second if item.record_type == ASSET_MANIFEST_CONTRACT)

        assert runner.download_calls == 1
        assert first_assets.payload["download_status"] == "downloaded"
        assert second_assets.payload["download_status"] == "already_downloaded"
        assert first_assets.payload["downloaded_files"][0]["sha256"] == (
            "9bc365f2514351337f5a124f26bf21920fd03bb21c634fa94756d22a893a7cd5"
        )
        assert first_assets.payload["downloaded_files"][0]["rights_status"] == "requires_review"


def test_opencli_health_timeout_requires_browser_bridge_handoff():
    class TimeoutRunner:
        def run_json(self, arguments, *, timeout_seconds=60):
            raise ConnectorAdapterError("CONNECTOR_TIMEOUT", "Connector command timed out")

    connector = OpenCli1688Connector(runner=TimeoutRunner(), targets=())

    health = connector.healthcheck()

    assert health["status"] == "human_action_required"
    assert health["browser_bridge_connected"] is False
    assert health["error_code"] == "BROWSER_BRIDGE_UNRESPONSIVE"
    assert health["human_action_required"] is True


def test_connector_command_whitelists_exclude_login_send_cart_order_and_payment():
    forbidden = {"login", "send", "cart", "checkout", "order", "pay", "payment"}

    class RecordingOpenCliRunner:
        def __init__(self):
            self.commands = []

        def run_json(self, arguments, *, timeout_seconds=60):
            self.commands.append(arguments)
            if arguments[1] == "item":
                return fixture("1688_opencli_item_v1.json")
            if arguments[1] == "assets":
                return fixture("1688_opencli_assets_v1.json")
            if arguments[1] == "store":
                return [
                    {
                        "store_name": "脱敏供应商甲",
                        "company_name": "脱敏供应商甲有限公司",
                        "business_model_text": "生产加工",
                        "years_on_platform_text": "5年",
                        "location": "浙江",
                        "return_rate_text": "公开服务信号",
                    }
                ]
            raise AssertionError(arguments)

    opencli_runner = RecordingOpenCliRunner()
    records, _ = OpenCli1688Connector(
        runner=opencli_runner,
        targets=(
            SourceTarget(
                "candidate://compression-main",
                "900000000001",
                "fixture-seller",
            ),
        ),
        asset_download_root=None,
    ).pull()
    listing = next(item for item in records if item.record_type == SOURCE_LISTING_CONTRACT)
    assert listing.payload["supplier_legal_entity"] == "脱敏供应商甲有限公司"
    assert listing.payload["supplier_business_model_text"] == "生产加工"
    assert [command[1] for command in opencli_runner.commands] == [
        "item",
        "assets",
        "store",
    ]

    class RecordingMessageRunner:
        def __init__(self):
            self.commands = []

        def run_json(self, arguments, *, timeout_seconds=60):
            self.commands.append(arguments)
            return fixture("1688_cli_messages_v1.json")

    message_runner = RecordingMessageRunner()
    Cli1688MessageConnector(
        runner=message_runner,
        targets=(SourceTarget("candidate://compression-main", "900000000001"),),
        profile="kjds",
    ).pull(cursor="2026-07-25T00:00:00+00:00")
    assert message_runner.commands[0][:2] == ["seller", "messages"]

    class RecordingCatalogRunner:
        def __init__(self):
            self.commands = []

        def run_json(self, arguments, *, timeout_seconds=60):
            self.commands.append(arguments)
            if arguments[0] == "search":
                return fixture("1688_cli_search_v1.json")
            if arguments[0] == "offer":
                return fixture("1688_cli_offer_v1.json")
            raise AssertionError(arguments)

    catalog_runner = RecordingCatalogRunner()
    catalog_records, _ = Cli1688CatalogConnector(
        runner=catalog_runner,
        targets=(SourceTarget("candidate://compression-main", "900000000001"),),
        searches=(SourceSearch("candidate://compression-main", "真空压缩收纳袋", 5),),
        profile="kjds",
    ).pull()
    assert len(catalog_records) == 3
    assert catalog_runner.commands[0][0] == "search"
    assert catalog_runner.commands[1][0] == "offer"

    tokens = {
        token.casefold()
        for command in [
            *opencli_runner.commands,
            *message_runner.commands,
            *catalog_runner.commands,
        ]
        for token in command
    }
    assert not forbidden.intersection(tokens)
