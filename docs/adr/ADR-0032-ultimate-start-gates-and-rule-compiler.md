# ADR-0032: Ultimate Start Gates and effective rule compiler

Status: Accepted for Start-Gate review<br>
Date: 2026-07-27

## Decision

1. `GATE_PM_059` / `GATE_RA_059` remain Release Gates and may remain REJECTED
   until real Pilot and settlement evidence exists.
2. Independent Ultimate Start PM/RA Gates assess whether the Blueprint and
   Requirements Architecture are unambiguous and implementable. They do not
   require completed business outcomes.
3. Effective Rule Registry is the only rule truth source. Evaluators compile
   effective facts by `as_of`; code is a generic interpreter.
4. Missing domain/source Evidence is fail-closed for Pilot Approval and publish.
5. `approval_allocation_selected` is a budget slot only.

## Consequences

Ultimate execution can begin only after both Start Gates are APPROVED. A Start
approval never changes the Release Gate criteria, Ozon write authority, or
actual-profit semantics.

Normative sources:

- `docs/project/ULTIMATE_PRODUCT_BLUEPRINT.md`
- `docs/project/ULTIMATE_REQUIREMENTS_ARCHITECTURE.md`
