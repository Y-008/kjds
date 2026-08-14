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
EVIDENCE = "docs/project/evidence/20260801_BAS_159_NATIVE_PARITY_ACCEPTANCE.md"
SCREENSHOTS = (
    "output/playwright/bas159-native-parity-desktop.png",
    "output/playwright/bas159-native-parity-mobile-390.png",
)
EXPECTED_SCREENSHOT_SHA256 = {
    SCREENSHOTS[0]: "71df5a6fba38c9badf9a3ec054dedd0a191163e6cb67073e29b1489e8cb9f2da",
    SCREENSHOTS[1]: "d47f4903555bc5d761348b25178110351fe8263508b24031648611b3f210d6ef",
}

TASKS = (
    ("task-bas159-pytest", "BAS-159 capability-granular acceptance authority", "tests", ("task-bas158-evidence",), "/engineering-graph"),
    ("task-bas159-database", "BAS-159 PostgreSQL head/current Graph-schema compatibility", "database", ("task-bas159-pytest",), "/runtime-graph"),
    ("task-bas159-runtime", "BAS-159 authenticated deterministic no-data runtime", "runtime", ("task-bas159-database",), "/runtime-graph"),
    ("task-bas159-web", "BAS-159 executable responsive acceptance workspace", "web", ("task-bas159-runtime",), "/native-parity"),
    ("task-bas159-evidence", "BAS-159 immutable acceptance Evidence", "evidence", ("task-bas159-web",), "/evidence-graph"),
)

NODES = (
    ("requirements", "requirement:BR-133@master-8.63", "requirement", "BR-133 capability-granular native-parity acceptance", "docs/project/MASTER_SPEC.md", "task-bas159-pytest"),
    ("requirements", "adr:ADR-0079", "adr", "ADR-0079 native-parity acceptance verifier", "docs/adr/ADR-0079-native-parity-acceptance-verifier.md", "task-bas159-pytest"),
    ("engineering", "service:native-parity-acceptance-v1", "service", "NativeParityAcceptanceWorkspace exact-scope v1", "apps/control_plane/native_parity_acceptance.py", "task-bas159-pytest"),
    ("engineering", "adapter:native-parity-graph-v1", "service", "Canonical SQL Graph acceptance adapter v1", "apps/control_plane/native_parity_graph.py", "task-bas159-database"),
    ("runtime", "api:native-parity-acceptance-no-data", "api_probe", "Authenticated deterministic native-parity no-data boundary", "http://127.0.0.1:8000/v1/native-parity-acceptance/workspace", "task-bas159-runtime"),
    ("runtime", "web:native-parity-acceptance-390", "browser_probe", "Native-parity acceptance desktop and 390px", SCREENSHOTS[1], "task-bas159-web"),
    ("evidence", "evidence:BAS-159", "evidence", "BAS-159 acceptance contract/no-data Evidence", EVIDENCE, "task-bas159-evidence"),
)

EDGES = (
    ("requirement:BR-133@master-8.63", "specified_by", "adr:ADR-0079", "requirements"),
    ("adr:ADR-0079", "implemented_by", "service:native-parity-acceptance-v1", "engineering"),
    ("service:native-parity-acceptance-v1", "reads_from", "adapter:native-parity-graph-v1", "engineering"),
    ("adapter:native-parity-graph-v1", "observed_as", "api:native-parity-acceptance-no-data", "runtime"),
    ("api:native-parity-acceptance-no-data", "rendered_by", "web:native-parity-acceptance-390", "runtime"),
    ("web:native-parity-acceptance-390", "recorded_in", "evidence:BAS-159", "evidence"),
)


def sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path = ROOT) -> str:
    result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout + result.stderr


