import json
from pathlib import Path


def test_loop_engineering_registry_covers_the_six_control_modules():
    path = Path(__file__).parents[1] / "docs" / "project" / "registries" / "loop_engineering_registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))

    modules = {module["id"]: module for module in registry["modules"]}
    assert set(modules) == {
        "automations",
        "skills",
        "integrations",
        "subagents",
        "worktrees",
        "memory",
    }
    for module in modules.values():
        assert module["state"] in {"partial", "design_only", "process_only", "ready"}
        assert module["required_controls"]
        assert module["promotion_gate"]
    assert len(registry["loop_contract"]) >= 6
