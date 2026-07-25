from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse, urlunparse

from .connectors import ConnectorRecord

SOURCE_LISTING_CONTRACT = "source-listing-snapshot-v1"
ASSET_MANIFEST_CONTRACT = "asset-manifest-v1"
SUPPLIER_MESSAGE_CONTRACT = "supplier-message-snapshot-v1"
CONNECTOR_SCHEMA_VERSION = "kjds-source-connector-v1"
CANDIDATE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
MESSAGE_REDACTIONS = (
    (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[邮箱已脱敏]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号已脱敏]"),
    (re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)"), "[电话已脱敏]"),
    (re.compile(r"(?i)(?:微信|wechat|wx)\s*[:：]?\s*[A-Za-z0-9_-]{5,}"), "[微信号已脱敏]"),
    (re.compile(r"https?://[^\s]+"), "[链接已脱敏]"),
)


class ConnectorAdapterError(RuntimeError):
    def __init__(self, code: str, message: str, *, human_action_required: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.human_action_required = human_action_required


class JsonCommandRunner(Protocol):
    def run_json(self, arguments: list[str], *, timeout_seconds: int = 60) -> Any: ...


class NodeJsonCommandRunner:
    """Run one fixed Node entrypoint without shell expansion or sensitive output."""

    MAX_OUTPUT_BYTES = 2 * 1024 * 1024

    def __init__(self, entrypoint: str | Path, *, node_binary: str | None = None) -> None:
        self.entrypoint = Path(entrypoint).expanduser().resolve()
        self.node_binary = node_binary or shutil.which("node") or ""

    @property
    def installed(self) -> bool:
        return bool(self.node_binary) and self.entrypoint.is_file()

    def run_json(self, arguments: list[str], *, timeout_seconds: int = 60) -> Any:
        if not self.installed:
            raise ConnectorAdapterError("TOOL_NOT_INSTALLED", "Connector tool is not installed")
        if not 1 <= timeout_seconds <= 180:
            raise ValueError("Connector command timeout must be between 1 and 180 seconds")
        if any(not isinstance(item, str) or not item or "\x00" in item for item in arguments):
            raise ValueError("Connector command arguments must be non-empty strings")
        try:
            # File-backed output prevents a timed-out Node parent from leaving
            # Python blocked on stdout pipes that a browser-bridge child process
            # may still hold open.
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                completed = subprocess.run(
                    [self.node_binary, str(self.entrypoint), *arguments],
                    check=False,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=timeout_seconds,
                    env=os.environ.copy(),
                    shell=False,
                )
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read(self.MAX_OUTPUT_BYTES)
                stderr = stderr_file.read(self.MAX_OUTPUT_BYTES)
        except subprocess.TimeoutExpired as exc:
            raise ConnectorAdapterError(
                "CONNECTOR_TIMEOUT",
                "Connector command timed out",
                human_action_required=False,
            ) from exc
        except OSError as exc:
            raise ConnectorAdapterError("CONNECTOR_START_FAILED", "Connector command could not start") from exc
        decoded = stdout.decode("utf-8", errors="replace").strip()
        error_text = stderr.decode("utf-8", errors="replace")
        values = self._json_values(decoded)
        envelope = values[-1] if values else None
        if completed.returncode != 0:
            code = self._error_code(envelope, error_text)
            raise ConnectorAdapterError(
                code,
                self._safe_error_message(code),
                human_action_required=code
                in {
                    "CONNECTOR_BROWSER_BRIDGE_DISCONNECTED",
                    "CAPTCHA_REQUIRED",
                    "NOT_LOGGED_IN",
                    "ACCOUNT_AMBIGUOUS",
                },
            )
        if envelope is None:
            raise ConnectorAdapterError("CONNECTOR_INVALID_JSON", "Connector returned invalid JSON")
        if isinstance(envelope, dict) and envelope.get("ok") is False:
            code = self._error_code(envelope, error_text)
            raise ConnectorAdapterError(
                code,
                self._safe_error_message(code),
                human_action_required=code
                in {
                    "CONNECTOR_BROWSER_BRIDGE_DISCONNECTED",
                    "CAPTCHA_REQUIRED",
                    "NOT_LOGGED_IN",
                    "ACCOUNT_AMBIGUOUS",
                },
            )
        if isinstance(envelope, dict) and "data" in envelope and envelope.get("ok") is True:
            return envelope["data"]
        return envelope

    @staticmethod
    def _json_values(value: str) -> list[Any]:
        if not value:
            return []
        decoder = json.JSONDecoder()
        position = 0
        result: list[Any] = []
        while position < len(value):
            while position < len(value) and value[position].isspace():
                position += 1
            if position >= len(value):
                break
            try:
                item, position = decoder.raw_decode(value, position)
            except json.JSONDecodeError:
                return []
            result.append(item)
        return result

    @staticmethod
    def _error_code(envelope: Any, stderr: str) -> str:
        raw_code = ""
        if isinstance(envelope, dict):
            raw_error = envelope.get("error")
            if isinstance(raw_error, dict):
                raw_code = str(raw_error.get("code", ""))
            raw_code = raw_code or str(envelope.get("code", ""))
        combined = f"{raw_code} {stderr}".upper()
        if "BROWSER_CONNECT" in combined or "BRIDGE" in combined:
            return "CONNECTOR_BROWSER_BRIDGE_DISCONNECTED"
        if "CAPTCHA" in combined or "SLIDER" in combined or "VERIFY" in combined:
            return "CAPTCHA_REQUIRED"
        if "NOT_LOGGED_IN" in combined or "LOGIN_REQUIRED" in combined:
            return "NOT_LOGGED_IN"
        if "CONVERSATION_NOT_SELECTED" in combined or "AMBIGUOUS" in combined:
            return "ACCOUNT_AMBIGUOUS"
        if "SCHEMA" in combined or "PARSE" in combined:
            return "CONNECTOR_SCHEMA_DRIFT"
        return raw_code.strip().upper() or "CONNECTOR_COMMAND_FAILED"

    @staticmethod
    def _safe_error_message(code: str) -> str:
        return {
            "CONNECTOR_BROWSER_BRIDGE_DISCONNECTED": "Connector-specific browser bridge is disconnected",
            "CAPTCHA_REQUIRED": "Human CAPTCHA or slider action is required",
            "NOT_LOGGED_IN": "Dedicated 1688 profile is not logged in",
            "ACCOUNT_AMBIGUOUS": "The target account or conversation is ambiguous",
            "CONNECTOR_SCHEMA_DRIFT": "Connector response schema changed",
        }.get(code, "Connector command failed")


@dataclass(frozen=True, slots=True)
class SourceTarget:
    candidate_ref: str
    offer_id: str
    seller_id: str | None = None

    def __post_init__(self) -> None:
        if not CANDIDATE_REF_PATTERN.fullmatch(self.candidate_ref):
            raise ValueError("Source target requires a bounded candidate_ref")
        if not self.offer_id.isdigit() or len(self.offer_id) > 32:
            raise ValueError("1688 offer_id must contain digits only")
        if self.seller_id is not None and (not self.seller_id.strip() or len(self.seller_id) > 200):
            raise ValueError("1688 seller_id must be non-empty and at most 200 characters")


@dataclass(frozen=True, slots=True)
class SourceSearch:
    candidate_ref: str
    keyword: str
    max_results: int = 5
    sort: str = "relevance"

    def __post_init__(self) -> None:
        if not CANDIDATE_REF_PATTERN.fullmatch(self.candidate_ref):
            raise ValueError("Source search requires a bounded candidate_ref")
        if (
            not self.keyword.strip()
            or len(self.keyword) > 120
            or any(ord(character) < 32 for character in self.keyword)
        ):
            raise ValueError("Source search keyword must be printable and at most 120 characters")
        if (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or self.max_results < 1
            or self.max_results > 5
        ):
            raise ValueError("Source search may return between 1 and 5 results")
        if self.sort not in {"relevance", "best-selling", "price-asc", "price-desc"}:
            raise ValueError("Source search sort is unsupported")


def parse_source_targets(value: str | None) -> tuple[SourceTarget, ...]:
    if not value or not value.strip():
        return ()
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("KJDS_1688_TARGETS_JSON must be valid JSON") from exc
    if not isinstance(raw, list):
        raise ValueError("KJDS_1688_TARGETS_JSON must be a JSON array")
    targets = tuple(
        SourceTarget(
            candidate_ref=str(item.get("candidate_ref", "")).strip(),
            offer_id=str(item.get("offer_id", "")).strip(),
            seller_id=(
                str(item["seller_id"]).strip() if isinstance(item, dict) and item.get("seller_id") is not None else None
            ),
        )
        for item in raw
        if isinstance(item, dict)
    )
    if len(targets) != len(raw):
        raise ValueError("Every 1688 target must be an object")
    candidate_ids = {item.candidate_ref for item in targets}
    if len(candidate_ids) > 20:
        raise ValueError("A connector may configure at most 20 active candidates")
    for candidate_ref in candidate_ids:
        if sum(item.candidate_ref == candidate_ref for item in targets) > 5:
            raise ValueError("A candidate may configure at most 5 active suppliers")
    if len({(item.candidate_ref, item.offer_id) for item in targets}) != len(targets):
        raise ValueError("1688 targets must be unique per candidate and offer")
    return targets


def parse_source_searches(value: str | None) -> tuple[SourceSearch, ...]:
    if not value or not value.strip():
        return ()
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("KJDS_1688_SEARCHES_JSON must be valid JSON") from exc
    if not isinstance(raw, list):
        raise ValueError("KJDS_1688_SEARCHES_JSON must be a JSON array")
    searches = tuple(
        SourceSearch(
            candidate_ref=str(item.get("candidate_ref", "")).strip(),
            keyword=str(item.get("keyword", "")).strip(),
            max_results=item.get("max_results", 5),
            sort=str(item.get("sort", "relevance")).strip(),
        )
        for item in raw
        if isinstance(item, dict)
    )
    if len(searches) != len(raw):
        raise ValueError("Every 1688 search must be an object")
    if len(searches) > 20 or len({item.candidate_ref for item in searches}) > 20:
        raise ValueError("A connector may configure at most 20 active candidate searches")
    if len({(item.candidate_ref, item.keyword) for item in searches}) != len(searches):
        raise ValueError("1688 searches must be unique per candidate and keyword")
    return searches


class _Base1688Connector:
    platform = "1688"
    schema_version = CONNECTOR_SCHEMA_VERSION

    def __init__(self, *, runner: JsonCommandRunner, targets: tuple[SourceTarget, ...]) -> None:
        self.runner = runner
        self.targets = targets
        self.last_success_at: str | None = None
        self.last_error_code: str | None = None

    def _health(
        self,
        *,
        name: str,
        capabilities: tuple[str, ...],
        whoami_arguments: list[str],
        installed: bool,
    ) -> dict[str, Any]:
        if not installed:
            return self._health_view(
                name=name,
                capabilities=capabilities,
                status="not_configured",
                installed=False,
                bridge=None,
                logged_in=None,
                error_code="TOOL_NOT_CONFIGURED",
                human_action_required=False,
            )
        try:
            # The connector catalog is rendered in the dashboard boot path, whose
            # HTTP client has a 15-second deadline. Fail closed quickly enough for
            # both 1688 probes to report a truthful state instead of making the
            # entire catalog look unavailable.
            identity = self.runner.run_json(whoami_arguments, timeout_seconds=5)
            logged_in = bool(
                identity.get("logged_in", identity.get("loggedIn")) if isinstance(identity, dict) else False
            )
            status = (
                "ready" if logged_in and self._is_configured() else "needs_human_login" if not logged_in else "idle"
            )
            error_code = None if logged_in else "NOT_LOGGED_IN"
            return self._health_view(
                name=name,
                capabilities=capabilities,
                status=status,
                installed=True,
                bridge=True,
                logged_in=logged_in,
                error_code=error_code,
                human_action_required=not logged_in,
            )
        except ConnectorAdapterError as exc:
            code = (
                "OPENCLI_BRIDGE_UNRESPONSIVE"
                if name == OpenCli1688Connector.name and exc.code == "CONNECTOR_TIMEOUT"
                else exc.code
            )
            human_action_required = exc.human_action_required or code == "OPENCLI_BRIDGE_UNRESPONSIVE"
            self.last_error_code = code
            return self._health_view(
                name=name,
                capabilities=capabilities,
                status="human_action_required" if human_action_required else "degraded",
                installed=True,
                bridge=False
                if code in {"CONNECTOR_BROWSER_BRIDGE_DISCONNECTED", "OPENCLI_BRIDGE_UNRESPONSIVE"}
                else None,
                logged_in=False if code == "NOT_LOGGED_IN" else None,
                error_code=code,
                human_action_required=human_action_required,
            )

    def _health_view(
        self,
        *,
        name: str,
        capabilities: tuple[str, ...],
        status: str,
        installed: bool,
        bridge: bool | None,
        logged_in: bool | None,
        error_code: str | None,
        human_action_required: bool,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "platform": self.platform,
            "status": status,
            "tool_installed": installed,
            "browser_bridge_connected": bridge,
            "logged_in": logged_in,
            "target_count": len(self.targets),
            "last_success_at": self.last_success_at,
            "schema_version": self.schema_version,
            "error_code": error_code,
            "human_action_required": human_action_required,
            "capabilities": list(capabilities),
            "external_write_allowed": False,
        }

    def _success(self) -> str:
        self.last_success_at = datetime.now(UTC).isoformat()
        self.last_error_code = None
        return self.last_success_at

    def _is_configured(self) -> bool:
        return bool(self.targets)

    def _fail(self, exc: ConnectorAdapterError) -> None:
        self.last_error_code = exc.code
        raise exc


class OpenCli1688Connector(_Base1688Connector):
    name = "opencli-1688"
    MAX_ASSETS_PER_VERSION = 200

    def __init__(
        self,
        *,
        runner: JsonCommandRunner,
        targets: tuple[SourceTarget, ...],
        asset_download_root: str | Path | None = None,
        installed: bool = True,
    ) -> None:
        super().__init__(runner=runner, targets=targets)
        self.asset_download_root = Path(asset_download_root).expanduser().resolve() if asset_download_root else None
        self.installed = installed

    def healthcheck(self) -> dict[str, Any]:
        return self._health(
            name=self.name,
            capabilities=("item", "store", "assets"),
            whoami_arguments=["1688", "whoami", "-f", "json"],
            installed=self.installed,
        )

    def pull(self, *, cursor: str | None = None) -> tuple[list[ConnectorRecord], str | None]:
        if cursor not in {None, ""}:
            raise ValueError("opencli-1688 uses a complete bounded target snapshot and does not accept a cursor")
        records: list[ConnectorRecord] = []
        try:
            for target in self.targets:
                item = self.runner.run_json(
                    ["1688", "item", target.offer_id, "-f", "json"],
                    timeout_seconds=60,
                )
                occurred_at = self._success()
                records.append(opencli_item_record(item, target=target, occurred_at=occurred_at))
                assets = self.runner.run_json(
                    ["1688", "assets", target.offer_id, "-f", "json"],
                    timeout_seconds=60,
                )
                occurred_at = self._success()
                asset_record = opencli_asset_record(
                    assets,
                    target=target,
                    occurred_at=occurred_at,
                )
                asset_record.payload.update(self._download_asset_version(target=target, record=asset_record))
                records.append(asset_record)
                if target.seller_id:
                    store = self.runner.run_json(
                        ["1688", "store", target.seller_id, "-f", "json"],
                        timeout_seconds=60,
                    )
                    records[-2].payload.update(public_store_projection(store))
        except ConnectorAdapterError as exc:
            self._fail(exc)
        return records, None

    def _download_asset_version(
        self,
        *,
        target: SourceTarget,
        record: ConnectorRecord,
    ) -> dict[str, Any]:
        if self.asset_download_root is None:
            return {
                "download_status": "download_not_configured",
                "downloaded_files": [],
            }
        counts = (
            record.payload["main_count"]
            + record.payload["sku_count"]
            + record.payload["detail_count"]
            + record.payload["video_count"]
        )
        if counts > self.MAX_ASSETS_PER_VERSION:
            raise ConnectorAdapterError(
                "ASSET_LIMIT_EXCEEDED",
                "1688 asset version exceeds the bounded download limit",
            )
        version_payload = {
            "listing_id": target.offer_id,
            "source_urls": record.payload["source_urls"],
            "counts": {
                field: record.payload[field] for field in ("main_count", "sku_count", "detail_count", "video_count")
            },
        }
        version_hash = sha256(
            json.dumps(
                version_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        version_dir = (self.asset_download_root / target.offer_id / version_hash).resolve()
        if self.asset_download_root not in version_dir.parents:
            raise ConnectorAdapterError(
                "ASSET_PATH_INVALID",
                "Asset version path escaped the configured download root",
            )
        marker = version_dir / ".complete.json"
        if marker.is_file():
            try:
                prior = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ConnectorAdapterError(
                    "ASSET_MANIFEST_INVALID",
                    "Existing asset version manifest is invalid",
                ) from exc
            files = prior.get("files")
            if not isinstance(files, list):
                raise ConnectorAdapterError(
                    "ASSET_MANIFEST_INVALID",
                    "Existing asset version manifest is invalid",
                )
            return {
                "asset_version_hash": version_hash,
                "download_status": "already_downloaded",
                "downloaded_files": files,
            }
        version_dir.mkdir(parents=True, exist_ok=True)
        self.runner.run_json(
            [
                "1688",
                "download",
                target.offer_id,
                "--output",
                str(version_dir),
                "-f",
                "json",
            ],
            timeout_seconds=180,
        )
        files = self._downloaded_file_manifest(version_dir)
        if counts and not files:
            raise ConnectorAdapterError(
                "ASSET_DOWNLOAD_EMPTY",
                "1688 asset download returned no local files",
            )
        manifest = {
            "contract_id": ASSET_MANIFEST_CONTRACT,
            "listing_id": target.offer_id,
            "asset_version_hash": version_hash,
            "source_urls": record.payload["source_urls"],
            "files": files,
            "rights_status": "requires_review",
            "completed_at": datetime.now(UTC).isoformat(),
        }
        temporary = version_dir / ".complete.json.tmp"
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(marker)
        return {
            "asset_version_hash": version_hash,
            "download_status": "downloaded",
            "downloaded_files": files,
        }

    @staticmethod
    def _downloaded_file_manifest(version_dir: Path) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for path in sorted(item for item in version_dir.rglob("*") if item.is_file()):
            if path.name.startswith(".complete.json"):
                continue
            relative = path.relative_to(version_dir).as_posix()
            digest = sha256()
            byte_size = 0
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
                    byte_size += len(chunk)
            files.append(
                {
                    "path": relative,
                    "sha256": digest.hexdigest(),
                    "byte_size": byte_size,
                    "rights_status": "requires_review",
                }
            )
        return files


class Cli1688CatalogConnector(_Base1688Connector):
    name = "1688-cli-catalog"

    def __init__(
        self,
        *,
        runner: JsonCommandRunner,
        targets: tuple[SourceTarget, ...],
        searches: tuple[SourceSearch, ...],
        profile: str = "kjds",
        installed: bool = True,
    ) -> None:
        super().__init__(runner=runner, targets=targets)
        profile = profile.strip()
        if not profile or len(profile) > 80:
            raise ValueError("1688 CLI profile must be non-empty and at most 80 characters")
        self.searches = searches
        self.profile = profile
        self.installed = installed

    def _is_configured(self) -> bool:
        return bool(self.targets or self.searches)

    def healthcheck(self) -> dict[str, Any]:
        health = self._health(
            name=self.name,
            capabilities=("search", "offer_details"),
            whoami_arguments=["whoami", "--profile", self.profile, "--json-v2"],
            installed=self.installed,
        )
        health["search_count"] = len(self.searches)
        return health

    def pull(self, *, cursor: str | None = None) -> tuple[list[ConnectorRecord], str | None]:
        if cursor not in {None, ""}:
            raise ValueError("1688-cli-catalog uses a complete bounded snapshot and does not accept a cursor")
        records: list[ConnectorRecord] = []
        try:
            for search in self.searches:
                response = self.runner.run_json(
                    [
                        "search",
                        search.keyword,
                        "--max",
                        str(search.max_results),
                        "--sort",
                        search.sort,
                        "--exclude-ads",
                        "--profile",
                        self.profile,
                        "--json-v2",
                    ],
                    timeout_seconds=90,
                )
                occurred_at = self._success()
                records.extend(cli_search_records(response, search=search, occurred_at=occurred_at))
            for target in self.targets:
                response = self.runner.run_json(
                    [
                        "offer",
                        target.offer_id,
                        "--profile",
                        self.profile,
                        "--json-v2",
                    ],
                    timeout_seconds=90,
                )
                occurred_at = self._success()
                records.append(cli_offer_record(response, target=target, occurred_at=occurred_at))
        except ConnectorAdapterError as exc:
            self._fail(exc)
        return records, None


class Cli1688MessageConnector(_Base1688Connector):
    name = "1688-cli-messages"

    def __init__(
        self,
        *,
        runner: JsonCommandRunner,
        targets: tuple[SourceTarget, ...],
        profile: str = "kjds",
        installed: bool = True,
    ) -> None:
        super().__init__(runner=runner, targets=targets)
        profile = profile.strip()
        if not profile or len(profile) > 80:
            raise ValueError("1688 CLI profile must be non-empty and at most 80 characters")
        self.profile = profile
        self.installed = installed

    def healthcheck(self) -> dict[str, Any]:
        return self._health(
            name=self.name,
            capabilities=("messages_read",),
            whoami_arguments=["whoami", "--profile", self.profile, "--json-v2"],
            installed=self.installed,
        )

    def pull(self, *, cursor: str | None = None) -> tuple[list[ConnectorRecord], str | None]:
        arguments_since = ["--since", cursor] if cursor else []
        records: list[ConnectorRecord] = []
        latest = cursor
        try:
            for target in self.targets:
                response = self.runner.run_json(
                    [
                        "seller",
                        "messages",
                        "--offer",
                        target.offer_id,
                        "--limit",
                        "200",
                        *arguments_since,
                        "--profile",
                        self.profile,
                        "--json-v2",
                    ],
                    timeout_seconds=90,
                )
                occurred_at = self._success()
                message_records = cli_message_records(response, target=target, fallback_time=occurred_at)
                records.extend(message_records)
                for record in message_records:
                    if latest is None or record.occurred_at > latest:
                        latest = record.occurred_at
        except ConnectorAdapterError as exc:
            self._fail(exc)
        return records, latest


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", f"{label} response must be an object")
    return value


def require_single_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, list):
        if len(value) != 1:
            raise ConnectorAdapterError(
                "CONNECTOR_SCHEMA_DRIFT",
                f"{label} response must contain exactly one item",
            )
        value = value[0]
    return require_object(value, label)


def public_store_projection(value: Any) -> dict[str, Any]:
    payload = require_single_object(value, "1688 store")
    fields = {
        "store_name": "supplier_company_name",
        "company_name": "supplier_legal_entity",
        "business_model_text": "supplier_business_model_text",
        "years_on_platform_text": "supplier_years_on_platform_text",
        "location": "supplier_location",
        "staff_size_text": "supplier_staff_size_text",
        "response_rate_text": "supplier_response_rate_text",
        "return_rate_text": "supplier_return_rate_text",
    }
    return {
        target: _optional_text(payload.get(source), source)
        for source, target in fields.items()
        if payload.get(source) is not None
    }


def public_asset_urls(value: Any) -> list[str]:
    payload = require_object(value, "1688 assets")
    result: list[str] = []
    for field in (
        "main_images",
        "sku_images",
        "detail_images",
        "videos",
        "other_images",
    ):
        values = payload.get(field, [])
        if not isinstance(values, list):
            raise ConnectorAdapterError(
                "CONNECTOR_SCHEMA_DRIFT",
                f"1688 asset URL field is invalid: {field}",
            )
        for raw in values:
            parsed = urlparse(str(raw))
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ConnectorAdapterError(
                    "CONNECTOR_SCHEMA_DRIFT",
                    f"1688 asset URL is invalid: {field}",
                )
            normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
            if normalized not in result:
                result.append(normalized)
    if len(result) > OpenCli1688Connector.MAX_ASSETS_PER_VERSION:
        raise ConnectorAdapterError(
            "ASSET_LIMIT_EXCEEDED",
            "1688 asset version exceeds the bounded URL limit",
        )
    return result


def _required_text(value: Any, field: str, maximum: int = 1000) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", f"Connector field is invalid: {field}")
    if isinstance(value, float) and not isfinite(value):
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", f"Connector field is invalid: {field}")
    normalized = str(value).strip()
    if not normalized or len(normalized) > maximum:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", f"Connector field is invalid: {field}")
    return normalized


def _optional_text(value: Any, field: str, maximum: int = 1000) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", f"Connector field is invalid: {field}")
    if isinstance(value, float) and not isfinite(value):
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", f"Connector field is invalid: {field}")
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", f"Connector field is invalid: {field}")
    return normalized


def _bounded_text_list(value: Any, field: str, *, maximum_items: int = 50) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", f"Connector field is invalid: {field}")
    result: list[str] = []
    for item in value:
        normalized = _optional_text(item, field)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _visible_attributes(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 100:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: visible_attributes")
    result: list[dict[str, str]] = []
    for raw in value:
        item = require_object(raw, "1688 visible attribute")
        key = _required_text(item.get("key"), "visible_attributes.key", 120)
        attribute_value = _required_text(item.get("value"), "visible_attributes.value", 500)
        result.append({"key": key, "value": attribute_value})
    return result


def _price_tiers(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 50:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: price_tiers")
    result: list[dict[str, Any]] = []
    for raw in value:
        item = require_object(raw, "1688 price tier")
        quantity_min = item.get("quantity_min")
        price = item.get("price")
        if quantity_min is not None and (
            isinstance(quantity_min, bool)
            or not isinstance(quantity_min, (int, float))
            or not isfinite(quantity_min)
            or quantity_min < 0
        ):
            raise ConnectorAdapterError(
                "CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: price_tiers.quantity_min"
            )
        if price is not None and (
            isinstance(price, bool) or not isinstance(price, (int, float)) or not isfinite(price) or price < 0
        ):
            raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: price_tiers.price")
        result.append(
            {
                "quantity_text": _optional_text(item.get("quantity_text"), "price_tiers.quantity_text", 120),
                "quantity_min": quantity_min,
                "price_text": _required_text(item.get("price_text"), "price_tiers.price_text", 120),
                "price": price,
                "currency": _optional_text(item.get("currency"), "price_tiers.currency", 12),
            }
        )
    return result


def _material_text(attributes: list[dict[str, str]]) -> str | None:
    material_keys = {"材质", "产品材质", "主要材质", "面料名称", "主面料成分"}
    values = [f"{item['key']}：{item['value']}" for item in attributes if item["key"] in material_keys]
    return "；".join(values) or None


LISTING_VERIFICATION_FIELDS = (
    "sku_combinations_text",
    "material_text",
    "net_weight_text",
    "gross_weight_text",
    "package_dimensions_text",
    "tier_pricing_text",
    "sample_price_text",
    "domestic_freight_text",
    "delivery_time_text",
    "current_stock_text",
    "compression_method_text",
    "uncompressed_dimensions_text",
    "compressed_dimensions_text",
    "recovery_result_text",
    "repeat_compression_text",
    "defect_handling_text",
    "return_terms_text",
    "quality_inspection_text",
    "packaging_oem_text",
    "asset_use_authorization_text",
)


def _listing_verification_fields(**observed: str | None) -> dict[str, Any]:
    result = {field: observed.get(field) for field in LISTING_VERIFICATION_FIELDS}
    if any(value is not None and len(value) > 1000 for value in result.values()):
        raise ConnectorAdapterError(
            "CONNECTOR_SCHEMA_DRIFT",
            "A listing verification field exceeds the bounded projection limit",
        )
    unknown_fields = [field for field, value in result.items() if value is None]
    return {
        **result,
        "unknown_fields": unknown_fields,
        "unknown_fields_text": ",".join(unknown_fields),
    }


def _bounded_join(values: list[str], *, maximum: int = 1000) -> str | None:
    result = ""
    for value in values:
        candidate = f"{result}；{value}" if result else value
        if len(candidate) > maximum:
            break
        result = candidate
    return result or None


def redact_supplier_message(value: str) -> tuple[str, bool]:
    redacted = value
    for pattern, replacement in MESSAGE_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted, redacted != value


def opencli_item_record(value: Any, *, target: SourceTarget, occurred_at: str) -> ConnectorRecord:
    payload = require_single_object(value, "1688 item")
    offer_id = _required_text(payload.get("offer_id"), "offer_id", 32)
    if offer_id != target.offer_id:
        raise ConnectorAdapterError("CONNECTOR_TARGET_MISMATCH", "1688 item response target does not match")
    title = _required_text(payload.get("title"), "title")
    attributes = _visible_attributes(payload.get("visible_attributes"))
    price_tiers = _price_tiers(payload.get("price_tiers"))
    service_badges = _bounded_text_list(payload.get("service_badges"), "service_badges")
    stock_quantity = payload.get("stock_quantity")
    if stock_quantity is not None and (
        isinstance(stock_quantity, bool) or not isinstance(stock_quantity, int) or stock_quantity < 0
    ):
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: stock_quantity")
    moq_value = payload.get("moq_value")
    if moq_value is not None and (
        isinstance(moq_value, bool)
        or not isinstance(moq_value, (int, float))
        or not isfinite(moq_value)
        or moq_value < 0
    ):
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: moq_value")
    material_text = _material_text(attributes)
    delivery_time_text = _optional_text(payload.get("delivery_days_text"), "delivery_days_text")
    customization_text = _optional_text(payload.get("customization_text"), "customization_text")
    private_label_text = _optional_text(payload.get("private_label_text"), "private_label_text")
    packaging_oem_text = "；".join(item for item in (customization_text, private_label_text) if item) or None
    verification_fields = _listing_verification_fields(
        material_text=material_text,
        tier_pricing_text=(json.dumps(price_tiers, ensure_ascii=False, separators=(",", ":")) if price_tiers else None),
        delivery_time_text=delivery_time_text,
        current_stock_text=str(stock_quantity) if stock_quantity is not None else None,
        packaging_oem_text=packaging_oem_text,
    )
    return ConnectorRecord(
        source="opencli-1688",
        record_type=SOURCE_LISTING_CONTRACT,
        external_id=offer_id,
        occurred_at=occurred_at,
        source_ref=f"https://detail.1688.com/offer/{offer_id}.html",
        payload={
            "contract_id": SOURCE_LISTING_CONTRACT,
            "platform": "1688",
            "candidate_ref": target.candidate_ref,
            "listing_id": offer_id,
            "seller_id": target.seller_id,
            "member_id": _optional_text(payload.get("member_id"), "member_id", 200),
            "shop_id": _optional_text(payload.get("shop_id"), "shop_id", 200),
            "title": title,
            "price_text": _optional_text(payload.get("price_text"), "price_text"),
            "price_tiers": price_tiers,
            "currency": _optional_text(payload.get("currency"), "currency", 12),
            "moq_text": _optional_text(payload.get("moq_text"), "moq_text"),
            "moq_value": moq_value,
            "seller_name": _optional_text(payload.get("seller_name"), "seller_name"),
            "origin_place": _optional_text(payload.get("origin_place"), "origin_place"),
            "visible_attributes": attributes,
            "visible_attributes_text": "；".join(f"{item['key']}：{item['value']}" for item in attributes) or None,
            "sales_text": _optional_text(payload.get("sales_text"), "sales_text"),
            "service_badges": service_badges,
            "service_badges_text": "；".join(service_badges) or None,
            **verification_fields,
            "license_status": "requires_review",
            "fact_status": "research_signal",
        },
    )


def cli_search_records(value: Any, *, search: SourceSearch, occurred_at: str) -> list[ConnectorRecord]:
    payload = require_object(value, "1688 search")
    keyword = _required_text(payload.get("keyword"), "keyword", 120)
    if keyword != search.keyword:
        raise ConnectorAdapterError("CONNECTOR_TARGET_MISMATCH", "1688 search response keyword does not match")
    offers = payload.get("offers")
    if not isinstance(offers, list) or len(offers) > search.max_results:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "1688 search response exceeds the bounded result limit")
    records: list[ConnectorRecord] = []
    for raw in offers:
        offer = require_object(raw, "1688 search offer")
        if offer.get("isP4P") is True:
            continue
        offer_id = _required_text(offer.get("offerId"), "offerId", 32)
        if not offer_id.isdigit():
            raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "1688 search offerId must contain digits only")
        title = _required_text(offer.get("title"), "title")
        price = require_object(offer.get("price", {}), "1688 search price")
        supplier = require_object(offer.get("supplier", {}), "1688 search supplier")
        location = require_object(offer.get("location", {}), "1688 search location")
        supplier_name = _optional_text(supplier.get("name"), "supplier.name")
        supplier_years = supplier.get("years")
        if supplier_years is not None and (
            isinstance(supplier_years, bool) or not isinstance(supplier_years, int) or supplier_years < 0
        ):
            raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: supplier.years")
        origin_place = (
            " ".join(
                item
                for item in (
                    _optional_text(location.get("province"), "location.province"),
                    _optional_text(location.get("city"), "location.city"),
                )
                if item
            )
            or None
        )
        records.append(
            ConnectorRecord(
                source="1688-cli-catalog",
                record_type=SOURCE_LISTING_CONTRACT,
                external_id=offer_id,
                occurred_at=occurred_at,
                source_ref=f"https://detail.1688.com/offer/{offer_id}.html",
                payload={
                    "contract_id": SOURCE_LISTING_CONTRACT,
                    "platform": "1688",
                    "candidate_ref": search.candidate_ref,
                    "listing_id": offer_id,
                    "seller_id": supplier_name or offer_id,
                    "title": title,
                    "price_text": _optional_text(price.get("text"), "price.text"),
                    "seller_name": supplier_name,
                    "supplier_years_on_platform_text": (f"{supplier_years}年" if supplier_years is not None else None),
                    "origin_place": origin_place,
                    "search_keyword": keyword,
                    "search_sort": search.sort,
                    "search_ads_excluded": True,
                    **_listing_verification_fields(),
                    "license_status": "requires_review",
                    "fact_status": "research_signal",
                },
            )
        )
    return records


def _cli_offer_attributes(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 100:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: attributes")
    result: list[dict[str, str]] = []
    for raw in value:
        item = require_object(raw, "1688 offer attribute")
        result.append(
            {
                "key": _required_text(item.get("name"), "attributes.name", 120),
                "value": _required_text(item.get("value"), "attributes.value", 500),
            }
        )
    return result


def _cli_offer_skus(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 200:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: skus")
    result: list[dict[str, Any]] = []
    for raw in value:
        item = require_object(raw, "1688 offer SKU")
        stock = item.get("stock")
        price = item.get("price")
        if stock is not None and (isinstance(stock, bool) or not isinstance(stock, int) or stock < 0):
            raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: skus.stock")
        if price is not None and (
            isinstance(price, bool) or not isinstance(price, (int, float)) or not isfinite(price) or price < 0
        ):
            raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: skus.price")
        result.append(
            {
                "sku_id": _optional_text(item.get("skuId"), "skus.skuId", 200),
                "specs": _required_text(item.get("specs"), "skus.specs", 500),
                "price": price,
                "stock": stock,
            }
        )
    return result


def _cli_offer_packages(value: Any) -> list[dict[str, str | None]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 200:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: packageInfo")
    result: list[dict[str, str | None]] = []
    for raw in value:
        item = require_object(raw, "1688 package info")
        result.append(
            {
                "sku_id": _optional_text(item.get("skuId"), "packageInfo.skuId", 200),
                "spec": _optional_text(item.get("spec"), "packageInfo.spec", 500),
                "length": _optional_text(item.get("length"), "packageInfo.length", 80),
                "width": _optional_text(item.get("width"), "packageInfo.width", 80),
                "height": _optional_text(item.get("height"), "packageInfo.height", 80),
                "weight": _optional_text(item.get("weight"), "packageInfo.weight", 80),
                "volume": _optional_text(item.get("volume"), "packageInfo.volume", 80),
            }
        )
    return result


def cli_offer_record(value: Any, *, target: SourceTarget, occurred_at: str) -> ConnectorRecord:
    payload = require_object(value, "1688 offer")
    offer_id = _required_text(payload.get("offerId"), "offerId", 32)
    if offer_id != target.offer_id:
        raise ConnectorAdapterError("CONNECTOR_TARGET_MISMATCH", "1688 offer response target does not match")
    title = _required_text(payload.get("title"), "title")
    supplier = require_object(payload.get("supplier", {}), "1688 offer supplier")
    freight = require_object(payload.get("freight", {}), "1688 offer freight")
    attributes = _cli_offer_attributes(payload.get("attributes"))
    skus = _cli_offer_skus(payload.get("skus"))
    packages = _cli_offer_packages(payload.get("packageInfo"))
    raw_tiers = payload.get("priceTiers")
    if raw_tiers is None:
        raw_tiers = []
    if not isinstance(raw_tiers, list) or len(raw_tiers) > 50:
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: priceTiers")
    price_tiers: list[dict[str, Any]] = []
    for raw in raw_tiers:
        tier = require_object(raw, "1688 offer price tier")
        minimum = tier.get("minQty")
        price = tier.get("price")
        if (
            isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or minimum <= 0
            or isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not isfinite(price)
            or price <= 0
        ):
            raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: priceTiers")
        price_tiers.append(
            {
                "quantity_text": str(minimum),
                "quantity_min": minimum,
                "price_text": str(price),
                "price": price,
                "currency": "CNY",
            }
        )
    moq_value = payload.get("minOrderQty")
    if moq_value is not None and (isinstance(moq_value, bool) or not isinstance(moq_value, int) or moq_value < 0):
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "Connector field is invalid: minOrderQty")
    sku_combinations_text = _bounded_join([item["specs"] for item in skus])
    known_stocks = [item["stock"] for item in skus if item["stock"] is not None]
    current_stock_text = f"{len(known_stocks)}个SKU页面库存合计{sum(known_stocks)}" if known_stocks else None
    package_summaries = [
        f"{item['spec'] or item['sku_id'] or '规格未知'}:"
        f"{item['length'] or '?'}×{item['width'] or '?'}×{item['height'] or '?'}"
        f",重量{item['weight'] or '?'},体积{item['volume'] or '?'}"
        for item in packages
    ]
    package_dimensions_text = _bounded_join(package_summaries)
    listed_piece_weights = [str(item["weight"]) for item in packages if item["weight"]]
    freight_unit_weight = _optional_text(freight.get("unitWeight"), "freight.unitWeight", 80)
    listed_piece_weight_text = _bounded_join(
        [
            *(f"包装记录重量{item}" for item in listed_piece_weights),
            *([f"运费模板单位重量{freight_unit_weight}"] if freight_unit_weight else []),
        ]
    )
    material_text = _material_text(attributes)
    price_text = _optional_text(payload.get("priceRange"), "priceRange")
    if price_text and not price_text.startswith("¥"):
        price_text = f"¥{price_text}"
    if price_text is None and isinstance(payload.get("priceMin"), (int, float)):
        price_text = f"¥{payload['priceMin']}"
    verification_fields = _listing_verification_fields(
        sku_combinations_text=sku_combinations_text,
        material_text=material_text,
        package_dimensions_text=package_dimensions_text,
        tier_pricing_text=(json.dumps(price_tiers, ensure_ascii=False, separators=(",", ":")) if price_tiers else None),
        current_stock_text=current_stock_text,
    )
    supplier_name = _optional_text(supplier.get("name"), "supplier.name")
    return ConnectorRecord(
        source="1688-cli-catalog",
        record_type=SOURCE_LISTING_CONTRACT,
        external_id=offer_id,
        occurred_at=occurred_at,
        source_ref=f"https://detail.1688.com/offer/{offer_id}.html",
        payload={
            "contract_id": SOURCE_LISTING_CONTRACT,
            "platform": "1688",
            "candidate_ref": target.candidate_ref,
            "listing_id": offer_id,
            "seller_id": target.seller_id or _optional_text(supplier.get("memberId"), "supplier.memberId", 200),
            "title": title,
            "price_text": price_text,
            "price_tiers": price_tiers,
            "currency": "CNY",
            "moq_text": f"{moq_value}{_optional_text(payload.get('unitName'), 'unitName', 40) or ''}起批"
            if moq_value is not None
            else None,
            "moq_value": moq_value,
            "seller_name": supplier_name,
            "supplier_legal_entity": supplier_name,
            "visible_attributes": attributes,
            "visible_attributes_text": _bounded_join([f"{item['key']}：{item['value']}" for item in attributes]),
            "skus": skus,
            "package_info": packages,
            "listed_piece_weight_text": listed_piece_weight_text,
            **verification_fields,
            "license_status": "requires_review",
            "fact_status": "research_signal",
        },
    )


def opencli_asset_record(value: Any, *, target: SourceTarget, occurred_at: str) -> ConnectorRecord:
    payload = require_single_object(value, "1688 assets")
    offer_id = _required_text(payload.get("offer_id"), "offer_id", 32)
    if offer_id != target.offer_id:
        raise ConnectorAdapterError("CONNECTOR_TARGET_MISMATCH", "1688 asset response target does not match")
    counts = {}
    for field in ("main_count", "sku_count", "detail_count", "video_count"):
        raw = payload.get(field)
        if not isinstance(raw, int) or raw < 0:
            raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", f"1688 asset field is invalid: {field}")
        counts[field] = raw
    source_urls = public_asset_urls(payload)
    return ConnectorRecord(
        source="opencli-1688",
        record_type=ASSET_MANIFEST_CONTRACT,
        external_id=f"{offer_id}:assets",
        occurred_at=occurred_at,
        source_ref=f"https://detail.1688.com/offer/{offer_id}.html",
        payload={
            "contract_id": ASSET_MANIFEST_CONTRACT,
            "platform": "1688",
            "candidate_ref": target.candidate_ref,
            "listing_id": offer_id,
            "seller_id": target.seller_id,
            **counts,
            "source_urls": source_urls,
            "download_status": "listed_not_downloaded",
            "rights_status": "requires_review",
            "license_status": "requires_review",
            "fact_status": "research_signal",
        },
    )


def cli_message_records(
    value: Any,
    *,
    target: SourceTarget,
    fallback_time: str,
) -> list[ConnectorRecord]:
    payload = require_object(value, "1688 seller messages")
    conversation = _required_text(payload.get("conversation"), "conversation", 300)
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "1688 seller messages must contain a messages list")
    result: list[ConnectorRecord] = []
    for raw in messages:
        message = require_object(raw, "1688 message")
        raw_content = _required_text(message.get("content"), "content", 4000)
        content, content_redacted = redact_supplier_message(raw_content)
        occurred_at = str(message.get("time") or fallback_time)
        try:
            parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "1688 message time is invalid") from exc
        if parsed.tzinfo is None:
            raise ConnectorAdapterError("CONNECTOR_SCHEMA_DRIFT", "1688 message time must include a timezone")
        occurred_at = parsed.astimezone(UTC).isoformat()
        message_id = str(message.get("messageId") or "").strip()
        conversation_ref_hash = sha256(conversation.encode()).hexdigest()
        if not message_id:
            message_id = sha256(
                json.dumps(
                    {
                        "conversation_ref_hash": conversation_ref_hash,
                        "time": occurred_at,
                        "sender": message.get("sender"),
                        "content": content,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        result.append(
            ConnectorRecord(
                source="1688-cli",
                record_type=SUPPLIER_MESSAGE_CONTRACT,
                external_id=message_id,
                occurred_at=occurred_at,
                source_ref=f"https://detail.1688.com/offer/{target.offer_id}.html",
                payload={
                    "contract_id": SUPPLIER_MESSAGE_CONTRACT,
                    "platform": "1688",
                    "candidate_ref": target.candidate_ref,
                    "listing_id": target.offer_id,
                    "seller_id": target.seller_id,
                    "conversation_ref_hash": conversation_ref_hash,
                    "message_id": message_id,
                    "sender": message.get("sender"),
                    "is_mine": bool(message.get("isMine")),
                    "content": content,
                    "content_redacted": content_redacted,
                    "read": bool(message.get("read")),
                    "kind": message.get("kind"),
                    "license_status": "requires_review",
                    "fact_status": "research_signal",
                },
            )
        )
    return result
