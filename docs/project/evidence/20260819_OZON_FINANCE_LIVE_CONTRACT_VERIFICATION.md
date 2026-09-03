# 20260819 Ozon Finance Live Contract Verification

## Scope

- Requirement: BR-040
- Operation: `ozon.finance.read`
- Endpoint candidate fixed by the existing Pilot contract: `POST /v3/finance/transaction/list`
- Frontier review: not_required
- External write: false
- Formal finance promotion: false

## Admission decision

The repository does not currently contain a current official response admission that proves
`operation_id`, `amount`, `posting`, `items`, `services`, or their nested fields are mandatory for
every successful operation row. The live contract therefore validates only the admitted response
envelope:

- top-level JSON object;
- `result` object;
- `result.operations` list;
- every operations entry is an object;
- optional non-negative integer `result.page_count`.

Observed operation field names remain `unverified_observation_only`. They are not formal facts,
accounting mappings, reconciliation keys, or proof that the endpoint is currently enabled for a
real account.

## Readback integrity implemented

The finance response Evidence bundle now contains a non-secret request context with:

- operation;
- query-window SHA-256;
- page;
- page size.

The independent verifier checks:

- bundle SHA-256 and exact byte size;
- bundle and body object shapes;
- response body SHA-256;
- fixed contract/path and successful HTTP status;
- operation count and page count against the summary;
- operation, query hash, page and page size against the frozen request context;
- malformed scalar/list bundles return `READBACK_BUNDLE_CONTRACT_INVALID` rather than raising an
  unclassified exception.

## Verification

```text
uv run ruff check apps/control_plane/ozon_live_contracts.py \
  apps/control_plane/ozon_worker.py \
  apps/control_plane/provider_readback_verifier.py \
  tests/test_ozon_live_contracts.py \
  tests/test_ozon_worker.py \
  tests/test_provider_readback_verifier.py

All checks passed!

uv run pytest -q tests/test_ozon_live_contracts.py \
  tests/test_ozon_worker.py \
  tests/test_provider_readback_verifier.py

112 passed in 0.79s
```

## Remaining blocker

A current official response sample, captured through the approved read-only identity and stored as
immutable Evidence, is still required before versioning any operation-level field as mandatory.
This engineering result does not prove official Key readiness, live finance access, real orders,
settlement, bank cash, or accounting correctness.
