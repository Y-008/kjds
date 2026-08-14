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
    "20260730_BAS_156_NATIVE_EXACT_SCOPE_DELIVERY_EXCEPTIONS.md"
)
SCREENSHOTS = (
    "output/playwright/bas156-delivery-exceptions-desktop.png",
    "output/playwright/bas156-delivery-exceptions-mobile-390.png",
)

TASKS = (
    (
        "task-bas156-pytest",
        "BAS-156 delivery/readback authority contracts",
        "tests",
        ("task-bas155-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas156-database",
        "BAS-156 single-head composed authority",
        "database",
        ("task-bas156-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas156-runtime",
        "BAS-156 authenticated deterministic no-data runtime",
        "runtime",
        ("task-bas156-database",),
        "/runtime-graph",
    ),
    (
        "task-bas156-web",
        "BAS-156 executable states and responsive workspace",
        "web",
        ("task-bas156-runtime",),
        "/delivery-exceptions",
    ),
    (
        "task-bas156-evidence",
        "BAS-156 immutable engineering Evidence",
        "evidence",
        ("task-bas156-web",),
        "/evidence-graph",
    ),
)
NODES = (
    (
        "requirements",
        "requirement:BR-130@master-8.61",
        "requirement",
        "BR-130 native exact-scope delivery exception authority",
        "docs/project/MASTER_SPEC.md",
        "task-bas156-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0076",
        "adr",
        "ADR-0076 native exact-scope delivery exception authority",
        "docs/adr/ADR-0076-native-exact-scope-delivery-exception-authority.md",
        "task-bas156-pytest",
    ),
    (
        "engineering",
        "service:scoped-delivery-exception-v1",
        "service",
        "ScopedDeliveryExceptionWorkspace exact-scope v1",
        "apps/control_plane/scoped_delivery_exceptions.py",
        "task-bas156-pytest",
    ),
    (
        "engineering",
        "service:authorized-delivery-readback-v1",
        "service",
        "Authorized read-only delivery Readback contract",
        "apps/control_plane/delivery_readback.py",
        "task-bas156-pytest",
    ),
    (
        "engineering",
        "database:bas156-existing-authorities-0079",
        "database_probe",
        "BAS-156 composes existing authorities at single 0079",
        "migrations/versions/20260730_0079_native_scoped_customer_service.py",
        "task-bas156-database",
    ),
    (
        "runtime",
        "api:native-delivery-exception-no-data",
        "api_probe",
        "Authenticated delivery exception no-data boundary",
        "http://127.0.0.1:8000/v1/delivery-exceptions/workspace",
        "task-bas156-runtime",
    ),
    (
        "runtime",
        "web:native-delivery-exception-390",
        "browser_probe",
        "Delivery exception desktop and 390px",
        SCREENSHOTS[1],
        "task-bas156-web",
    ),
    (
        "evidence",
        "evidence:BAS-156",
        "evidence",
        "BAS-156 delivery exception contract/no-data Evidence",
        EVIDENCE,
        "task-bas156-evidence",
    ),
)
EDGES = (
    (
        "requirement:BR-130@master-8.61",
        "specified_by",
        "adr:ADR-0076",
        "requirements",
    ),
    (
        "adr:ADR-0076",
        "implemented_by",
        "service:scoped-delivery-exception-v1",
        "engineering",
    ),
    (
        "service:scoped-delivery-exception-v1",
        "requires",
        "service:authorized-delivery-readback-v1",
        "engineering",
    ),
    (
        "service:authorized-delivery-readback-v1",
        "composes_at",
        "database:bas156-existing-authorities-0079",
        "engineering",
    ),
    (
        "database:bas156-existing-authorities-0079",
        "observed_as",
        "api:native-delivery-exception-no-data",
        "runtime",
    ),
    (
        "api:native-delivery-exception-no-data",
        "rendered_by",
        "web:native-delivery-exception-390",
        "runtime",
    ),
    (
        "web:native-delivery-exception-390",
        "recorded_in",
        "evidence:BAS-156",
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
            "tests/test_delivery_readback.py",
            "tests/test_scoped_delivery_exceptions.py",
            "tests/test_api_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas156-graph-{os.getpid()}",
        ]
    )
    match = re.search(r"(\d+) passed", output)
    if match is None:
        raise RuntimeError("BAS-156 focused tests did not pass")
    passed = int(match.group(1))

    heads = ScriptDirectory.from_config(
        Config(str(ROOT / "alembic.ini"))
    ).get_heads()
    if heads != ["20260730_0079"]:
        raise RuntimeError(f"BAS-156 Alembic head drifted: {heads}")

    runtime = json.loads(
        run([sys.executable, "scripts/verify_bas156_runtime.py"])
        .strip()
        .splitlines()[-1]
    )
    if (
        runtime.get("anonymous") != 401
        or runtime.get("authenticated") != 200
        or runtime.get("forbidden") != 403
        or runtime.get("status") != "no_data"
        or runtime.get("total") != 0
        or runtime.get("deterministic") is not True
        or runtime.get("upstream_reads") != []
        or runtime.get("external_write_allowed") is not False
        or runtime.get("private_erp_interface_allowed") is not False
    ):
        raise RuntimeError("BAS-156 runtime truth boundary drifted")

    compose = [
        json.loads(line)
        for line in run(["docker", "compose", "ps", "--format", "json"])
        .splitlines()
        if line.strip()
    ]
    healthy = {
        row["Service"]
        for row in compose
        if row.get("State") == "running"
        and row.get("Health") == "healthy"
    }
    if not {"api", "media-worker", "postgres", "web"} <= healthy:
        raise RuntimeError("BAS-156 containers are not healthy")

    web_output = run(
        ["npm.cmd" if os.name == "nt" else "npm", "test"],
        cwd=ROOT / "web",
    )
    if "fail 0" not in web_output or "pass 107" not in web_output:
        raise RuntimeError("BAS-156 executable Web state tests did not pass")
    shots = {path: sha(path) for path in SCREENSHOTS}

    evidence = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "contract/no_data",
        "979 passed",
        "107 passed",
        "production composition root uses the disabled source",
        "1440/1440",
        "390/390/390",
        "external_write_allowed=false",
    ):
        if marker not in evidence:
            raise RuntimeError(f"BAS-156 Evidence marker missing: {marker}")

    common = {"state": "passed"}
    return {
        "tests": {
            **common,
            "summary": (
                f"{passed} focused tests executed by this verifier; "
                "authorized-source timeout/schema/revocation/replay/unknown "
                "outcome and adversarial Agent closure pass; separate "
                "current full gate is recorded in immutable Evidence"
            ),
            "input_sha256": _sha(
                [
                    sha("apps/control_plane/delivery_readback.py"),
                    sha("apps/control_plane/scoped_delivery_exceptions.py"),
                    sha("tests/test_delivery_readback.py"),
                    sha("tests/test_scoped_delivery_exceptions.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-156",
        },
        "database": {
            **common,
            "summary": "Alembic current/head single 0079; no 0080 required",
            "input_sha256": _sha(heads),
            "artifact_ref": "postgres:alembic_version",
        },
        "runtime": {
            **common,
            "summary": (
                "401/200/403 deterministic real no_data with zero upstream "
                "reads; production readback source remains disabled"
            ),
            "input_sha256": _sha(runtime),
            "artifact_ref": (
                "http://127.0.0.1:8000/v1/delivery-exceptions/workspace"
            ),
        },
        "web": {
            **common,
            "summary": (
                "107 executable Web tests plus desktop 1440 and mobile 390; "
                "error/retry/success and blocked/no_data/ready states pass "
                "with zero overflow and console errors"
            ),
            "input_sha256": _sha(
                [
                    hashlib.sha256(web_output.encode()).hexdigest(),
                    shots,
                ]
            ),
            "artifact_ref": SCREENSHOTS[1],
        },
        "evidence": {
            **common,
            "summary": f"BAS-156 Evidence SHA-256 {sha(EVIDENCE)}",
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
        result["tasks"] < 111
        or result["nodes"] < 233
        or result["edges"] < 229
    ):
        raise RuntimeError(f"BAS-156 Graph count drifted: {result}")
    print(
        json.dumps(
            {
                "project_id": kernel.PROJECT_ID,
                **result,
                "business_state": "no_data",
                "authorized_readback_source_bound": False,
                "external_write_allowed": False,
            },
            sort_keys=True,
        )
    )
