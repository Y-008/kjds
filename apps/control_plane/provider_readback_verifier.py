from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from .channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
)
from .ozon_live_contracts import (
    FINANCE_TRANSACTION_PATH,
    validate_finance_transactions_payload,
)

PROVIDER_READBACK_VERIFIER_VERSION = "1.0"
PROVIDER_READBACK_CONTRACT_ID = "kjds-provider-readback-verifier-v1"
READBACK_SUMMARY_CONTRACT_ID = "kjds-provider-readback-summary-v1"
READBACK_BUNDLE_SCHEMA_VERSION = "ozon-response-bundle-v2"
READBACK_FINANCE_CONTRACT_VERSION = "ozon-finance-transactions-v1"
READBACK_PRODUCT_CONTRACT_VERSION = "ozon-product-read-v1"
READBACK_OFFICIAL_ORIGIN = "https://api-seller.ozon.ru"
READBACK_FINANCE_PATH = FINANCE_TRANSACTION_PATH
READBACK_PRODUCT_INFO_PATH = "/v3/product/info/list"
READBACK_PRODUCT_ATTRIBUTE_PATHS = {
    "/v4/product/info/attributes",
    "/v3/products/info/attributes",
}
READBACK_MAX_BUNDLE_BYTES = 1024 * 1024
READBACK_FRESHNESS_SECONDS = SignedManagedCredentialLeaseResolver.VERIFIER_TTL_SECONDS
READBACK_ACCEPTED_CONTRACTS = {
    READBACK_FINANCE_CONTRACT_VERSION,
    READBACK_PRODUCT_CONTRACT_VERSION,
}

REQUIRED_SUMMARY_KEYS = {
    "contract_id",
    "schema_version",
    "platform",
    "account_ref",
    "adapter_id",
    "adapter_version",
    "required_capability",
    "scope",
    "client_id_sha256",
    "credential_fingerprint_sha256",
    "secret_reference_sha256",
    "observed_at",
    "operation",
    "query_window_sha256",
    "response_bundle_sha256",
    "response_byte_size",
    "operation_count",
    "page",
    "page_size",
    "page_count",
    "captured_by",
    "official_origin_verified",
    "contract_version",
}


