from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "verify-g1.ps1"
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


def test_g1_harness_keeps_infrastructure_seams_without_domain_scenarios():
    source = HARNESS.read_text(encoding="utf-8")

    required_seams = (
        "Replaying migrations in disposable database",
        "Verifying transactional outbox on PostgreSQL",
        "Running Python quality gates",
        "Verifying production API image",
        "Verifying Ozon Worker cannot bypass explicit execution intent",
        "Starting disposable API",
        "Verifying bounded Evidence integrity monitoring",
        "Verifying backup and isolated restore",
        "Starting disposable web UI",
    )
    for seam in required_seams:
        assert seam in source

    migrated_domain_routes = (
        "/v1/market/research-signals",
        "/v1/experiments",
        "/v1/policies",
        "/v1/procurement",
        "/v1/finance/cash-plan",
        "/v1/finance/reconciliation",
        "/v1/sourcing/supplier-comparisons",
    )
    for route in migrated_domain_routes:
        assert route not in source

    assert "alembic heads" in source
    assert 'result.migration = "20' not in source
    assert len(source.splitlines()) < 900


def test_production_image_packages_machine_readable_registries():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")

    assert "COPY docs/project/registries ./docs/project/registries" in dockerfile
    assert "!docs/project/registries/*.json" in dockerignore
