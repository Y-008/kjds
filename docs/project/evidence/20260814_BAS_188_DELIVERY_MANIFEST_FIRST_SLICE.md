# BAS-188 Governed DeliveryManifest Assembly Evidence (First Slice)

## Scope and result

- Task: `BAS-188`
- Deep module: `GovernedDeliveryManifestWorkspace.assemble(scope, as_of, artifact_refs, delivery_target, idempotency_key)`
- Result type: immutable, content-addressed `DeliveryManifestOutcome`
- Public API, router, runtime wiring, migration, OpenAPI and dependency changes: none
- Social publish, campaign grant, readback, revoke and kill-switch: `not_admitted` (BAS-178)

This first slice assembles already-admitted media artifacts (image, video,
editing blueprint, tutorial) into a frozen, deterministic DeliveryManifest for
a social delivery target. It does not create a second ContentAsset, Evidence,
Job, EditingBlueprint or TutorialGraph truth, and performs zero external writes.

## Reused truth boundaries

| Artifact kind | Reused contract | Eligible use |
| --- | --- | --- |
| image | `kjds-media-job-artifact-reference-v1` | width/height metadata only |
| video | `kjds-media-job-artifact-reference-v1` | width/height/duration/encoder seal |
| editing blueprint | `kjds-editing-blueprint-v1` | schema_version + source asset refs |
| tutorial | `kjds-tutorial-graph-v1` | tutorial graph version + capture manifest |
| per-asset manifest | `kjds-media-delivery-manifest-v1` | referenced, never re-derived |

Every artifact freezes its contract id/version, artifact ref, SHA-256,
kind-specific metadata and dependency refs. The whole manifest binds one exact
tenant/entity/store scope and one data `as_of`.

## Admission model

- Only `image`, `video`, `editing_blueprint`, `tutorial` kinds are admitted.
- Each kind requires its declared metadata keys; missing keys block the manifest.
- Duplicate artifact refs, unknown/self/cyclic dependencies block the manifest.
- Sensitive values (credential field names, bearer tokens, cookies, private keys)
  are rejected before hashing.
- Artifacts execute in deterministic topological order; identical scope/as_of/
  idempotency/artifact bytes replay byte-equivalently.
- The social delivery target is `not_admitted`: publish/campaign grant/readback/
  revoke/kill-switch remain zero-authority and `external_write_allowed=false`.

## Preserved uncertainty states

`COMPILED`, `PROPOSAL_ONLY`, `BLOCKED`, `INVALIDATED`, `STALE` remain distinct.
This slice can only return `PROPOSAL_ONLY` (social target not admitted) or
`INVALIDATED`/`STALE` after explicit revocation/staleness. It never promotes a
manifest to listing eligibility or external execution.

## Zero-authority conservation

Every outcome preserves literal `false` for: Fact, FinanceEntry, Approval,
Permit, Pilot, Outbox, canonical Graph write, dependency install, network and
external write.

## Verification record

Working directory: `D:\KJDS\kjds`

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_delivery_manifest.py --basetemp D:\KJDS\pytest-bas188
.................... [100%]
20 passed in 0.11s

.\.venv\Scripts\ruff.exe check --no-cache apps/control_plane/delivery_manifest.py tests/test_delivery_manifest.py
All checks passed!
```

Covered negative contracts include duplicate/unknown/self/cyclic artifact refs,
missing kind metadata, sensitive scope/artifact payloads, malformed SHA-256,
scope key drift, dependency ordering determinism, scope/idempotency drift,
readback verify/invalidate, explicit invalidation and staleness, and the
social delivery target remaining `not_admitted`.

## Artifact hashes

- module: `apps/control_plane/delivery_manifest.py`
- contract: `docs/project/registries/delivery_manifest_contracts.json`
- tests: `tests/test_delivery_manifest.py`

## UNKNOWN retained

- real social platform account binding and campaign authority (BAS-178);
- production publish/readback/revoke/kill-switch semantics;
- real tenant/store media artifact inventory and delivery scheduling;
- platform-specific media constraints (format, duration, aspect, captions).

No production delivery or external execution is implied by this first slice.
