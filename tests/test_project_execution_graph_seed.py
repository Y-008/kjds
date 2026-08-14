from copy import deepcopy

from scripts.seed_project_engineering_execution_graph import (
    AUTHORITY_INTAKE_ARTIFACT_ROOT,
    AUTHORITY_TOPOLOGY_ARTIFACT_ROOT,
    SCHEDULER_ARTIFACT_ROOT,
    SCHEDULER_RUNTIME_NODE_KEYS,
    _dependency_recovery_task_specs,
    _intake_task_specs,
    _node_specs,
    _scheduler_task_specs,
    _task_specs,
    _topology_task_specs,
    chain_observation_inputs,
    database_observation_input,
)


def _observations() -> dict[str, dict[str, str]]:
    return {
        verifier: {"input_sha256": verifier * 8}
        for _task, _title, verifier, _dependencies, _workspace in _task_specs()
    }


def _all_observations() -> dict[str, dict[str, str]]:
    observations = _observations()
    for specs in (
        _scheduler_task_specs(),
        _intake_task_specs(),
        _topology_task_specs(),
        _dependency_recovery_task_specs(),
    ):
        for (
            _task,
            _title,
            _verifier,
            observation_key,
            _dependencies,
            _workspace,
        ) in specs:
            observations[observation_key] = {
                "input_sha256": observation_key * 8
            }
    return observations


def test_chained_verifier_inputs_replay_and_propagate_upstream_changes() -> None:
    first = _observations()
    replay = deepcopy(first)
    chain_observation_inputs(first)
    chain_observation_inputs(replay)
    assert first == replay

    changed = _observations()
    changed["pytest"]["input_sha256"] = "changed-upstream"
    chain_observation_inputs(changed)
    assert {
        verifier
        for verifier in first
        if first[verifier]["input_sha256"]
        != changed[verifier]["input_sha256"]
    } == set(first)


def test_chained_verifier_inputs_preserve_unchanged_prefix() -> None:
    first = _observations()
    changed = _observations()
    changed["containers"]["input_sha256"] = "changed-container-image"
    chain_observation_inputs(first)
    chain_observation_inputs(changed)

    assert first["pytest"] == changed["pytest"]
    assert first["database"] == changed["database"]
    for verifier in ("containers", "api", "browser", "evidence"):
        assert first[verifier] != changed[verifier]


def test_dependency_dag_reverification_recovers_scheduler_intake_topology() -> None:
    first = _all_observations()
    changed = _all_observations()
    changed["pytest132"]["input_sha256"] = "changed-scheduler-tests"
    chain_observation_inputs(first)
    chain_observation_inputs(changed)

    for observation_key in (
        "pytest132",
        "scheduler",
        "pytest133",
        "intake",
        "tests134",
        "topology",
    ):
        assert first[observation_key] != changed[observation_key]


def test_topology_runtime_input_includes_both_independent_dependencies() -> None:
    first = _all_observations()
    intake_changed = _all_observations()
    tests_changed = _all_observations()
    intake_changed["intake"]["input_sha256"] = "changed-intake-runtime"
    tests_changed["tests134"]["input_sha256"] = "changed-topology-tests"
    chain_observation_inputs(first)
    chain_observation_inputs(intake_changed)
    chain_observation_inputs(tests_changed)

    assert first["topology"] != intake_changed["topology"]
    assert first["topology"] != tests_changed["topology"]


def test_database_observation_input_covers_result_affecting_binding_count() -> None:
    first = database_observation_input(
        revision="20260728_0070",
        binding_count=52,
    )
    replay = database_observation_input(
        revision="20260728_0070",
        binding_count=52,
    )
    changed = database_observation_input(
        revision="20260728_0070",
        binding_count=62,
    )

    assert first == replay
    assert first != changed


def test_scheduler_tasks_separate_engineering_proof_from_external_deployment() -> None:
    tasks = {
        task_id: {
            "verifier_id": verifier_id,
            "observation_key": observation_key,
            "dependencies": dependencies,
        }
        for (
            task_id,
            _title,
            verifier_id,
            observation_key,
            dependencies,
            _workspace,
        ) in _scheduler_task_specs()
    }
    assert tasks["task-bas132-verifier-tests"] == {
        "verifier_id": "bas132-pytest",
        "observation_key": "pytest132",
        "dependencies": (),
    }
    assert tasks["task-bas040-health-scheduler-deployment"] == {
        "verifier_id": "bas132-health-scheduler",
        "observation_key": "scheduler",
        "dependencies": ("task-bas132-verifier-tests",),
    }


