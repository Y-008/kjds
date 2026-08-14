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

PROVIDER_READBACK_VERIFIER_VERSION = "1.0"
PROVIDER_READBACK_CONTRACT_ID = "kjds-provider-readback-verifier-v1"
READBACK_SUMMARY_CONTRACT_ID = "kjds-provider-readback-summary-v1"
READBACK_BUNDLE_SCHEMA_VERSION = "ozon-response-bundle-v2"
READBACK_FINANCE_CONTRACT_VERSION = "ozon-finance-transactions-v1"
READBACK_PRODUCT_CONTRACT_VERSION = "ozon-product-read-v1"
READBACK_OFFICIAL_ORIGIN = "https://api-seller.ozon.ru"
READBACK_FINANCE_PATH = "/v3/finance/transaction/list"
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
                "bundle_contract",
                self._bundle_contract_valid(
                    bundle_bytes,
                    str(summary.get("contract_version") or ""),
                ),
                "READBACK_BUNDLE_CONTRACT_INVALID",
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
        if not bundle_bytes or len(bundle_bytes) > READBACK_MAX_BUNDLE_BYTES:
            return False
        try:
            bundle = json.loads(bundle_bytes)
            if (
                bundle.get("schema_version") != READBACK_BUNDLE_SCHEMA_VERSION
                or bundle.get("contract_version") != expected_contract
            ):
                return False
            responses = bundle["responses"]
            if not isinstance(responses, list):
                return False
            parsed_bodies: list[dict[str, Any]] = []
            for item in responses:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("path"), str)
                    or not isinstance(item.get("status_code"), int)
                    or not 200 <= item["status_code"] < 300
                    or not isinstance(item.get("headers"), dict)
                ):
                    return False
                body = base64.b64decode(item["body_base64"], validate=True)
                if len(body) > READBACK_MAX_BUNDLE_BYTES:
                    return False
                if not hmac.compare_digest(
                    str(item.get("body_sha256") or ""),
                    hashlib.sha256(body).hexdigest(),
                ):
                    return False
                parsed_bodies.append(json.loads(body))
            if expected_contract == READBACK_FINANCE_CONTRACT_VERSION:
                if len(parsed_bodies) != 1 or responses[0]["path"] != READBACK_FINANCE_PATH:
                    return False
                parsed = parsed_bodies[0]
                return isinstance(parsed.get("result", {}).get("operations"), list)
            if expected_contract == READBACK_PRODUCT_CONTRACT_VERSION:
                paths = [item["path"] for item in responses]
                if (
                    len(parsed_bodies) != 2
                    or READBACK_PRODUCT_INFO_PATH not in paths
                    or len(set(paths) & READBACK_PRODUCT_ATTRIBUTE_PATHS) != 1
                ):
                    return False
                return all(isinstance(body, dict) for body in parsed_bodies)
            return False
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False

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
