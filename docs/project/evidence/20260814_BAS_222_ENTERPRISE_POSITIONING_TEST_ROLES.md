# BAS-222 Enterprise Positioning Contract, Absorbed by BAS-223

## Supersession

BAS-222 was not submitted as a standalone feature or release. BR-149 and
BAS-223 supersede the earlier BR-148 role experiment and absorb the positioning
contract into one integrated API, OpenAPI, Web, and board-operating slice. The
earlier identity-like role vocabulary, snapshot, and test receipt are not
current Evidence and must not be used as a Gate.

## Current contract

`EnterprisePositioningAdvisor.position(profile)` remains the single deep
Interface. It deterministically projects 35 authority-free capability
templates from the versioned eight-dimension enterprise profile. It reuses the
existing Team Control, Global Expert Team, and Enterprise AI ERP registries
instead of creating another role, identity, task, or organization truth source.

The current RU/Ozon validation profile projects:

- 12 `required_now` templates;
- 9 `supporting_ai` templates;
- 9 `on_demand` templates;
- 5 `standby` templates;
- 0 `unsupported_gap` entries.

`unsupported_gap` is the fifth result status and is emitted only for an
unsupported country or platform authority. Every catalog entry has one stable
`role-template://kjds/enterprise-positioning/v2/{role_ref}` reference,
`runtime_mode=capability_template_only`, `human_binding_status=UNKNOWN`, and no
production, external-write, or formal-Fact-promotion authority. A template is
not a Principal, Agent, employee, appointment, Grant, task, or Evidence of a
human binding.

The eight profile dimensions are `business_model`, `stage`, `headcount_band`,
`markets`, `platforms`, `risk_class`, `primary_objective`, and
`enterprise_ref`. They control positioning, role breadth, capacity, local
authority gaps, control strength, next activation, and a deterministic
non-authoritative scope. The current output retains four ordered human
accountability seats and six separation-of-duties rules; all bindings remain
`UNKNOWN`.

## Current projection receipt

- Snapshot SHA-256:
  `e9b043c6052276de1b4da9a5fac11b5e7543f5d2ea73718b236724063e94085b`.
- Role totals: 35 catalog entries, 12 required, 9 supporting AI, 9 on demand,
  5 standby, and 0 unsupported gaps.
- BR-149 is the sole current requirement; BR-148 remains historical traceability
  only.

Final focused Python, API, Web, OpenAPI, accessibility, static, secret, and G-1
receipts are recorded by the BAS-223 Evidence only after the integrated exact19
candidate is frozen. This absorbed Evidence does not independently claim a
feature, release, final G-1, production admission, or business readiness.

## Integrated boundary

BAS-223 changes the positioning module and registry together with authenticated
read-only API/runtime/router adapters, the saved OpenAPI snapshot, the existing
Team Control Web surface, MASTER_SPEC, ADR-0098, the board operating plan, and
the two BAS-223/BAS-222 Evidence records. It adds no database or migration and
does not create a second owner page.

No identity, appointment, task, Fact, budget, Approval, Permit, customer,
payment, purchase, listing, production setting, or external system write is
created or invoked.
