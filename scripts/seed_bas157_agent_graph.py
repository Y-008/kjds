from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import seed_bas154_agent_graph as kernel
from alembic.config import Config
from alembic.script import ScriptDirectory

from apps.control_plane.agent_harness import _sha

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    "docs/project/evidence/"
    "20260730_BAS_157_NATIVE_EXACT_SCOPE_WAREHOUSE_FULFILLMENT.md"
)
SCREENSHOTS = (
    "output/playwright/bas157-warehouse-fulfillment-desktop.png",
    "output/playwright/bas157-warehouse-fulfillment-mobile-390.png",
)

TASKS = (
    (
        "task-bas157-pytest",
        "BAS-157 warehouse authority and fail-closed composition",
        "tests",
        ("task-bas156-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas157-database",
        "BAS-157 append-only PostgreSQL 0080 authority",
        "database",
        ("task-bas157-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas157-runtime",
        "BAS-157 authenticated deterministic no-data runtime",
        "runtime",
        ("task-bas157-database",),
        "/runtime-graph",
    ),
    (
        "task-bas157-web",
        "BAS-157 executable states and responsive workspace",
        "web",
        ("task-bas157-runtime",),
        "/warehouse-fulfillment",
    ),
    (
        "task-bas157-evidence",
        "BAS-157 immutable engineering Evidence",
        "evidence",
        ("task-bas157-web",),
        "/evidence-graph",
    ),
)

NODES = (
    (
        "requirements",
        "requirement:BR-131@master-8.63",
        "requirement",
        "BR-131 native exact-scope warehouse fulfillment authority",
        "docs/project/MASTER_SPEC.md",
        "task-bas157-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0077",
        "adr",
        "ADR-0077 native exact-scope warehouse fulfillment authority",
        "docs/adr/ADR-0077-native-exact-scope-warehouse-fulfillment-authority.md",
        "task-bas157-pytest",
    ),
    (
        "engineering",
        "service:scoped-warehouse-fulfillment-v1",
        "service",
        "ScopedWarehouseFulfillmentWorkspace exact-scope v1",
        "apps/control_plane/scoped_warehouse_fulfillment.py",
        "task-bas157-pytest",
    ),
    (
        "engineering",
        "service:warehouse-execution-authority-v1",
        "service",
        "Append-only warehouse event and governed Readback authority",
        "apps/control_plane/warehouse_fulfillment.py",
        "task-bas157-pytest",
    ),
    (
        "engineering",
        "policy:warehouse-l4-policy-only",
        "policy",
        "Warehouse mutation actions remain L4 policy-only",
        "docs/project/registries/write_path_registry.json",
        "task-bas157-pytest",
    ),
    (
        "engineering",
        "database:native-warehouse-authority-0080",
        "database_probe",
        "Forward-only append-only warehouse authority at 0080",
        "migrations/versions/20260730_0080_native_warehouse_execution_authority.py",
        "task-bas157-database",
    ),
    (
        "runtime",
        "api:native-warehouse-fulfillment-no-data",
        "api_probe",
        "Authenticated warehouse fulfillment no-data boundary",
        "http://127.0.0.1:8000/v1/warehouse-fulfillment/workspace",
        "task-bas157-runtime",
    ),
    (
        "runtime",
        "web:native-warehouse-fulfillment-390",
        "browser_probe",
        "Warehouse fulfillment desktop and 390px",
        SCREENSHOTS[1],
        "task-bas157-web",
    ),
    (
        "evidence",
        "evidence:BAS-157",
        "evidence",
        "BAS-157 warehouse contract/no-data Evidence",
        EVIDENCE,
        "task-bas157-evidence",
    ),
)

EDGES = (
    (
        "requirement:BR-131@master-8.63",
        "specified_by",
        "adr:ADR-0077",
        "requirements",
    ),
    (
        "adr:ADR-0077",
        "implemented_by",
        "service:scoped-warehouse-fulfillment-v1",
        "engineering",
    ),
    (
        "service:scoped-warehouse-fulfillment-v1",
        "requires",
        "service:warehouse-execution-authority-v1",
        "engineering",
    ),
    (
        "service:warehouse-execution-authority-v1",
        "bounded_by",
        "policy:warehouse-l4-policy-only",
        "engineering",
    ),
    (
        "service:warehouse-execution-authority-v1",
        "persists_at",
        "database:native-warehouse-authority-0080",
        "engineering",
    ),
    (
        "database:native-warehouse-authority-0080",
        "observed_as",
        "api:native-warehouse-fulfillment-no-data",
        "runtime",
    ),
    (
        "api:native-warehouse-fulfillment-no-data",
        "rendered_by",
        "web:native-warehouse-fulfillment-390",
        "runtime",
    ),
    (
        "web:native-warehouse-fulfillment-390",
        "recorded_in",
        "evidence:BAS-157",
        "evidence",
    ),
)


def sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def observations() -> dict[str, dict[str, str]]:
    output = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_warehouse_fulfillment_authority.py",
            "tests/test_scoped_warehouse_fulfillment.py",
            "tests/test_warehouse_fulfillment_api.py",
            "tests/test_write_path_registry.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas157-graph-{os.getpid()}",
        ]
    )
    match = re.search(r"(\d+) passed", output)
    if match is None:
        raise RuntimeError("BAS-157 focused tests did not pass")
    passed = int(match.group(1))

    heads = ScriptDirectory.from_config(
        Config(str(ROOT / "alembic.ini"))
    ).get_heads()
    if heads != ["20260730_0080"]:
        raise RuntimeError(f"BAS-157 Alembic head drifted: {heads}")
    replay_output = run(
        [sys.executable, "scripts/verify_bas157_migration_replay.py"]
    )
    if "base -> 0080 -> 0079 -> 0080" not in replay_output:
        raise RuntimeError("BAS-157 PostgreSQL replay did not pass")

    runtime = json.loads(
        run([sys.executable, "scripts/verify_bas157_runtime.py"])
        .strip()
        .splitlines()[-1]
    )
    if (
        runtime.get("anonymous") != 401
        or runtime.get("authenticated") != 200
        or runtime.get("forbidden") != 403
        or runtime.get("readiness") != 200
        or runtime.get("status") != "no_data"
        or runtime.get("total") != 0
        or runtime.get("upstream_reads") != []
        or runtime.get("deterministic") is not True
        or runtime.get("external_write_allowed") is not False
        or runtime.get("private_erp_interface_allowed") is not False
    ):
        raise RuntimeError("BAS-157 runtime truth boundary drifted")

    compose = [
        json.loads(line)
        for line in run(
            ["docker", "compose", "ps", "--format", "json"]
        ).splitlines()
        if line.strip()
    ]
    healthy = {
        row["Service"]
        for row in compose
        if row.get("State") == "running"
        and row.get("Health") == "healthy"
    }
    if not {"api", "media-worker", "postgres", "web"} <= healthy:
        raise RuntimeError("BAS-157 containers are not healthy")

    web_output = run(
        ["npm.cmd" if os.name == "nt" else "npm", "test"],
        cwd=ROOT / "web",
    )
    if "fail 0" not in web_output or "pass 111" not in web_output:
        raise RuntimeError(
            "BAS-157 executable Web state tests did not pass"
        )
    shots = {path: sha(path) for path in SCREENSHOTS}

    evidence = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "contract/no_data",
        "1007 passed",
        "111 passed",
        "20260730_0080",
        "1440/1440",
        "390/390",
        "external_write_allowed=false",
        "global 0.59→M4 goal",
    ):
        if marker not in evidence:
            raise RuntimeError(
                f"BAS-157 Evidence marker missing: {marker}"
            )

    common = {"state": "passed"}
    return {
        "tests": {
            **common,
            "summary": (
                f"{passed} focused tests executed by this verifier; "
                "exact-scope authority, conservation, governance-chain "
                "and policy-only closure pass; separate current full "
                "1007-test gate is recorded in immutable Evidence"
            ),
            "input_sha256": _sha(
                [
                    sha(
                        "apps/control_plane/"
                        "scoped_warehouse_fulfillment.py"
                    ),
                    sha("apps/control_plane/warehouse_fulfillment.py"),
                    sha(
                        "tests/"
                        "test_scoped_warehouse_fulfillment.py"
                    ),
                    sha(
                        "tests/test_warehouse_fulfillment_authority.py"
                    ),
                    sha("tests/test_warehouse_fulfillment_api.py"),
                    sha(
                        "docs/project/registries/"
                        "write_path_registry.json"
                    ),
                ]
            ),
            "artifact_ref": "process:pytest BAS-157",
        },
        "database": {
            **common,
            "summary": (
                "Alembic current/head single 0080; empty PostgreSQL "
                "base→0080→0079→0080 replay and append-only triggers pass"
            ),
            "input_sha256": _sha(
                [
                    heads,
                    hashlib.sha256(
                        replay_output.encode()
                    ).hexdigest(),
                    sha(
                        "migrations/versions/"
                        "20260730_0080_native_warehouse_"
                        "execution_authority.py"
                    ),
                ]
            ),
            "artifact_ref": "postgres:alembic_version",
        },
        "runtime": {
            **common,
            "summary": (
                "401/200/403 deterministic real no_data with zero "
                "upstream reads; production warehouse source unbound"
            ),
            "input_sha256": _sha(runtime),
            "artifact_ref": (
                "http://127.0.0.1:8000/"
                "v1/warehouse-fulfillment/workspace"
            ),
        },
        "web": {
            **common,
            "summary": (
                "111 executable Web tests plus desktop 1440 and mobile "
                "390; error/retry/success and blocked/no_data/ready "
                "states pass with strict width and zero console errors"
            ),
            "input_sha256": _sha(
                [
                    sha(
                        "web/features/warehouse-fulfillment/"
                        "warehouse-fulfillment-console.tsx"
                    ),
                    sha(
                        "web/lib/warehouse-fulfillment-state.ts"
                    ),
                    sha(
                        "web/lib/"
                        "warehouse-fulfillment-state.test.ts"
                    ),
                    shots,
                ]
            ),
            "artifact_ref": SCREENSHOTS[1],
        },
        "evidence": {
            **common,
            "summary": (
                f"BAS-157 Evidence SHA-256 {sha(EVIDENCE)}"
            ),
            "input_sha256": sha(EVIDENCE),
            "artifact_ref": EVIDENCE,
        },
    }


if __name__ == "__main__":
    kernel.EVIDENCE = EVIDENCE
    kernel.TASK_SPECS = TASKS
    kernel.NODE_SPECS = NODES
    kernel.EDGE_SPECS = EDGES
    kernel.upsert_graph(observations())
    result = kernel.counts()
    if (
        result["tasks"] < 116
        or result["nodes"] < 242
        or result["edges"] < 237
    ):
        raise RuntimeError(f"BAS-157 Graph count drifted: {result}")
    print(
        json.dumps(
            {
                "project_id": kernel.PROJECT_ID,
                **result,
                "business_state": "no_data",
                "authorized_warehouse_source_bound": False,
                "external_write_allowed": False,
            },
            sort_keys=True,
        )
    )
