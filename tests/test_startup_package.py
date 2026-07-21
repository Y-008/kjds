from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path

from apps.control_plane.intelligence import MarketIntelligenceService
from scripts.validate_startup_package import (
    CANDIDATE_MEASUREMENT_CONTRACTS,
    CONTRACT,
    REVIEW_FIELDS,
    validate_startup_package,
)


def test_startup_package_contract_and_fail_closed_boundaries(tmp_path: Path):
    source = Path("web/public/startup")
    report = validate_startup_package(source)
    assert report["status"] == "structurally_valid"
    assert report["contract"] == "kjds-startup-package-v4"
    assert report["formal_fact_promoted"] is False
    assert report["submission_readiness"]["status"] == "awaiting_inputs"
    assert report["submission_readiness"]["automatic_import"] is False
    assert report["submission_readiness"]["blocked_sections"] == sorted(CONTRACT)
    assert report["coverage"]["suppliers_per_sku"] == {"RU-001": 3, "RU-002": 3, "RU-003": 3}
    assert report["coverage"]["media_roles_per_sku"] == {"RU-001": 7, "RU-002": 7, "RU-003": 7}
    assert report["coverage"]["ozon_api_identities"] == 7
    assert report["coverage"]["candidate_metrics_per_candidate"] == {
        "candidate://RU-001-v1": 5,
        "candidate://RU-002-v1": 5,
        "candidate://RU-003-v1": 5,
    }

    package = tmp_path / "startup"
    shutil.copytree(source, package)
    quote_path = package / "supplier-quotes.csv"
    with quote_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with quote_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(row for row in rows if row["sku"] != "RU-003")

    access_path = package / "g0-ozon-access.csv"
    with access_path.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(["api_key", "must-not-be-collected", "", "", "pending"])

    media_path = package / "sku-media.csv"
    with media_path.open(encoding="utf-8-sig", newline="") as handle:
        media_rows = list(csv.DictReader(handle))
        media_fields = list(media_rows[0])
    with media_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=media_fields)
        writer.writeheader()
        for row in media_rows:
            if row["sku"] == "RU-003" and row["variant_id"] == "base" and row["asset_role"] == "packaging":
                continue
            if row["sku"] == "RU-001" and row["variant_id"] == "base" and row["asset_role"] == "front_main":
                row["status"] = "verified"
            writer.writerow(row)

    rejected = validate_startup_package(package)
    assert rejected["status"] == "invalid"
    assert any("RU-003 requires exactly three distinct suppliers" in error for error in rejected["errors"])
    assert any("sensitive field names are forbidden: api_key" in error for error in rejected["errors"])
    assert any("RU-003 base variant is missing roles: packaging" in error for error in rejected["errors"])
    assert any("verified row RU-001/base/front_main is missing" in error for error in rejected["errors"])


def test_prepare_startup_package_adds_missing_templates_without_overwrite(tmp_path: Path):
    destination = tmp_path / "startup"
    destination.mkdir()
    preserved = destination / "g0-governance.csv"
    preserved.write_text("owner-entered-data", encoding="utf-8")

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            "scripts/prepare-startup-package.ps1",
            "-Destination",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)

    assert report["status"] == "updated"
    assert report["template_count"] == 8
    assert report["added_templates"] == [
        "candidate-research.csv",
        "finance-reconciliation.csv",
        "g0-ozon-access.csv",
        "g0-ozon-api-identities.csv",
        "sku-media.csv",
        "sku-passports.csv",
        "supplier-quotes.csv",
    ]
    assert report["preserved_templates"] == ["g0-governance.csv"]
    assert preserved.read_text(encoding="utf-8") == "owner-entered-data"
    assert len(list(destination.glob("*.csv"))) == 8


def test_ozon_api_identity_inventory_rejects_missing_and_duplicate_references(tmp_path: Path):
    package = tmp_path / "startup"
    shutil.copytree(Path("web/public/startup"), package)
    identity_path = package / "g0-ozon-api-identities.csv"
    with identity_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    rows[0]["identity_ref"] = ""
    rows[1]["identity_ref"] = rows[2]["identity_ref"]
    with identity_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    report = validate_startup_package(package)
    assert report["status"] == "invalid"
    assert "g0-ozon-api-identities.csv: every row requires identity_ref" in report["errors"]
    assert "g0-ozon-api-identities.csv: identity_ref values must be unique" in report["errors"]


