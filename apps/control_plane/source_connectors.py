from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .connectors import ConnectorRegistry
from .source_connector_adapters import (
    Cli1688CatalogConnector,
    Cli1688MessageConnector,
    NodeJsonCommandRunner,
    OpenCli1688Connector,
    parse_source_searches,
    parse_source_targets,
)


@dataclass(frozen=True, slots=True)
class SourceConnectorCapability:
    name: str
    platform: str
    ingestion: str
    authentication: str
    capabilities: tuple[str, ...]
    notes: str
    maturity: str


SOURCE_CONNECTORS = (
    SourceConnectorCapability(
        "opencli-1688",
        "1688",
        "opencli_adapter",
        "dedicated_browser_profile",
        ("item", "store", "assets"),
        "商品、店铺和资产只读采集；登录、验证码或 Schema 漂移时停机。",
        "controlled",
    ),
    SourceConnectorCapability(
        "1688-cli-catalog",
        "1688",
        "1688_cli",
        "dedicated_browser_profile",
        ("search", "offer_details"),
        "关键词发现与已批准 Offer 详情只读采集；默认排除广告，最多每候选 5 条。",
        "controlled",
    ),
    SourceConnectorCapability(
        "1688-cli-messages",
        "1688",
        "1688_cli",
        "dedicated_browser_profile",
        ("messages_read",),
        "只读检查供应商站内信；不包含发送、购物车、结算或支付命令。",
        "controlled",
    ),
    SourceConnectorCapability(
        "ozon-official",
        "ozon",
        "official_api_or_export",
        "seller_api",
        ("market_signal", "account_export"),
        "Ozon 市场和账户数据只允许官方 API 或受控导出，不以网页抓取替代。",
        "managed",
    ),
    SourceConnectorCapability(
        "pinduoduo-research",
        "pinduoduo",
        "controlled_browser",
        "manual_session",
        ("public_research_signal",),
        "公开页面仅作研究信号；正式接入等待开放平台账号与审核。",
        "research_only",
    ),
    SourceConnectorCapability(
        "xianyu-research",
        "xianyu",
        "controlled_browser",
        "manual_session",
        ("public_research_signal",),
        "仅限人工或受控浏览器只读发现，不建设无人值守爬虫。",
        "research_only",
    ),
)


def build_source_connector_registry() -> ConnectorRegistry:
    """Build registered runtime adapters from non-secret environment configuration."""
    targets = parse_source_targets(os.getenv("KJDS_1688_TARGETS_JSON"))
    searches = parse_source_searches(os.getenv("KJDS_1688_SEARCHES_JSON"))
    opencli_runner = NodeJsonCommandRunner(os.getenv("KJDS_OPENCLI_ENTRYPOINT", ""))
    cli_runner = NodeJsonCommandRunner(os.getenv("KJDS_1688_CLI_ENTRYPOINT", ""))
    asset_download_root = os.getenv("KJDS_1688_ASSET_DOWNLOAD_ROOT") or str(
        Path(__file__).resolve().parents[2] / ".runtime" / "source-assets"
    )
    registry = ConnectorRegistry()
    registry.register(
        OpenCli1688Connector(
            runner=opencli_runner,
            targets=targets,
            asset_download_root=asset_download_root,
            installed=opencli_runner.installed,
        )
    )
    registry.register(
        Cli1688CatalogConnector(
            runner=cli_runner,
            targets=targets,
            searches=searches,
            profile=os.getenv("KJDS_1688_PROFILE", "kjds"),
            installed=cli_runner.installed,
        )
    )
    registry.register(
        Cli1688MessageConnector(
            runner=cli_runner,
            targets=targets,
            profile=os.getenv("KJDS_1688_PROFILE", "kjds"),
            installed=cli_runner.installed,
        )
    )
    return registry


def source_connector_catalog(registry: ConnectorRegistry | None = None) -> list[dict[str, Any]]:
    registered = dict(registry.items()) if registry else {}
    health_by_name: dict[str, dict[str, Any]] = {}
    if registered:
        with ThreadPoolExecutor(max_workers=len(registered), thread_name_prefix="source-health") as executor:
            futures = {name: executor.submit(connector.healthcheck) for name, connector in registered.items()}
            for name, future in futures.items():
                try:
                    health_by_name[name] = future.result()
                except Exception:
                    health_by_name[name] = {
                        "name": name,
                        "platform": "unknown",
                        "status": "degraded",
                        "tool_installed": None,
                        "browser_bridge_connected": None,
                        "logged_in": None,
                        "target_count": 0,
                        "last_success_at": None,
                        "schema_version": None,
                        "error_code": "HEALTHCHECK_FAILED",
                        "human_action_required": False,
                        "capabilities": [],
                        "external_write_allowed": False,
                    }
    result: list[dict[str, Any]] = []
    for item in SOURCE_CONNECTORS:
        connector = registered.get(item.name)
        health = (
            health_by_name[item.name]
            if connector
            else {
                "name": item.name,
                "platform": item.platform,
                "status": "managed_elsewhere" if item.maturity == "managed" else "not_automated",
                "tool_installed": None,
                "browser_bridge_connected": None,
                "logged_in": None,
                "target_count": 0,
                "last_success_at": None,
                "schema_version": None,
                "error_code": "CONNECTOR_NOT_REGISTERED",
                "human_action_required": False,
                "capabilities": list(item.capabilities),
                "external_write_allowed": False,
            }
        )
        result.append(
            {
                **health,
                "ingestion": item.ingestion,
                "authentication": item.authentication,
                "maturity": item.maturity,
                "notes": item.notes,
            }
        )
    return result
