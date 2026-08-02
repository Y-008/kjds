# ULTIMATE_EXECUTION_START

## Verdict

The root audit has approved both Ultimate start gates:

- PM Start Gate: `APPROVED`
- RA Start Gate: `APPROVED`

This evidence opens the Ultimate execution phase for implementation only. The allowed delivery scope is
`M0 → M4` implementation work. It is not a claim that the Ultimate product is complete.

Hard constraints remain in force:

- 0.59 PM/RA Release Gates remain `REJECTED`.
- Pilot and Final Gates are not passed.
- External writes to Ozon, suppliers, purchases, payments, and ads remain closed.
- Pricing remains `not_for_sale`.
- `Start-P0 = 0`.

## Repository baseline

- Branch: `feature/batch-opportunity-mining-059`
- Commit: `b34a3a711f6e5f8dff4e2a7bde876a2a3df8a00f`
- Recorded timestamp: `2026-07-27T09:32:18.3360126+08:00`

## Approved start-gate sources

- Product blueprint: [docs/project/ULTIMATE_PRODUCT_BLUEPRINT.md](../ULTIMATE_PRODUCT_BLUEPRINT.md)
- Requirements architecture: [docs/project/ULTIMATE_REQUIREMENTS_ARCHITECTURE.md](../ULTIMATE_REQUIREMENTS_ARCHITECTURE.md)
- PM Start Gate review: [docs/project/reviews/20260727_ULTIMATE_START_GATE_PM.md](../reviews/20260727_ULTIMATE_START_GATE_PM.md)
- RA Start Gate review: [docs/project/reviews/20260727_ULTIMATE_START_GATE_RA.md](../reviews/20260727_ULTIMATE_START_GATE_RA.md)
- 0.59 PM Release Gate: [docs/project/reviews/20260727_GATE_PM_059.md](../reviews/20260727_GATE_PM_059.md)
- 0.59 RA Release Gate: [docs/project/reviews/20260727_GATE_RA_059.md](../reviews/20260727_GATE_RA_059.md)
- Master spec backlink: [docs/project/MASTER_SPEC.md](../MASTER_SPEC.md)
- Remaining plan backlink: [docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md](../03_REMAINING_WORK_AND_PARALLEL_PLAN.md)

## M0 implementation contract

The first execution slice must be a dynamic, read-only Truth/Governance contract. It may not be a static
aggregation or empty shell. It must derive its values from existing authorities and expose at least:

- tenant / entity / store scope
- Identity / Evidence / Rule compiled hashes
- contribution-view availability and authority for the four contribution views
- Approval / Permit / Readback / Kill / Compensation status
- `external_writes = false`
- source gaps and blockers
- Owner / SLA / next

Required behavior for the first slice:

- anonymous requests return `401`
- unauthorized requests return `403`
- bad Evidence fails closed
- rule gaps and `no_data` remain visible as blockers
- `as_of` lookup is deterministic

This evidence intentionally documents the opening of implementation work only. It does not relax any later
Pilot, Final, approval, permit, readback, kill-switch, compensation, or external-write gates.