def test_review_readiness_requires_filled_rows_but_never_promotes_facts(tmp_path: Path):
    package = tmp_path / "startup"
    shutil.copytree(Path("web/public/startup"), package)

    for filename, fields in REVIEW_FIELDS.items():
        path = package / filename
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            fieldnames = list(rows[0])
        for row in rows:
            for field in fields:
                row[field] = "review-input"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    candidate_path = package / "candidate-research.csv"
    with candidate_path.open(encoding="utf-8-sig", newline="") as handle:
        candidate_rows = list(csv.DictReader(handle))
        candidate_fields = list(candidate_rows[0])
    for index, row in enumerate(candidate_rows):
        metric = row["metric"]
        row.update(
            {
                "candidate_name": f"Candidate {row['candidate_ref'][-6:-3]}",
                "category": "kitchen_storage",
                "value": "1" if metric == "supplier_available" else "0" if metric == "compliance_redline" else "60",
                "confidence": "0.8",
                "evidence_reference": f"controlled-store://candidate/{index}",
                "source_family": "ozon" if index % 2 == 0 else "supplier-market",
                "observed_at": "2026-07-18T12:00:00+08:00",
                "owner": "product-owner",
                "status": "verified",
            }
        )
    with candidate_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=candidate_fields)
        writer.writeheader()
        writer.writerows(candidate_rows)

    media_path = package / "sku-media.csv"
    with media_path.open(encoding="utf-8-sig", newline="") as handle:
        media_rows = list(csv.DictReader(handle))
        media_fields = list(media_rows[0])
    for row in media_rows:
        row.update(
            {
                "source_kind": "sample_photo",
                "source_reference": "controlled-store://source",
                "rights_evidence_reference": "controlled-store://rights",
                "captured_at": "2026-07-18T12:00:00+08:00",
                "sha256": "a" * 64,
                "owner": "product-owner",
                "status": "verified",
            }
        )
    with media_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=media_fields)
        writer.writeheader()
        writer.writerows(media_rows)

    report = validate_startup_package(package)
    assert report["status"] == "structurally_valid"
    assert report["submission_readiness"]["status"] == "ready_for_human_intake"
    assert report["submission_readiness"]["blocked_sections"] == []
    assert report["submission_readiness"]["automatic_import"] is False
    assert report["submission_readiness"]["formal_fact_promoted"] is False

    strict = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/validate_startup_package.py",
            "web/public/startup",
            "--require-review-ready",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    strict_report = json.loads(strict.stdout)
    assert strict.returncode == 3
    assert strict_report["status"] == "structurally_valid"
    assert strict_report["submission_readiness"]["status"] == "awaiting_inputs"


def test_candidate_research_template_rejects_missing_metric_and_invalid_measurement(tmp_path: Path):
    package = tmp_path / "startup"
    shutil.copytree(Path("web/public/startup"), package)
    candidate_path = package / "candidate-research.csv"
    with candidate_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    rows = [row for row in rows if not (
        row["candidate_ref"] == "candidate://RU-003-v1" and row["metric"] == "return_risk"
    )]
    rows[0]["window_days"] = "7"
    rows[1]["value"] = "NaN"
    with candidate_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    report = validate_startup_package(package)

    assert report["status"] == "invalid"
    assert any("measurement contract mismatch" in error for error in report["errors"])
    assert any("value outside metric range" in error for error in report["errors"])
    assert any("requires each fixed metric exactly once" in error for error in report["errors"])


def test_candidate_template_measurement_contract_stays_aligned_with_runtime_policy():
    runtime = {
        metric: (
            int(contract["min_window_days"]),
            int(contract["max_window_days"]),
            int(contract["min_sample_size"]),
        )
        for metric, contract in MarketIntelligenceService.CANDIDATE_MEASUREMENT_CONTRACTS.items()
    }
    assert runtime == CANDIDATE_MEASUREMENT_CONTRACTS
