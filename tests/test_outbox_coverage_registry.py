import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "project" / "registries" / "outbox_coverage.json"
CONTROL_PLANE = ROOT / "apps" / "control_plane"


def test_outbox_coverage_registry_matches_direct_session_transactions():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entries = registry["modules"]
    registered = {entry["module"] for entry in entries}
    direct_transactions = {
        path.name
        for path in CONTROL_PLANE.glob("*.py")
        if "Session(" in (source := path.read_text(encoding="utf-8"))
        and "session.begin()" in source
    }

    assert registry["full_system_outbox"] is False
    assert len(registered) == len(entries)
    assert registered == direct_transactions

    allowed = set(registry["status_definitions"])
    for entry in entries:
        assert entry["status"] in allowed
        assert entry["delivery_contract"]
        assert entry["rationale"].strip()
        assert entry["activation_trigger"].strip()

    covered = {entry["module"] for entry in entries if entry["status"] == "covered"}
    assert {"automation.py", "governance.py"} <= covered

    closed_loop_entries = [
        entry for entry in entries if entry["module"] == "closed_loop_evolution.py"
    ]
    assert closed_loop_entries == [
        {
            "module": "closed_loop_evolution.py",
            "status": "internal_only",
            "delivery_contract": (
                "append_only_exact_scope_closed_loop_outcome_and_evidence_ledger"
            ),
            "rationale": (
                "闭环演化只在同一事务保存 exact-scope outcome root、supporting links、"
                "状态事件与受控 Evidence；V1 固定 causal=false、outbox=0、"
                "external_write=false，不创建 Approval、Permit 或任何平台、供应商、"
                "客户外部动作。"
            ),
            "activation_trigger": (
                "闭环 Observation 获准交付独立跨进程消费者或外部执行编排前"
            ),
        }
    ]
