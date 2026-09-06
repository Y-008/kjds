# KJDS Drill-down and Replay Contract

| Field | Value |
|---|---|
| `doc_id` | `KJDS-DRILLDOWN-REPLAY-001` |
| `status` | `PROPOSED_FOR_IMPLEMENTATION` |
| `owner` | control-plane and web owners |
| `scope` | dashboards, natural-language BI, exports, Agent decisions and customer reports |

## 1. Standard path

```text
enterprise → entity → store → warehouse → category → price_band
→ SKU → Listing → campaign → order → fee/return → settlement
→ bank transaction → raw Evidence
```

The selected scope, period, currency, timezone, `as_of`, status and rule version remain active at every level. A drill-down is a read-only projection and does not create a second fact.

## 2. Transparency envelope

Every card and API response displays:

```text
status, as_of, fresh_until, source_count, excluded_count,
exclusion_reasons, quality, formula_version, rule_version,
authority_hash, lineage, next_action
```

The user can open the formula, included rows, excluded rows, source document, SHA-256, capture time and the exact calculation version.

## 3. Decision replay

An Agent decision stores:

```text
decision_id
input_snapshot_id
input_hash
evidence_refs
policy_hash
model_version
prompt_version
skill_version
output_hash
evaluation_ref
action_ref
readback_ref
```

Replay has two modes:

```text
historical_replay  what the system knew then
current_recompute  what the system would decide now
```

The result comparison identifies differences caused by data, rules, models or permissions.

## 4. Natural-language analytics

Natural-language requests compile to a read-only query plan containing scope, dimensions, metrics, filters, period, versions and expected row grain. The plan is validated against the metric catalog and access policy before execution. Arbitrary SQL, cross-tenant scope and hidden fields are rejected.

## 5. Evidence export

```text
query_plan.json
metric_definitions.json
scope.json
period.json
source_watermarks.json
included_rows.csv
excluded_rows.csv
lineage.json
result.json
checksums.txt
```

An exported package can be verified and replayed without relying on a mutable dashboard cache.

## 6. Acceptance

Acceptance requires six-level drill-down, preserved filters, formula/source visibility, historical/current replay, stable result hashes, export verification, no hidden cross-tenant fields and correct `no_data`, `partial`, `stale`, `blocked` and `unknown_outcome` rendering.
