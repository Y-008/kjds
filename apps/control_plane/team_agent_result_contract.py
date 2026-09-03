"""Shared fail-closed contract for TeamAgent result payloads."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .enterprise_control import DataClassification, PayloadClassifier

FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "fact",
        "formal_fact",
        "finance_entry",
        "approval",
        "permit",
        "external_write",
        "external_write_allowed",
    }
)
SENSITIVE_RESULT_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "bank_account",
        "card_number",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "credit_card",
        "email",
        "national_id",
        "password",
        "passport",
        "phone",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
        "ssn",
        "tax_id",
        "token",
    }
)
FORBIDDEN_RESULT_KEY_TOKENS = frozenset(
    key.replace("_", "") for key in FORBIDDEN_RESULT_KEYS
)
FORBIDDEN_RESULT_KEY_ALIASES = frozenset(
    {
        *FORBIDDEN_RESULT_KEYS,
        "approvals",
        "external_writes",
        "facts",
        "finance_entries",
        "formal_facts",
        "permits",
    }
)
AUTHORITY_DISCRIMINATOR_KEYS = frozenset(
    {
        "action",
        "authority",
        "kind",
        "object_type",
        "record_type",
        "resource_type",
        "type",
    }
)
SENSITIVE_RESULT_KEY_TOKENS = frozenset(
    key.replace("_", "") for key in SENSITIVE_RESULT_KEYS
)
RESULT_CLASSIFIER = PayloadClassifier()


class TeamAgentResultContractError(ValueError):
    """The proposed result cannot enter checkpoints, traces, or persistence."""


def _normalized_key(value: Any) -> str:
    snake_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value).strip())
    return re.sub(r"[^a-z0-9]+", "_", snake_case.lower()).strip("_")


def _contains_authority_marker(normalized_key: str) -> bool:
    padded = f"_{normalized_key}_"
    return any(
        f"_{marker}_" in padded
        for marker in FORBIDDEN_RESULT_KEY_ALIASES
    )


def normalize_team_agent_result(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical JSON-safe data after authority and secret scanning."""

    try:
        payload = json.loads(
            json.dumps(
                dict(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise TeamAgentResultContractError(
            "task result must be a canonical JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise TeamAgentResultContractError("task result must be an object")

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                normalized_key = _normalized_key(key)
                key_token = "".join(
                    character
                    for character in normalized_key
                    if character.isalnum()
                )
                if (
                    normalized_key in FORBIDDEN_RESULT_KEYS
                    or key_token in FORBIDDEN_RESULT_KEY_TOKENS
                    or _contains_authority_marker(normalized_key)
                ):
                    raise TeamAgentResultContractError(
                        "TeamAgent results cannot mint authority or external writes"
                    )
                if (
                    normalized_key in AUTHORITY_DISCRIMINATOR_KEYS
                    and isinstance(child, str)
                    and _contains_authority_marker(_normalized_key(child))
                ):
                    raise TeamAgentResultContractError(
                        "TeamAgent results cannot mint authority or external writes"
                    )
                sensitive_markers = (
                    "access_token",
                    "api_key",
                    "bank_account",
                    "card_number",
                    "credential",
                    "email",
                    "national_id",
                    "passport",
                    "password",
                    "phone",
                    "private_key",
                    "refresh_token",
                    "secret",
                    "session_token",
                    "ssn",
                    "tax_id",
                )
                if (
                    normalized_key in SENSITIVE_RESULT_KEYS
                    or key_token in SENSITIVE_RESULT_KEY_TOKENS
                    or any(
                        marker in normalized_key
                        or marker.replace("_", "") in key_token
                        for marker in sensitive_markers
                    )
                ):
                    raise TeamAgentResultContractError(
                        "TeamAgent results cannot contain sensitive fields"
                    )
                walk(child)
        elif isinstance(node, Sequence) and not isinstance(
            node, (str, bytes, bytearray)
        ):
            for child in node:
                walk(child)

    walk(payload)
    classification = RESULT_CLASSIFIER.classify(payload)
    if classification in {
        DataClassification.PERSONAL,
        DataClassification.SECRET,
    }:
        raise TeamAgentResultContractError(
            "TeamAgent results cannot contain sensitive values"
        )
    return payload


__all__ = [
    "FORBIDDEN_RESULT_KEYS",
    "SENSITIVE_RESULT_KEYS",
    "TeamAgentResultContractError",
    "normalize_team_agent_result",
]
