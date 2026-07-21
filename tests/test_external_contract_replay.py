import hashlib
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.image_execution import ComfyImageExecutionService
from apps.control_plane.imports import OzonImportService
from apps.control_plane.ozon_worker import OzonApiError, OzonCredentials, OzonSellerClient

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "external_contracts"


def _manifest():
    return json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


def _case(case_id: str):
    return next(case for case in _manifest()["cases"] if case["id"] == case_id)


def _fixture(case_id: str) -> bytes:
    case = _case(case_id)
    path = (FIXTURE_DIR / case["path"]).resolve()
    assert path.parent == FIXTURE_DIR.resolve()
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == case["sha256"]
    return content


def test_external_contract_manifest_is_complete_and_immutable():
    manifest = _manifest()
    cases = manifest["cases"]

    assert manifest["contains_sensitive_data"] is False
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["system"] for case in cases} == {
        "ozon_seller_api",
        "comfyui",
        "ozon_finance_export",
    }
    assert {case["expected_outcome"] for case in cases} == {"accepted", "schema_drift"}
    for case in cases:
        assert case["contract_version"]
        _fixture(case["id"])


@pytest.mark.parametrize(
    ("case_id", "expected_code"),
    [
        ("ozon.offer-state.success.v1", None),
        ("ozon.offer-state.schema-drift.v1", "OZON_SCHEMA_DRIFT"),
    ],
)
def test_ozon_offer_state_contract_replay(case_id, expected_code):
    replay = json.loads(_fixture(case_id))

    def handler(request: httpx.Request):
        return httpx.Response(200, json=replay["responses"][request.url.path])

    client = OzonSellerClient(
        OzonCredentials(client_id="fixture-client", api_key="fixture-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        if expected_code:
            with pytest.raises(OzonApiError) as caught:
                client.offer_state("fixture-offer-1")
            assert caught.value.code == expected_code
        else:
            result = client.offer_state("fixture-offer-1")
            assert result["contract_version"] == OzonSellerClient.PRODUCT_READ_CONTRACT_VERSION
            assert result["state"]["offer_id"] == "fixture-offer-1"
            assert len(result["state_hash"]) == 64
    finally:
        client.close()


@pytest.mark.parametrize(
    ("case_id", "accepted"),
    [
        ("comfy.history.success.v1", True),
        ("comfy.history.schema-drift.v1", False),
    ],
)
def test_comfy_history_contract_replay(case_id, accepted):
    replay = json.loads(_fixture(case_id))
    output = ComfyImageExecutionService._first_image(replay["prompt-fixture-1"]["outputs"])

    assert (output is not None) is accepted
    if accepted:
        assert output == {
            "filename": "fixture_00001_.png",
            "subfolder": "kjds/fixture",
            "type": "output",
        }


@pytest.mark.parametrize(
    ("case_id", "accepted"),
    [
        ("ozon.finance.success.v1", True),
        ("ozon.finance.schema-drift.v1", False),
    ],
)
def test_ozon_finance_contract_replay(case_id, accepted):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    preview = OzonImportService(engine).preview_file(
        filename="transactions.csv",
        content=_fixture(case_id),
    )

    assert preview.ready is accepted
    assert preview.record_type == "ozon_fee"
    if not accepted:
        assert {"currency", "effective_at"}.issubset(preview.missing_columns)
