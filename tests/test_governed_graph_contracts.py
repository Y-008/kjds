import pytest

from apps.control_plane.governed_graph_contracts import (
    EconomicState,
    EvidenceState,
    GovernedGraphNode,
    GraphNodeKind,
    OperationalState,
    ProofState,
)


def test_graph_node_requires_all_independent_refs_before_live_admission():
    node = GovernedGraphNode(
        node_id="price-rule-1",
        kind=GraphNodeKind.BUSINESS,
        label="automatic repricing",
        proof_state=ProofState.PROVED,
        evidence_state=EvidenceState.VALID,
        operational_state=OperationalState.LIVE,
        economic_state=EconomicState.ALLOWED,
        rollback_available=True,
        proof_refs=("proof-1",),
        evidence_refs=("readback-1",),
    )
    assert node.admission_state == "LIVE"


def test_unknown_external_outcome_cannot_become_live():
    node = GovernedGraphNode(
        node_id="price-rule-1",
        kind="economic_guard",
        label="repricing guard",
        proof_state="PROVED",
        evidence_state="UNKNOWN_OUTCOME",
        operational_state="LIVE",
        economic_state="ALLOWED",
        rollback_available=True,
        proof_refs=("proof-1",),
        evidence_refs=("attempt-1",),
    )
    assert node.admission_state == "UNKNOWN_OUTCOME"


def test_proved_or_valid_states_require_references():
    with pytest.raises(ValueError, match="proof_refs"):
        GovernedGraphNode(
            node_id="n1",
            kind="theorem",
            label="missing evidence",
            proof_state="PROVED",
        )
