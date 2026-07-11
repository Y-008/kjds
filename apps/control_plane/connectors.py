from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ConnectorRecord:
    source: str
    record_type: str
    external_id: str
    occurred_at: str
    payload: dict[str, Any]
    source_ref: str


class CommerceConnector(Protocol):
    """Anti-corruption boundary for Ozon, logistics, ads and settlement providers."""

    name: str

    def pull(self, *, cursor: str | None = None) -> tuple[list[ConnectorRecord], str | None]: ...

    def healthcheck(self) -> dict[str, Any]: ...


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, CommerceConnector] = {}

    def register(self, connector: CommerceConnector) -> None:
        if connector.name in self._connectors:
            raise ValueError(f"Connector already registered: {connector.name}")
        self._connectors[connector.name] = connector

    def get(self, name: str) -> CommerceConnector:
        try:
            return self._connectors[name]
        except KeyError as exc:
            raise KeyError(f"Unknown connector: {name}") from exc
