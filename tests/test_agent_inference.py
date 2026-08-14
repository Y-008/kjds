from __future__ import annotations

from apps.control_plane.agent_inference import _effective_prompt


def test_effective_prompt_appends_exact_evidence_ids() -> None:
    contract = {"prompt": "Normalize only what is explicitly present."}
    result = _effective_prompt(contract, ("evd-one", "evd-two"))
    assert result.startswith("Normalize only what is explicitly present.")
    assert "evd-one" in result
    assert "evd-two" in result
    assert "field_evidence" in result


def test_effective_prompt_is_identity_without_evidence_ids() -> None:
    contract = {"prompt": "Base prompt."}
    assert _effective_prompt(contract, ()) == "Base prompt."


def test_effective_prompt_deduplicates_and_sorts_evidence_ids() -> None:
    contract = {"prompt": "P."}
    result = _effective_prompt(contract, ("evd-b", "evd-a", "evd-b"))
    assert result.index("evd-a") < result.index("evd-b")
    assert result.count("evd-b") == 1
