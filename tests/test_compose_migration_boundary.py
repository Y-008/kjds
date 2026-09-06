"""Static and render-time checks for the Compose migration boundary.

The API image is a runtime image.  Database schema ownership is intentionally
isolated in the short-lived ``migrate`` service so an API restart cannot run
DDL with its non-owner runtime principal.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
COMPOSE = ROOT / "compose.yaml"
DOCKERFILE = ROOT / "Dockerfile"


def _service_block(source: str, service: str, next_service: str | None = None) -> str:
    marker = f"  {service}:"
    start = source.index(marker)
    if next_service is None:
        return source[start:]
    end = source.index(f"  {next_service}:", start + len(marker))
    return source[start:end]


def _environment_mapping(service: dict) -> dict[str, str]:
    environment = service.get("environment", {})
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}
    if isinstance(environment, list):
        result: dict[str, str] = {}
        for item in environment:
            key, separator, value = str(item).partition("=")
            result[key] = value if separator else ""
        return result
    raise AssertionError("Compose environment must be a mapping or list")


def test_dockerfile_assigns_schema_ownership_to_migrate_stage_only():
    source = DOCKERFILE.read_text(encoding="utf-8")
    migrate = source[source.index("FROM control-plane AS migrate") : source.index("FROM control-plane AS api")]
    api = source[source.index("FROM control-plane AS api") : source.index("FROM mwader/static-ffmpeg")]

    assert "CMD" in migrate
    assert "alembic upgrade head" in migrate
    assert "KJDS_DATABASE_URL" in migrate
    assert "KJDS_RUNTIME_DATABASE_URL" in migrate
    assert "CMD" in api
    assert '"uvicorn"' in api
    assert '"apps.control_plane.api:app"' in api
    assert "alembic" not in api


def test_compose_static_boundary_keeps_admin_dsn_out_of_runtime_services():
    source = COMPOSE.read_text(encoding="utf-8")
    migrate = _service_block(source, "migrate", "api")
    api = _service_block(source, "api", "web")

    assert "KJDS_DATABASE_URL: ${KJDS_DATABASE_URL:?" in migrate
    assert "KJDS_RUNTIME_DATABASE_URL" not in migrate
    assert "KJDS_DATABASE_URL:" not in api
    assert "alembic" not in api
    assert "condition: service_completed_successfully" in api
    assert 'restart: "no"' in migrate
    assert "condition: service_healthy" in migrate
    # Required interpolation prevents an empty or invented DSN from making a
    # rendered stack appear deployable.
    assert "KJDS_RUNTIME_DATABASE_URL: ${KJDS_RUNTIME_DATABASE_URL:?" in api

    for service in ("postgres", "web", "media-worker", "ozon-worker", "ozon-read-worker"):
        block = _service_block(source, service, {
            "postgres": "migrate",
            "web": "media-worker",
            "media-worker": "ozon-worker",
            "ozon-worker": "ozon-read-worker",
            "ozon-read-worker": None,
        }[service])
        assert "KJDS_DATABASE_URL:" not in block


def test_compose_config_renders_split_services_without_starting_containers(tmp_path: Path):
    if shutil.which("docker") is None:
        pytest.skip("docker is unavailable; static Compose checks still run")

    env_file = tmp_path / "compose-contract.env"
    env_file.write_text(
        "\n".join(
            (
                "KJDS_DATABASE_URL=postgresql+psycopg://migration_user:fixture@postgres:5432/hermes",
                "KJDS_RUNTIME_DATABASE_URL=postgresql+psycopg://runtime_user:fixture@postgres:5432/hermes",
                "KJDS_BUILD_COMMIT=fixture-commit",
                "KJDS_MIGRATION_HEAD=fixture-head",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    process_env = os.environ.copy()
    # python-dotenv may have loaded the repository's local .env in an earlier
    # test module; explicit process values must not make this render check
    # accidentally exercise a developer credential.
    process_env.update(
        {
            "KJDS_DATABASE_URL": "postgresql+psycopg://migration_user:fixture@postgres:5432/hermes",
            "KJDS_RUNTIME_DATABASE_URL": "postgresql+psycopg://runtime_user:fixture@postgres:5432/hermes",
            "KJDS_BUILD_COMMIT": "fixture-commit",
            "KJDS_MIGRATION_HEAD": "fixture-head",
        }
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(COMPOSE),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=process_env,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    services = rendered["services"]

    migrate_env = _environment_mapping(services["migrate"])
    api_env = _environment_mapping(services["api"])
    assert migrate_env["KJDS_DATABASE_URL"].startswith(
        "postgresql+psycopg://migration_user:"
    )
    assert "KJDS_DATABASE_URL" not in api_env
    assert api_env["KJDS_RUNTIME_DATABASE_URL"].startswith(
        "postgresql+psycopg://runtime_user:"
    )
    assert services["api"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["migrate"]["restart"] == "no"

    # The admin DSN is not injected into any runtime/worker service in the
    # fully interpolated configuration.
    for name, service in services.items():
        if name == "migrate":
            continue
        assert "KJDS_DATABASE_URL" not in _environment_mapping(service)