class ProviderReadbackVerifier:
    """Pure, versioned verifier for a fresh official provider readback.

    It is the independent external-verifier contract for the managed lease
    store: only a passing observation (with its content-addressed hash) may be
    recorded as ``external_verifier_observation_sha256`` on a lease.  The
    verifier never contacts the provider, never reads secrets, and rejects
    self-certification (verifier/capturer/provisioner must be distinct roles).
    """

    def verify(
        self,
        *,
        summary: dict[str, Any],
        bundle_bytes: bytes,
        facts: dict[str, Any],
        verifier_actor: str,
        provisioner_actor: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = self._aware(as_of)
        checks: dict[str, bool] = {}
        blockers: list[str] = []

        def check(name: str, passed: bool, blocker: str) -> None:
            checks[name] = passed
            if not passed:
                blockers.append(blocker)

        check(
            "summary_contract",
            summary.get("contract_id") == READBACK_SUMMARY_CONTRACT_ID
            and summary.get("schema_version") == "1",
            "READBACK_SUMMARY_CONTRACT_INVALID",
        )
        missing = sorted(REQUIRED_SUMMARY_KEYS - set(summary))
        check("summary_fields", not missing, f"READBACK_SUMMARY_MISSING_FIELDS:{','.join(missing)}")
        if summary.get("contract_id") == READBACK_SUMMARY_CONTRACT_ID and not missing:
            scope = summary.get("scope")
            check(
                "scope",
                isinstance(scope, dict)
                and scope.get("tenant_ref") == facts.get("tenant_ref")
                and scope.get("entity_ref") == facts.get("entity_ref")
                and scope.get("store_ref") == facts.get("store_ref"),
                "READBACK_SCOPE_DRIFT",
            )
            check(
                "identity_fingerprint",
                summary.get("credential_fingerprint_sha256")
                == facts.get("credential_fingerprint_sha256")
                and summary.get("secret_reference_sha256")
                == facts.get("secret_reference_sha256"),
                "READBACK_IDENTITY_DRIFT",
            )
            check(
                "binding",
                summary.get("platform") == facts.get("platform")
                and summary.get("account_ref") == facts.get("account_ref")
                and summary.get("adapter_id") == facts.get("adapter_id")
                and summary.get("adapter_version") == facts.get("adapter_version")
                and summary.get("required_capability") == facts.get("required_capability"),
                "READBACK_BINDING_DRIFT",
            )
            check(
                "official_origin",
                summary.get("official_origin_verified") is True
                and summary.get("contract_version") in READBACK_ACCEPTED_CONTRACTS,
                "READBACK_NOT_OFFICIAL",
            )
            check(
                "bundle_integrity",
                summary.get("response_bundle_sha256")
                == hashlib.sha256(bundle_bytes).hexdigest(),
                "READBACK_BUNDLE_HASH_DRIFT",
            )
            check(
                "bundle_size",
                summary.get("response_byte_size") == len(bundle_bytes),
                "READBACK_BUNDLE_SIZE_DRIFT",
            )
            bundle_contract_valid = self._bundle_contract_valid(
                bundle_bytes,
                str(summary.get("contract_version") or ""),
            )
            check(
                "bundle_contract",
                bundle_contract_valid,
                "READBACK_BUNDLE_CONTRACT_INVALID",
            )
            if (
                summary.get("contract_version") == READBACK_FINANCE_CONTRACT_VERSION
                and bundle_contract_valid
            ):
                check(
                    "finance_summary_alignment",
                    self._finance_summary_matches_bundle(summary, bundle_bytes),
                    "READBACK_SUMMARY_BUNDLE_MISMATCH",
                )
            if (
                summary.get("contract_version") == READBACK_PRODUCT_CONTRACT_VERSION
                and bundle_contract_valid
            ):
                check(
                    "product_summary_alignment",
                    self._product_summary_matches_bundle(summary, bundle_bytes),
                    "READBACK_SUMMARY_BUNDLE_MISMATCH",
                )
            check(
                "freshness",
                self._fresh(
                    summary.get("observed_at"),
                    facts.get("provider_readback_verified_at"),
                    cutoff,
                ),
                "READBACK_OBSERVATION_STALE",
            )
        check(
            "independence",
            str(verifier_actor or "").strip()
            not in {
                str(provisioner_actor or "").strip(),
                str(summary.get("captured_by") or "").strip(),
            }
            and str(summary.get("captured_by") or "").strip()
            != str(provisioner_actor or "").strip(),
            "READBACK_VERIFIER_NOT_INDEPENDENT",
        )

        verdict = "passed" if not blockers else "failed"
        input_hash = self._hash(
            {
                "verifier_version": PROVIDER_READBACK_VERIFIER_VERSION,
                "summary": summary,
                "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
                "facts": facts,
                "verifier_actor": verifier_actor,
                "provisioner_actor": provisioner_actor,
                "as_of": cutoff.isoformat(),
            }
        )
        observation = {
            "contract_id": PROVIDER_READBACK_CONTRACT_ID,
            "verifier_version": PROVIDER_READBACK_VERIFIER_VERSION,
            "verdict": verdict,
            "checks": checks,
            "blockers": sorted(blockers),
            "observed_at": cutoff.isoformat(),
            "input_sha256": input_hash,
            "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
            "captured_by": summary.get("captured_by"),
            "verified_by": verifier_actor,
        }
        observation["observation_sha256"] = self._hash(observation)
        return observation

    @classmethod
    def _bundle_contract_valid(
        cls,
        bundle_bytes: bytes,
        expected_contract: str,
    ) -> bool:
        parsed = cls._parse_bundle(bundle_bytes, expected_contract)
        return parsed is not None

    @classmethod
    def parse_bundle_contract(
        cls,
        bundle_bytes: bytes,
        expected_contract: str,
    ) -> dict[str, Any] | None:
        """Parse and validate one supported bundle for independent adapters.

        The public projection contains only contract metadata and counts.  It
        never returns decoded provider response bodies, so downstream
        acceptance evaluators can reuse the exact verifier rules without
        gaining a second path to raw external data.
        """
        return cls._parse_bundle(bundle_bytes, expected_contract)

    @classmethod
    def _finance_summary_matches_bundle(
        cls,
        summary: dict[str, Any],
        bundle_bytes: bytes,
    ) -> bool:
        parsed = cls._parse_bundle(bundle_bytes, READBACK_FINANCE_CONTRACT_VERSION)
        if parsed is None:
            return False
        return (
            summary.get("operation_count") == parsed["operation_count"]
            and summary.get("page_count") == parsed.get("page_count")
            and summary.get("operation") == parsed.get("operation")
            and summary.get("query_window_sha256")
            == parsed.get("query_window_sha256")
            and summary.get("page") == parsed.get("page")
            and summary.get("page_size") == parsed.get("page_size")
        )

    @classmethod
    def _product_summary_matches_bundle(
        cls,
        summary: dict[str, Any],
        bundle_bytes: bytes,
    ) -> bool:
        parsed = cls._parse_bundle(bundle_bytes, READBACK_PRODUCT_CONTRACT_VERSION)
        if parsed is None:
            return False
        # ``query_window_sha256`` is the historical summary field used by the
        # readback contract for a product target.  It carries the SHA-256 of
        # the requested offer id; the raw offer id is intentionally absent
        # from the bundle and from verifier output.
        return (
            summary.get("operation") == parsed.get("operation")
            and summary.get("query_window_sha256")
            == parsed.get("offer_id_sha256")
        )

    @classmethod
    def _parse_bundle(
        cls,
        bundle_bytes: bytes,
        expected_contract: str,
    ) -> dict[str, Any] | None:
        if not bundle_bytes or len(bundle_bytes) > READBACK_MAX_BUNDLE_BYTES:
            return None
        try:
            bundle = json.loads(bundle_bytes)
            if not isinstance(bundle, dict):
                return None
            if (
                bundle.get("schema_version") != READBACK_BUNDLE_SCHEMA_VERSION
                or bundle.get("contract_version") != expected_contract
            ):
                return None
            responses = bundle["responses"]
            if not isinstance(responses, list):
                return None
            parsed_bodies: list[dict[str, Any]] = []
            for item in responses:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("path"), str)
                    or not isinstance(item.get("status_code"), int)
                    or not 200 <= item["status_code"] < 300
                    or not isinstance(item.get("headers"), dict)
                ):
                    return None
                body = base64.b64decode(item["body_base64"], validate=True)
                if len(body) > READBACK_MAX_BUNDLE_BYTES:
                    return None
                if not hmac.compare_digest(
                    str(item.get("body_sha256") or ""),
                    hashlib.sha256(body).hexdigest(),
                ):
                    return None
                parsed_body = json.loads(body)
                if not isinstance(parsed_body, dict):
                    return None
                parsed_bodies.append(parsed_body)
            if expected_contract == READBACK_FINANCE_CONTRACT_VERSION:
                if len(parsed_bodies) != 1 or responses[0]["path"] != READBACK_FINANCE_PATH:
                    return None
                request_context = bundle.get("request_context")
                if not isinstance(request_context, dict):
                    return None
                if set(request_context) != {
                    "operation",
                    "query_window_sha256",
                    "page",
                    "page_size",
                }:
                    return None
                if (
                    request_context.get("operation") != "ozon.finance.read"
                    or not isinstance(request_context.get("query_window_sha256"), str)
                    or len(request_context["query_window_sha256"]) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in request_context["query_window_sha256"]
                    )
                    or isinstance(request_context.get("page"), bool)
                    or not isinstance(request_context.get("page"), int)
                    or request_context["page"] < 1
                    or isinstance(request_context.get("page_size"), bool)
                    or not isinstance(request_context.get("page_size"), int)
                    or not 1 <= request_context["page_size"] <= 1000
                ):
                    return None
                return {
                    **validate_finance_transactions_payload(parsed_bodies[0]),
                    **request_context,
                }
            if expected_contract == READBACK_PRODUCT_CONTRACT_VERSION:
                paths = [item["path"] for item in responses]
                if (
                    len(parsed_bodies) != 2
                    or READBACK_PRODUCT_INFO_PATH not in paths
                    or len(set(paths) & READBACK_PRODUCT_ATTRIBUTE_PATHS) != 1
                ):
                    return None
                if not all(isinstance(body, dict) for body in parsed_bodies):
                    return None
                request_context = bundle.get("request_context")
                if not isinstance(request_context, dict):
                    return None
                if set(request_context) != {"operation", "offer_id_sha256"}:
                    return None
                offer_hash = request_context.get("offer_id_sha256")
                if (
                    request_context.get("operation") != "ozon.product.read"
                    or not isinstance(offer_hash, str)
                    or len(offer_hash) != 64
                    or any(character not in "0123456789abcdef" for character in offer_hash)
                ):
                    return None
                return {
                    "response_count": len(parsed_bodies),
                    "operation": request_context["operation"],
                    "offer_id_sha256": offer_hash,
                }
            return None
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _fresh(
        observed_at: Any,
        verified_at: Any,
        cutoff: datetime,
    ) -> bool:
        try:
            observed = ProviderReadbackVerifier._aware(observed_at)
            verified = ProviderReadbackVerifier._aware(verified_at)
        except (TypeError, ValueError):
            return False
        if observed > cutoff or verified > cutoff:
            return False
        if (cutoff - observed).total_seconds() > READBACK_FRESHNESS_SECONDS:
            return False
        return (cutoff - verified).total_seconds() <= READBACK_FRESHNESS_SECONDS

    @staticmethod
    def _aware(value: Any) -> datetime:
        parsed = (
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if not isinstance(value, datetime)
            else value
        )
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("readback timestamp must include timezone")
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
