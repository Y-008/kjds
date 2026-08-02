# ADR-0082: Scenario-aware evidence class policy

- Status: Accepted; implementation in progress
- Date: 2026-08-02
- Requirement: BR-082 / BR-084 / BAS-104
- Delivery: BAS-104
- Owners: Product, Compliance, Engineering

## Context

The batch-opportunity content gate required all three internal Passports
(product/compliance/quality) to be independently approved before a candidate
could become content-ready.  Operator architecture guidance points out that
the evidence layer is necessary in every scenario, but the "three Passports"
packaging is not: the necessity depends on how much automation or regulation
amplifies the cost of a wrong action.

1. A few ordinary SKUs listed manually: a database plus object storage with
   six basic evidence roles (supplier identity, purchase link, product
   certificate, SKU mapping, image source, basic QC result) is enough.
2. Daily automated screening/publishing of hundreds of SKUs: the structured
   evidence layer is the brake system and full Passports are required.
3. Branded, 3C, food, cosmetics, mother-and-baby and medical categories:
   certification, labelling and claims evidence is mandatory and strict.
4. EU-market exports: the EU Digital Product Passport (DPP) is a real
   regulatory direction, but the internal Passports are NOT the EU DPP and
   must never be presented as such.

## Decision

Introduce a deterministic evidence-class policy
(`kjds-evidence-class-policy-v1`, `apps/control_plane/evidence_class.py`)
with four classes: `manual_small`, `auto_scale`, `regulated`, `eu_export`.

- All classes require the same six basic evidence roles (evidence layer is
  never optional).
- `requires_full_passports` is only true for `auto_scale`, `regulated` and
  `eu_export`; `manual_small` gates on the six basic roles instead and keeps
  independent human approval for any publish.
- `regulated` additionally requires certification evidence; `eu_export`
  reserves a DPP-alignment seam (`dpp_mapping`) without conflating internal
  Passports with the EU DPP.
- Classification is deterministic and explicit: regulated category flags win,
  then EU target markets, then operation mode.  The batch pipeline is an
  automated scanner, so its inferred default is `auto_scale` (fail-closed);
  `manual_small` must be declared explicitly on the scan request
  (`BatchOpportunityPrepareInput.evidence_class`).
- No model judgement is involved anywhere in the classification.

The evidence layer itself is unchanged: the same immutable evidence records,
scope bindings and verification continue to back every role.

## Consequences

- Existing automated scans keep the strict Passport gate (no safety
  regression); a declared `manual_small` scan replaces the Passport blocker
  with a `basic_evidence_incomplete` blocker that names the missing roles.
- Candidates expose `evidence_class`, `passport_required` and per-role
  `basic_evidence_status` for the Web/reporting layer.
- A role with no data source is `False` (fail-closed); readiness is never
  guessed.
