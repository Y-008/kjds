# ADR-0083: Lightweight SKU identity card and validation economics

- Status: Accepted; implementation in progress
- Date: 2026-08-02
- Requirement: BR-082 / BR-084 / BAS-104
- Delivery: BAS-104
- Owners: Product, Supply Chain, Engineering

## Context

The trial phase validates one specific chain: 1688 supply -> Ozon market ->
cost/profit matching.  The operator's guidance separates "trial-run
materials" from "scale-up governance materials": full three-Passport and
heavy media QA are scale-up gates, not prerequisites for validation.

Electric hoists are spec-sensitive: a 500kg purchase price must never be
matched against a 1000kg Ozon sale, single-rope and double-rope loads are
different products, and 220V/50Hz bare-machine offers differ from 380V or
set-inclusive offers.  The existing exact-identity key is too coarse when the
identity payload omits these dimensions.

## Decision

1. **Lightweight SKU identity card** (`kjds-sku-identity-card-v1`,
   `apps/control_plane/sku_identity_card.py`): a canonical 17-field card
   (SKU id, product type, rated/single/double-rope load, lift height/speed,
   voltage/frequency/power, wire rope spec, remote control type, machine
   weight, package dimensions, accessory list, supplier URL, main image).
   Core specs (product type, rated load, lift height, voltage, frequency,
   power) must agree between market and supply sides before a match is
   allowed; confirmed mismatches exclude the pair from matching (counted as
   `spec_mismatch_excluded`).  Unverifiable cards (empty core specs on both
   sides) stay compatible and are reported as gaps, never guessed.
2. **Validation economics** (`KEY_COST_COMPONENTS`): the trial phase only
   requires evidence for the nine high-impact components (procurement,
   domestic/international logistics, packaging, commission, FX/payment
   reserve, taxes, returns, loss/damage); the rest are policy-estimated and
   reported as an interval (`landed_cost_interval_cny`,
   `profit_interval_cny`, `estimated_component_names`).  Scale-up classes
   keep the full fifteen-component evidence gate.
3. **Six basic media checks**: image matches SKU, image params match specs,
   no external watermark/contact, no brand logo, no unsubstantiated claims,
   accessories in image are included.  Statuses are passed/failed/unknown
   from captured page data; a failed check is a media blocker in every class,
   unknown is a reported gap.  Heavy multi-model media QA is deferred to the
   scale-up phase.

The trial phase therefore runs: real pages -> SKU identity match -> cost
interval -> market profit validation, without being blocked on complete
Passports or all fifteen cost evidence items.

## Consequences

- Core-spec conflicts can no longer produce a candidate silently; they are
  excluded and counted.
- Candidates expose `sku_identity_card`, `basic_media_checks` and the cost
  intervals for the Web/reporting layer.
- `pilot_ready` and any publish still require the full scale-up gates;
  validation mode only relaxes the trial-stage material requirements.
