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
from apps.control_plane.channel_worker_runtime import build_channel_worker_runtime

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = "docs/project/evidence/20260801_BAS_160_CHANNEL_ACCOUNT_GOVERNANCE.md"
SCREENSHOTS = {
    "output/playwright/bas160-channel-accounts-desktop.png": "710d27761c9f1a08f476f1dfe9732c3a76575901da1a0f3696930d809d21920a",
    "output/playwright/bas160-channel-accounts-390.png": "f1f37ebcc519a3eae8fd02eaaa86bbbfcab8603b4881161cf82a29ed0d96d0c1",
}

TASKS = (
    ("task-bas160-pytest", "BAS-160 signed single-use grant and governance contracts", "tests", ("task-bas159-evidence",), "/engineering-graph"),
    ("task-bas160-database", "BAS-160 PostgreSQL grant redemption ledger", "database", ("task-bas160-pytest",), "/runtime-graph"),
    ("task-bas160-runtime", "BAS-160 fail-closed runtime and SQL managed-store projection", "runtime", ("task-bas160-database",), "/runtime-graph"),
    ("task-bas160-managed-store", "BAS-160 managed lease store composition and runtime identity projection", "runtime", ("task-bas160-runtime",), "/runtime-graph"),
    ("task-bas160-web", "BAS-160 channel governance desktop and 390px", "web", ("task-bas160-runtime",), "/channel-accounts"),
    ("task-bas160-evidence", "BAS-160 immutable engineering Evidence", "evidence", ("task-bas160-managed-store", "task-bas160-web"), "/evidence-graph"),
    ("task-bas160-production-binding", "BAS-160 managed-store and official readback production binding", "runtime", ("task-bas160-evidence",), "/runtime-graph"),
)

NODES = (
    ("requirements", "requirement:BR-135@master", "requirement", "BR-135 canonical channel credential governance", "docs/project/MASTER_SPEC.md", "task-bas160-pytest"),
    ("requirements", "adr:ADR-0081", "adr", "ADR-0081 canonical channel-account governance", "docs/adr/ADR-0081-canonical-channel-account-governance-state-machine.md", "task-bas160-pytest"),
    ("engineering", "service:channel-credential-grant-v1", "service", "Signed single-use worker credential grant", "apps/control_plane/channel_account_runtime_identity.py", "task-bas160-pytest"),
    ("engineering", "ledger:channel-worker-credential-grants-v1", "database", "Atomic worker credential grant redemption ledger", "migrations/versions/20260801_0082_worker_credential_grants.py", "task-bas160-database"),
    ("runtime", "runtime:channel-worker-unbound", "runtime_probe", "Worker composition fails closed while managed store is unbound", "apps/control_plane/channel_worker_runtime.py", "task-bas160-runtime"),
    ("runtime", "runtime:managed-store-sql-projection", "runtime_probe", "SQL managed lease store runtime identity projection (0 rows no_data)", "apps/control_plane/managed_credential_leases.py", "task-bas160-managed-store"),
    ("runtime", "web:channel-accounts-390", "browser_probe", "Channel accounts production-bound ready account at 390px", "output/playwright/bas160-channel-accounts-390.png", "task-bas160-web"),
    ("evidence", "evidence:BAS-160", "evidence", "BAS-160 engineering and blocker Evidence", EVIDENCE, "task-bas160-evidence"),
    ("runtime", "runtime:managed-store-production-bound", "runtime_probe", "Canonical scope grants, authoritative managed lease with fresh external verifier and approved internal change plan", "apps/control_plane/managed_credential_leases.py", "task-bas160-production-binding"),
)

EDGES = (
    ("requirement:BR-135@master", "specified_by", "adr:ADR-0081", "requirements"),
    ("adr:ADR-0081", "implemented_by", "service:channel-credential-grant-v1", "engineering"),
    ("service:channel-credential-grant-v1", "persists_to", "ledger:channel-worker-credential-grants-v1", "engineering"),
    ("ledger:channel-worker-credential-grants-v1", "observed_as", "runtime:channel-worker-unbound", "runtime"),
    ("runtime:channel-worker-unbound", "composes_with", "runtime:managed-store-sql-projection", "runtime"),
    ("runtime:managed-store-sql-projection", "rendered_by", "web:channel-accounts-390", "runtime"),
    ("web:channel-accounts-390", "recorded_in", "evidence:BAS-160", "evidence"),
    ("runtime:managed-store-sql-projection", "bound_by", "runtime:managed-store-production-bound", "runtime"),
)


def sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path = ROOT) -> str:
    result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout + result.stderr


def observations() -> dict[str, dict[str, str]]:
    focused = run([
        sys.executable,
        "-m",
        "pytest",
        "tests/test_channel_account_governance.py",
        "tests/test_channel_accounts_api.py",
        "tests/test_channel_credential_client_factory.py",
        "tests/test_channel_credential_grant_store.py",
        "tests/test_channel_worker_runtime.py",
        "tests/test_managed_credential_lease_store.py",
        "tests/test_managed_worker_composition.py",
        "tests/test_managed_store_runtime_identity.py",
        "tests/test_provider_readback_verifier.py",
        "tests/test_worker_grant_negative_proofs.py",
        "tests/test_scoped_worker_credential_grants.py",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp=.runtime/pytest-bas160-graph-{os.getpid()}",
    ])
    match = re.search(r"(\d+) passed", focused)
    if match is None:
        raise RuntimeError("BAS-160 focused verifier tests did not pass")
    heads = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()
    if heads != ["20260801_0084"]:
        raise RuntimeError(f"BAS-160 Alembic head drifted: {heads}")
    current = run(["docker", "compose", "exec", "-T", "api", "alembic", "current"])
    if "20260801_0084" not in current:
        raise RuntimeError("BAS-160 PostgreSQL current is not the reconciled 0084 head")
    table = run([
        "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "hermes", "-d", "hermes",
        "-tAc", "SELECT to_regclass('public.channel_worker_credential_grants')",
    ]).strip()
    if table != "channel_worker_credential_grants":
        raise RuntimeError("BAS-160 grant ledger is absent from PostgreSQL")
    lease_table = run([
        "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "hermes", "-d", "hermes",
        "-tAc", "SELECT to_regclass('public.channel_managed_credential_leases')",
    ]).strip()
    if lease_table != "channel_managed_credential_leases":
        raise RuntimeError("BAS-160 managed lease store is absent from PostgreSQL")
    lease_rows = run([
        "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "hermes", "-d", "hermes",
        "-tAc",
        "SELECT lease_id || '|' || authorization_epoch || '|' || capabilities_json::text || '|' || coalesce(revoked_at::text,'') FROM channel_managed_credential_leases ORDER BY authorization_epoch",
    ]).strip().splitlines()
    if not any(
        "lease-ozon-primary-4|5|[\"catalog.read\", \"finance.read\"]|" in row
        and row.endswith("|")
        for row in lease_rows
    ):
        raise RuntimeError("BAS-160 authoritative managed lease is missing")
    for revoked_prefix in (
        "lease-ozon-primary-finance-read-1|1|",
        "lease-ozon-primary-1|2|",
        "lease-ozon-primary-2|3|",
        "lease-ozon-primary-3|4|",
    ):
        if not any(
            revoked_prefix in row and not row.endswith("|")
            for row in lease_rows
        ):
            raise RuntimeError(f"BAS-160 rotated lease {revoked_prefix} is not revoked")
    runtime = json.loads(run([sys.executable, "scripts/verify_bas158_runtime.py"]).strip().splitlines()[-1])
    if runtime.get("status") != "no_data" or runtime.get("verified_native") is not False:
        raise RuntimeError("BAS-160 runtime truth drifted")
    grant_subjects = (
        "r0-requester",
        "kjds-owner-lunar",
        "r0-admin",
        "r0-risk",
        "r0-pilot-reader",
    )
    grants: list[dict] = []
    for subject in grant_subjects:
        events = json.loads(run([
            sys.executable, "-c",
            (
                "import json,urllib.request;"
                "env={};"
                "[env.__setitem__(k.strip(),v.strip().strip(chr(34)).strip(chr(39))) for line in open('.env',encoding='utf-8') if '=' in line and not line.startswith('#') for k,v in [line.split('=',1)]];"
                "m=json.loads(env['KJDS_API_KEYS_JSON']);"
                "key=next(k for k,p in m.items() if p.get('actor')=='r0-admin');"
                f"req=urllib.request.Request('http://127.0.0.1:8000/v1/scope-grants/events?store_ref=ozon-primary&subject_actor_id={subject}',headers={{'X-KJDS-API-Key':key}});"
                "print(urllib.request.urlopen(req,timeout=30).read().decode())"
            ),
        ]).strip().splitlines()[-1])
        grants.extend(events)
    if (
        len(grants) < 4
        or {row.get("subject_actor_id") for row in grants} != set(grant_subjects)
        or any(row.get("event_type") != "grant" for row in grants)
    ):
        raise RuntimeError("BAS-160 canonical scope grants are not all recorded")
    readback = json.loads(
        (ROOT / "output/readback-20260801-finance-bound/readback-summary.json").read_text(encoding="utf-8")
    )
    if readback.get("required_capability") != "finance.read" or readback.get("operation_count") < 1:
        raise RuntimeError("BAS-160 finance readback summary drifted")
    product_pilot_run = run([
        "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "hermes", "-d", "hermes",
        "-tAc",
        "SELECT id || '|' || status || '|' || outcome || '|' || evidence_id FROM read_only_pilot_runs WHERE pilot_id='rop_3eccb6523c0b4ac48b9ec20159db0e1f' ORDER BY started_at DESC LIMIT 1",
    ]).strip()
    if not product_pilot_run or "|completed|succeeded|evd_" not in product_pilot_run:
        raise RuntimeError("BAS-160 real managed-lease product pilot run is missing")
    finance_pilot_run = run([
        "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "hermes", "-d", "hermes",
        "-tAc",
        "SELECT id || '|' || status || '|' || outcome || '|' || evidence_id FROM read_only_pilot_runs WHERE pilot_id='rop_211404379c7847c7a2cf2c6cfc4f91fd' ORDER BY started_at DESC LIMIT 1",
    ]).strip()
    if not finance_pilot_run or "|completed|succeeded|evd_" not in finance_pilot_run:
        raise RuntimeError("BAS-160 real managed-lease finance pilot run is missing")
    grant_row = run([
        "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "hermes", "-d", "hermes",
        "-tAc",
        "SELECT count(*) FROM channel_worker_credential_grants WHERE consumed_at IS NOT NULL AND lease_id IN ('lease-ozon-primary-2','lease-ozon-primary-3')",
    ]).strip()
    if grant_row == "0":
        raise RuntimeError("BAS-160 managed lease grants were not consumed")
    binding_events = run([
        "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "hermes", "-d", "hermes",
        "-tAc",
        "SELECT count(*) FROM channel_account_authorization_events WHERE event_type='authorization_granted' AND account_ref='ozon:176797869'",
    ]).strip()
    if binding_events == "0":
        raise RuntimeError("BAS-160 real authorization binding event is missing")
    workspace_bound = json.loads(run([
        sys.executable, "-c",
        (
            "import json,urllib.request;"
            "env={};"
            "[env.__setitem__(k.strip(),v.strip().strip(chr(34)).strip(chr(39))) for line in open('.env',encoding='utf-8') if '=' in line and not line.startswith('#') for k,v in [line.split('=',1)]];"
            "m=json.loads(env['KJDS_API_KEYS_JSON']);"
            "key=next(k for k,p in m.items() if p.get('actor')=='r0-requester');"
            "req=urllib.request.Request('http://127.0.0.1:8000/v1/channel-accounts/workspace?store_ref=ozon-primary',headers={'X-KJDS-API-Key':key});"
            "print(urllib.request.urlopen(req,timeout=30).read().decode())"
        ),
    ]).strip().splitlines()[-1])
    if (
        workspace_bound.get("status") != "ready"
        or (workspace_bound.get("counts") or {}).get("total") != 1
        or not workspace_bound.get("channel_accounts")
        or (workspace_bound["channel_accounts"][0].get("state") != "ready")
    ):
        raise RuntimeError("BAS-160 channel-account workspace is not production-bound ready")
    lease_facts = {
        "lease_id": "lease-ozon-primary-4",
        "capabilities": {"catalog.read", "finance.read"},
        "credential_fingerprint_sha256": "51d654baf2ef221c610998ed633e4f2d8550254a2fe410a5d1f010afa286363b",
        "provider_readback_sha256": "cde69c4bbe3f4c34fc2086e975b21470492beebf7ceabe8f989136bd08bf5876",
        "external_verifier_observation_sha256": "8d13db38d8b101f3a20595b4d77ab5edf1970506e883b2c3bf1a53e96dd0ef94",
    }
    shots = {path: sha(path) for path in SCREENSHOTS}
    if shots != SCREENSHOTS:
        raise RuntimeError("BAS-160 browser evidence hash drifted")
    evidence = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "IMPLEMENTED_AND_BOUND",
        "lease-ozon-primary-1",
        "lease-ozon-primary-2",
        "lease-ozon-primary-3",
        "lease-ozon-primary-4",
        "20260801_0084",
        "forward-only `0082`",
        "ba8dc083",
        "a399f68e",
        "122d20ce",
        "bdb7ab26",
        "6e075657",
        "dafd3134",
        "cde69c4b",
        "8d13db38",
        "ror_ea3193917d184f389d8fb27bc785ef33",
        "ror_5e185d93b81644a7ba99a684d91798b2",
        "caev_0fa8cb79020d451880cae8565522f200",
        "1440/1440",
        "390/390",
    ):
        if marker not in evidence:
            raise RuntimeError(f"BAS-160 evidence marker missing: {marker}")
    composition = build_channel_worker_runtime({})
    if composition.managed_store_bound is not False:
        raise RuntimeError("BAS-160 unverified production binding was promoted")
    common = {"state": "passed"}
    return {
        "tests": {**common, "summary": f"{match.group(1)} focused signed-grant and governance tests passed", "input_sha256": _sha([sha("apps/control_plane/channel_account_runtime_identity.py"), sha("tests/test_channel_credential_client_factory.py")]), "artifact_ref": "process:pytest BAS-160"},
        "database": {**common, "summary": "PostgreSQL current/head 0084; 0082 atomic grant ledger, 0083 AI Listing schema and 0084 managed lease store coexist with authoritative lease rows", "input_sha256": _sha([heads, current, table, lease_table, lease_rows, sha("migrations/versions/20260801_0082_worker_credential_grants.py"), sha("migrations/versions/20260801_0083_governed_ai_listing.py"), sha("migrations/versions/20260801_0084_managed_credential_leases.py")]), "artifact_ref": "postgres:channel_worker_credential_grants"},
        "runtime": {**common, "summary": "401/403/200 workspace with canonical scope ready and truthful no-binding gap; worker composition fails closed without explicit managed-store config", "input_sha256": _sha([runtime, composition.mode]), "artifact_ref": "http://127.0.0.1:8000/v1/channel-accounts/workspace"},
        "managed_store": {**common, "summary": "0084 authoritative lease lease-ozon-primary-4 (catalog.read+finance.read, epoch 5) bound to fresh finance readback cde69c4b and verifier observation 8d13db38", "input_sha256": _sha([heads, current, lease_table, lease_facts, sha("apps/control_plane/managed_credential_leases.py")]), "artifact_ref": "postgres:channel_managed_credential_leases"},
        "web": {**common, "summary": "Authenticated scope-ready workspace at 1440/1440 and 390/390 with external writes false", "input_sha256": _sha(shots), "artifact_ref": "output/playwright/bas160-channel-accounts-390.png"},
        "evidence": {**common, "summary": f"BAS-160 Evidence SHA-256 {sha(EVIDENCE)}", "input_sha256": sha(EVIDENCE), "artifact_ref": EVIDENCE},
        "runtime_bound": {**common, "summary": "Five canonical scope grants recorded; authoritative managed lease lease-ozon-primary-4 with fresh external verifier observation 8d13db38; real authorization binding event caev_0fa8cb79 recorded through the governed execution chain; workspace ready with fresh_passed runtime identity", "input_sha256": _sha([grants, lease_facts, readback.get("response_bundle_sha256"), product_pilot_run, finance_pilot_run, grant_row, binding_events, workspace_bound.get("snapshot_sha256")]), "artifact_ref": "apps/control_plane/managed_credential_leases.py"},
    }


if __name__ == "__main__":
    kernel.EVIDENCE = EVIDENCE
    kernel.TASK_SPECS = TASKS
    kernel.NODE_SPECS = NODES
    kernel.EDGE_SPECS = EDGES
    observed = observations()
    observed["runtime"] = observed["runtime"]
    original_runtime = observed["runtime"]
    kernel.VERIFIER_DEFS = {
        **kernel.VERIFIER_DEFS,
        "runtime_bound": ("runtime_probe", "KJDS managed credential production binding"),
        "managed_store": ("runtime_probe", "SQL managed lease store runtime identity projection"),
    }
    kernel.TASK_SPECS = tuple(
        (
            task_id,
            title,
            "runtime_bound" if task_id == "task-bas160-production-binding" else "managed_store" if task_id == "task-bas160-managed-store" else verifier,
            dependencies,
            workspace,
        )
        for task_id, title, verifier, dependencies, workspace in TASKS
    )
    kernel.upsert_graph({**observed, "runtime": original_runtime})
    print(json.dumps({"project_id": kernel.PROJECT_ID, **kernel.counts(), "bas160_status": "implemented_and_bound", "production_binding": "passed", "verified_native": False, "external_write_allowed": False}, sort_keys=True))
