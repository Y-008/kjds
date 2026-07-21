import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-24x7-health.ps1"
PWSH = shutil.which("pwsh")


class HealthHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, str | None]] = []
    invalid = 0

    def log_message(self, *_args):
        return

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.requests.append(("GET", self.path, self.headers.get("X-KJDS-API-Key")))
        if self.path == "/health/ready":
            self._json({"status": "ready"})
            return
        if self.path == "/v1/operations/readiness":
            self._json({"status": "ready"})
            return
        self.send_error(404)

    def do_POST(self):
        self.requests.append(("POST", self.path, self.headers.get("X-KJDS-API-Key")))
        parsed = urlparse(self.path)
        if parsed.path != "/v1/evidence/integrity-scan":
            self.send_error(404)
            return
        offset = int(parse_qs(parsed.query)["offset"][0])
        self._json(
            {
                "scanned": 1,
                "invalid": self.invalid if offset == 1 else 0,
                "incident_ids": {"evidence-1": "incident-1"} if self.invalid and offset == 1 else {},
                "scan_evidence_id": f"scan-{offset}",
                "next_offset": 1 if offset == 0 else None,
            }
        )


@pytest.fixture
def health_server():
    HealthHandler.requests = []
    HealthHandler.invalid = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def run_health(server, *, monitor_roles=("monitor",), invalid=0, reuse_operator=False):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the Windows health-loop contract")
    HealthHandler.invalid = invalid
    operator_key = "test-operator-key"
    monitor_key = operator_key if reuse_operator else "test-monitor-key"
    credentials = {
        operator_key: {"actor": "test-operator", "roles": ["operator"]},
        monitor_key: {"actor": "test-monitor", "roles": list(monitor_roles)},
    }
    env = os.environ.copy()
    env.update(
        {
            "KJDS_CONTROL_PLANE_URL": f"http://127.0.0.1:{server.server_port}",
            "KJDS_API_KEY": operator_key,
            "KJDS_MONITOR_API_KEY": monitor_key,
            "KJDS_API_KEYS_JSON": json.dumps(credentials),
            "KJDS_EXECUTOR_API_KEY": "test-executor-key",
            "KJDS_PILOT_READER_API_KEY": "test-pilot-reader-key",
            "OZON_API_KEY": "test-ozon-key",
            "KJDS_EVIDENCE_SCAN_PAGE_SIZE": "1",
            "KJDS_EVIDENCE_SCAN_MAX_PAGES": "5",
            "KJDS_HEALTH_REQUIRED": "true",
        }
    )
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(SCRIPT), "-ControlPlaneOnly"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return completed, json.loads(completed.stdout)


def test_health_loop_pages_with_dedicated_monitor_identity_and_sanitized_output(health_server):
    completed, payload = run_health(health_server)

    assert completed.returncode == 0
    assert payload["evidence_integrity"] == {
        "ok": True,
        "skipped": False,
        "error": None,
        "pages": 2,
        "scanned": 2,
        "invalid": 0,
        "incident_count": 0,
        "last_scan_evidence_id": "scan-1",
        "completed": True,
    }
    post_keys = [key for method, _, key in HealthHandler.requests if method == "POST"]
    assert post_keys == ["test-monitor-key", "test-monitor-key"]
    assert "test-monitor-key" not in completed.stdout
    assert "actual_sha256" not in completed.stdout
    assert "findings" not in completed.stdout


def test_health_loop_fails_closed_when_monitor_role_is_not_exclusive(health_server):
    completed, payload = run_health(health_server, monitor_roles=("monitor", "admin"))

    assert completed.returncode == 2
    assert payload["evidence_integrity"]["ok"] is False
    assert payload["evidence_integrity"]["pages"] == 0
    assert "exactly the monitor role" in payload["evidence_integrity"]["error"]
    assert not [request for request in HealthHandler.requests if request[0] == "POST"]


def test_health_loop_rejects_monitor_credential_reuse(health_server):
    completed, payload = run_health(health_server, reuse_operator=True)

    assert completed.returncode == 2
    assert payload["evidence_integrity"]["pages"] == 0
    assert "must not reuse" in payload["evidence_integrity"]["error"]
    assert not [request for request in HealthHandler.requests if request[0] == "POST"]


def test_health_loop_returns_nonzero_and_only_counts_when_integrity_finding_exists(health_server):
    completed, payload = run_health(health_server, invalid=1)

    assert completed.returncode == 2
    assert payload["evidence_integrity"]["invalid"] == 1
    assert payload["evidence_integrity"]["incident_count"] == 1
    assert payload["evidence_integrity"]["completed"] is True
    assert "evidence-1" not in completed.stdout
    assert "incident-1" not in completed.stdout