def observations() -> dict[str, dict[str, str]]:
    focused_output = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_native_parity_acceptance.py",
            "tests/test_native_parity_graph.py",
            "tests/test_native_parity_acceptance_api.py",
            "tests/test_commerce_operating_system.py",
            "tests/test_api_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas159-graph-{os.getpid()}",
        ]
    )
    match = re.search(r"(\d+) passed", focused_output)
    if match is None:
        raise RuntimeError("BAS-159 focused tests did not pass")
    passed = int(match.group(1))
    full_output = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas159-graph-full-{os.getpid()}",
        ]
    )
    full_match = re.search(r"(\d+) passed", full_output)
    if full_match is None or int(full_match.group(1)) < 1147:
        raise RuntimeError("BAS-159 full backend gate did not pass")
    run([sys.executable, "scripts/verify_secrets.py"])
    run(["uv", "run", "ruff", "check", "apps", "tests", "scripts"])
    run(["git", "diff", "--check"])

    heads = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()
    if heads != ["20260731_0081"]:
        raise RuntimeError(f"BAS-159 Alembic head drifted: {heads}")
    current = run([sys.executable, "-m", "alembic", "current"]).strip()
    if "20260731_0081" not in current:
        raise RuntimeError(f"BAS-159 Alembic current drifted: {current}")

    runtime = json.loads(run([sys.executable, "scripts/verify_bas159_runtime.py"]).strip().splitlines()[-1])
    expected = {
        "anonymous": 401,
        "authenticated": 200,
        "forbidden": 403,
        "readiness": 200,
        "deterministic": True,
        "entity_ref": None,
        "status": "no_data",
        "items": 0,
        "verified_native": 0,
        "openapi_matches_snapshot": True,
    }
    if any(runtime.get(key) != value for key, value in expected.items()):
        raise RuntimeError("BAS-159 runtime truth boundary drifted")
    controls = runtime.get("control_envelope", {})
    if any(controls.get(key) is not False for key in (
        "approval_created",
        "business_fact_created",
        "client_can_recalculate_or_promote",
        "credential_created_or_read",
        "engineering_done_is_verified_native",
        "external_write_allowed",
        "mapping_is_implementation",
        "permit_created",
        "self_certification_allowed",
    )):
        raise RuntimeError("BAS-159 control envelope drifted")

    compose = [json.loads(line) for line in run(["docker", "compose", "ps", "--format", "json"]).splitlines() if line.strip()]
    healthy = {row["Service"] for row in compose if row.get("State") == "running" and row.get("Health") == "healthy"}
    if not {"api", "media-worker", "postgres", "web"} <= healthy:
        raise RuntimeError("BAS-159 containers are not healthy")

    web_output = run(["npm.cmd" if os.name == "nt" else "npm", "test"], cwd=ROOT / "web")
    if "fail 0" not in web_output or "pass 126" not in web_output:
        raise RuntimeError("BAS-159 executable Web tests did not pass")
    run(["npm.cmd" if os.name == "nt" else "npm", "run", "build", "--", "--webpack"], cwd=ROOT / "web")
    shots = {path: sha(path) for path in SCREENSHOTS}
    if shots != EXPECTED_SCREENSHOT_SHA256:
        raise RuntimeError("BAS-159 measured browser capture bytes drifted")

    evidence = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "contract/no_data",
        "1149 passed",
        "126 passed",
        "20260731_0081",
        "1440/1440",
        "390/390",
        "external_write_allowed=false",
        "0.59→M4",
    ):
        if marker not in evidence:
            raise RuntimeError(f"BAS-159 Evidence marker missing: {marker}")

    common = {"state": "passed"}
    return {
        "tests": {
            **common,
            "summary": f"{passed} focused and {full_match.group(1)} full backend tests plus secrets, Ruff and diff gates executed by this verifier",
            "input_sha256": _sha([
                sha("apps/control_plane/native_parity_acceptance.py"),
                sha("apps/control_plane/native_parity_graph.py"),
                sha("tests/test_native_parity_acceptance.py"),
                sha("tests/test_native_parity_graph.py"),
                sha("tests/test_native_parity_acceptance_api.py"),
                sha("tests/test_commerce_operating_system.py"),
            ]),
            "artifact_ref": "process:pytest BAS-159",
        },
        "database": {
            **common,
            "summary": "PostgreSQL Alembic current/head single 0081; existing canonical Graph/Harness schema is compatible and no migration was forced",
            "input_sha256": _sha([heads, current, sha("apps/control_plane/native_parity_graph.py")]),
            "artifact_ref": "postgres:alembic_version",
        },
        "runtime": {
            **common,
            "summary": "401/200/403 deterministic real no_data; verified_native remains zero and all mutation controls are false",
            "input_sha256": _sha(runtime),
            "artifact_ref": "http://127.0.0.1:8000/v1/native-parity-acceptance/workspace",
        },
        "web": {
            **common,
            "summary": "126 executable Web tests and production build pass; previously measured desktop/mobile capture bytes match immutable Evidence hashes",
            "input_sha256": _sha([
                sha("web/features/native-parity/native-parity-console.tsx"),
                sha("web/lib/native-parity-state.ts"),
                sha("web/lib/native-parity-state.test.ts"),
                shots,
            ]),
            "artifact_ref": SCREENSHOTS[1],
        },
        "evidence": {
            **common,
            "summary": f"BAS-159 Evidence SHA-256 {sha(EVIDENCE)}",
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
    print(json.dumps({"project_id": kernel.PROJECT_ID, **result, "business_state": "no_data", "verified_native": 0, "external_write_allowed": False}, sort_keys=True))