def test_scheduler_nodes_keep_stable_artifact_root_across_observations() -> None:
    nodes = {
        stable_key: artifact
        for (
            _kind,
            stable_key,
            _node_type,
            _label,
            artifact,
            _task_id,
        ) in _node_specs(
            {
                "containers": {"artifact_ref": "docker-compose:kjds"},
                "scheduler": {
                    "artifact_ref": (
                        f"{SCHEDULER_ARTIFACT_ROOT}/content-hash.json"
                    )
                },
            }
        )
        if stable_key in SCHEDULER_RUNTIME_NODE_KEYS
    }
    assert nodes == {
        stable_key: SCHEDULER_ARTIFACT_ROOT
        for stable_key in SCHEDULER_RUNTIME_NODE_KEYS
    }


def test_authority_intake_tasks_separate_tests_from_live_observation() -> None:
    tasks = {
        task_id: {
            "verifier_id": verifier_id,
            "observation_key": observation_key,
            "dependencies": dependencies,
            "workspace": workspace,
        }
        for (
            task_id,
            _title,
            verifier_id,
            observation_key,
            dependencies,
            workspace,
        ) in _intake_task_specs()
    }
    assert tasks["task-bas133-verifier-tests"] == {
        "verifier_id": "bas133-pytest",
        "observation_key": "pytest133",
        "dependencies": ("task-bas132-verifier-tests",),
        "workspace": "/engineering-graph",
    }
    assert tasks["task-bas133-authority-intake-live"] == {
        "verifier_id": "bas133-authority-intake",
        "observation_key": "intake",
        "dependencies": ("task-bas133-verifier-tests",),
        "workspace": "/authority-intake",
    }


def test_authority_intake_observation_node_keeps_stable_artifact_root() -> None:
    nodes = {
        stable_key: artifact
        for (
            _kind,
            stable_key,
            _node_type,
            _label,
            artifact,
            _task_id,
        ) in _node_specs(
            {
                "containers": {"artifact_ref": "docker-compose:kjds"},
            }
        )
        if stable_key == "observation:bas133-authority-intake"
    }
    assert nodes == {
        "observation:bas133-authority-intake":
        AUTHORITY_INTAKE_ARTIFACT_ROOT
    }


def test_authority_topology_tasks_separate_code_proof_from_runtime_readiness() -> None:
    tasks = {
        task_id: {
            "verifier_id": verifier_id,
            "observation_key": observation_key,
            "dependencies": dependencies,
            "workspace": workspace,
        }
        for (
            task_id,
            _title,
            verifier_id,
            observation_key,
            dependencies,
            workspace,
        ) in _topology_task_specs()
    }
    assert tasks["task-bas134-verifier-tests"] == {
        "verifier_id": "bas134-tests",
        "observation_key": "tests134",
        "dependencies": ("task-bas133-verifier-tests",),
        "workspace": "/engineering-graph",
    }
    assert tasks["task-bas134-authority-workflow-topology"] == {
        "verifier_id": "bas134-authority-workflow-topology",
        "observation_key": "topology",
        "dependencies": (
            "task-bas133-authority-intake-live",
            "task-bas134-verifier-tests",
        ),
        "workspace": "/authority-intake",
    }


def test_authority_topology_observation_node_keeps_stable_artifact_root() -> None:
    nodes = {
        stable_key: artifact
        for (
            _kind,
            stable_key,
            _node_type,
            _label,
            artifact,
            _task_id,
        ) in _node_specs(
            {
                "containers": {"artifact_ref": "docker-compose:kjds"},
            }
        )
        if stable_key == "observation:bas134-authority-workflow-topology"
    }
    assert nodes == {
        "observation:bas134-authority-workflow-topology":
        AUTHORITY_TOPOLOGY_ARTIFACT_ROOT
    }


def test_dependency_recovery_task_and_nodes_are_verifier_owned() -> None:
    assert _dependency_recovery_task_specs() == (
        (
            "task-bas135-verifier-tests",
            "BAS-135 Graph dependency re-verification recovery",
            "bas135-tests",
            "pytest135",
            ("task-bas134-verifier-tests",),
            "/engineering-graph",
        ),
    )
    nodes = {
        stable_key: task_id
        for (
            _kind,
            stable_key,
            _node_type,
            _label,
            _artifact,
            task_id,
        ) in _node_specs(
            {
                "containers": {"artifact_ref": "docker-compose:kjds"},
            }
        )
        if stable_key in {
            "plan:BAS-135",
            "change:BAS-135",
            "code:graph-dependency-reverification",
            "test:graph-dependency-reverification",
            "evidence:BAS-135",
        }
    }
    assert set(nodes.values()) == {"task-bas135-verifier-tests"}
    assert len(nodes) == 5
