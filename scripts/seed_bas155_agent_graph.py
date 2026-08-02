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
    "20260730_BAS_155_NATIVE_EXACT_SCOPE_GROWTH_EXPERIMENTS.md"
)
SCREENSHOTS = (
    "output/playwright/bas155-growth-experiments-desktop.png",
    "output/playwright/bas155-growth-experiments-mobile-390.png",
)

TASKS = (
    ("task-bas155-pytest", "BAS-155 exact-scope growth contracts", "tests",
     ("task-bas154-evidence",), "/engineering-graph"),
    ("task-bas155-database", "BAS-155 PostgreSQL single-head authority", "database",
     ("task-bas155-pytest",), "/runtime-graph"),
    ("task-bas155-runtime", "BAS-155 authenticated deterministic no-data runtime", "runtime",
     ("task-bas155-database",), "/runtime-graph"),
    ("task-bas155-web", "BAS-155 desktop and 390px growth workspace", "web",
     ("task-bas155-runtime",), "/growth-experiments"),
    ("task-bas155-evidence", "BAS-155 immutable engineering Evidence", "evidence",
     ("task-bas155-web",), "/evidence-graph"),
)
NODES = (
    ("requirements", "requirement:BR-129@master-8.60", "requirement",
     "BR-129 native exact-scope growth experiments",
     "docs/project/MASTER_SPEC.md", "task-bas155-pytest"),
    ("requirements", "adr:ADR-0075", "adr",
     "ADR-0075 native exact-scope growth experiment authority",
     "docs/adr/ADR-0075-native-exact-scope-growth-experiment-authority.md",
     "task-bas155-pytest"),
    ("engineering", "service:scoped-growth-experiment-v1", "service",
     "ScopedGrowthExperimentWorkspace exact-scope v1",
     "apps/control_plane/scoped_growth_experiments.py", "task-bas155-pytest"),
    ("engineering", "database:bas155-existing-authorities-0079", "database_probe",
     "BAS-155 composes existing authority at single 0079",
     "migrations/versions/20260730_0079_native_scoped_customer_service.py",
     "task-bas155-database"),
    ("runtime", "api:native-growth-experiment-no-data", "api_probe",
     "Authenticated growth experiment no-data boundary",
     "http://127.0.0.1:8000/v1/growth-experiments/workspace",
     "task-bas155-runtime"),
    ("runtime", "web:native-growth-experiment-390", "browser_probe",
     "Native growth experiment desktop and 390px",
     SCREENSHOTS[1], "task-bas155-web"),
    ("evidence", "evidence:BAS-155", "evidence",
     "BAS-155 native growth experiment Evidence",
     EVIDENCE, "task-bas155-evidence"),
)
EDGES = (
    ("requirement:BR-129@master-8.60", "specified_by", "adr:ADR-0075", "requirements"),
    ("adr:ADR-0075", "implemented_by", "service:scoped-growth-experiment-v1", "engineering"),
    ("service:scoped-growth-experiment-v1", "composes_at", "database:bas155-existing-authorities-0079", "engineering"),
    ("database:bas155-existing-authorities-0079", "observed_as", "api:native-growth-experiment-no-data", "runtime"),
    ("api:native-growth-experiment-no-data", "rendered_by", "web:native-growth-experiment-390", "runtime"),
    ("web:native-growth-experiment-390", "recorded_in", "evidence:BAS-155", "evidence"),
)


def sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        command, cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout + result.stderr


def observations() -> dict[str, dict[str, str]]:
    output = run([
        sys.executable, "-m", "pytest",
        "tests/test_scoped_growth_experiments.py",
        "tests/test_growth_composition_integration.py",
        "tests/test_api_contract.py",
        "-q", "-p", "no:cacheprovider",
        f"--basetemp=output/pytest/bas155-graph-{os.getpid()}",
    ])
    match = re.search(r"(\d+) passed", output)
    if match is None:
        raise RuntimeError("BAS-155 focused tests did not pass")
    passed = int(match.group(1))
    heads = ScriptDirectory.from_config(
        Config(str(ROOT / "alembic.ini"))
    ).get_heads()
    if heads != ["20260730_0079"]:
        raise RuntimeError(f"BAS-155 Alembic head drifted: {heads}")
    runtime = json.loads(
        run([sys.executable, "scripts/verify_bas155_runtime.py"])
        .strip().splitlines()[-1]
    )
    compose = [
        json.loads(line)
        for line in run(["docker", "compose", "ps", "--format", "json"])
        .splitlines() if line.strip()
    ]
    healthy = {
        row["Service"] for row in compose
        if row.get("State") == "running" and row.get("Health") == "healthy"
    }
    if not {"api", "media-worker", "postgres", "web"} <= healthy:
        raise RuntimeError("BAS-155 containers are not healthy")
    web_output = run(
        ["npm.cmd" if os.name == "nt" else "npm", "test"],
        cwd=ROOT / "web",
    )
    if "fail 0" not in web_output or "pass 107" not in web_output:
        raise RuntimeError("BAS-155 executable Web state tests did not pass")
    shots = {path: sha(path) for path in SCREENSHOTS}
    evidence = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING", "979 passed", "107 passed",
        "production composition-root",
        "canonical PIM empty",
        "1440/1440", "390/390", "external_write_allowed=false",
    ):
        if marker not in evidence:
            raise RuntimeError(f"BAS-155 Evidence marker missing: {marker}")
    common = {"state": "passed"}
    return {
        "tests": {**common, "summary": (
                      f"{passed} focused tests executed by this verifier; "
                      "real composition-root wiring and PIM empty/mixed/"
                      "pagination closure covered; separate current full "
                      "gate is recorded in immutable Evidence"
                  ),
                  "input_sha256": _sha([
                      sha("apps/control_plane/scoped_growth_experiments.py"),
                      sha("tests/test_scoped_growth_experiments.py"),
                      sha("tests/test_growth_composition_integration.py"),
                  ]),
                  "artifact_ref": "process:pytest BAS-155"},
        "database": {**common, "summary": "PostgreSQL current/head single 0079; no 0080 required",
                     "input_sha256": _sha(heads), "artifact_ref": "postgres:alembic_version"},
        "runtime": {**common, "summary": "401/200/403 deterministic real no_data; four containers healthy",
                    "input_sha256": _sha(runtime), "artifact_ref": "http://127.0.0.1:8000/v1/growth-experiments/workspace"},
        "web": {**common, "summary": (
                    "107 executable Web tests plus desktop 1440 and mobile "
                    "390; error/retry/success and blocked/no_data/ready "
                    "states pass with zero overflow and console errors"
                ),
                "input_sha256": _sha([
                    hashlib.sha256(web_output.encode()).hexdigest(), shots
                ]), "artifact_ref": SCREENSHOTS[1]},
        "evidence": {**common, "summary": f"BAS-155 Evidence SHA-256 {sha(EVIDENCE)}",
                     "input_sha256": sha(EVIDENCE), "artifact_ref": EVIDENCE},
    }


if __name__ == "__main__":
    kernel.EVIDENCE = EVIDENCE
    kernel.TASK_SPECS = TASKS
    kernel.NODE_SPECS = NODES
    kernel.EDGE_SPECS = EDGES
    kernel.upsert_graph(observations())
    result = kernel.counts()
    if result["tasks"] < 106 or result["nodes"] < 225 or result["edges"] < 222:
        raise RuntimeError(f"BAS-155 Graph count drifted: {result}")
    print(json.dumps({
        "project_id": kernel.PROJECT_ID, **result,
        "business_state": "no_data", "external_write_allowed": False,
    }, sort_keys=True))
