# BAS-158 native exact-scope channel account authority

- Frozen delivery date: 2026-07-31
- Final verification date: 2026-08-01
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Completion meaning: `read-only contract / implemented_unverified`
- Business state: `no_data`
- Real authorized channel account bindings: `0`
- Production managed credential resolver bound: `false`
- Official provider readback bound: `false`
- Fresh provider-specific external verifier passed: `false`
- Public mutation workflow: `mutation_gated / policy_only / contract_only`
- `verified_native`: `false`
- Requirement: `BR-132`
- ADR: [ADR-0078](../../adr/ADR-0078-native-exact-scope-channel-account-authority.md)

## Implemented authority boundary

`ScopedChannelAccountAuthorityWorkspace.project(...)` is the only native
channel-account composition seam. It admits the authenticated Principal and
exact tenant/entity/store/platform/account/adapter/as-of tuple, resolves the
canonical Store Matrix and canonical Scope Grant inside the deep module, and
only then reads append-only channel authorization observations or runtime
identity state. A caller-supplied entity/store tuple is not authority.

Missing entity returns deterministic `no_data` before Store Matrix, Scope
Grant, channel authority, credential or provider reads. Missing, denied,
blocked, stale, revoked or conflicting Store Matrix membership returns
top-level `blocked` before Scope Grant or any downstream read. Store-level role
and account mismatch, cross-tenant/entity/store scope and direct service calls
without a permitted Principal fail closed.

Forward-only `20260731_0081` persists only non-secret, append-only:

- authorization lifecycle observations;
- independent review decisions with deterministic sequence;
- exact-scope Kill Switch bindings.

It does not create another Tenant, Entity, Store, Product, Order or credential
truth. It does not modify 0042, 0079 or 0080.

## Evidence and lifecycle closure

Dedicated channel authority Evidence is not accepted through the generic
Evidence upload path. Each consent, lifecycle, Permit, Readback, Kill and
Compensation purpose has a strict versioned schema with required fields,
field-level types, bounded lengths, enums, normalized duplicate-key rejection
and exact semantic-to-canonical-payload binding. Digest fields are validated as
lowercase 64-hex before capture.

Recursive secret rejection covers nested objects and arrays, camel/snake/kebab
and case variants, repeated URL/HTML/Unicode decoding, joined string-list
views, integer byte arrays, JWT/Bearer/Basic/provider token patterns,
high-entropy values and managed-secret locator smuggling. `secret_reference`
accepts only an opaque managed locator identifier; the locator itself is never
returned by the workspace. Rejected submissions do not create Evidence,
Evidence Blob or review-decision rows.

Independent review is an append-only authority. The submitter cannot provide
`reviewed_by`; the reviewer must be a different actor. Admission resolves the
latest deterministic decision for the same submission, so accepted followed
by rejected cannot fall back to the old acceptance. Exact metadata scope is
checked before any blob read; cross-scope review and object access perform zero
Evidence Blob content reads.

Authorization observations bind the full canonical payload: account/store,
adapter identity and version, authorization epoch and sequence, capabilities,
scopes, secret-reference fingerprint, credential fingerprint, rotation,
revocation, expiry, health, rate limit, schema, readback, verification time,
Scope Grant hash and as-of. Missing fields, one-field drift, latest bad
Evidence, cross-scope bindings, degraded health, duplicate active runtime
identity, sequence/epoch drift or unknown outcome fail closed without older
success fallback.

Collection status and counts are computed from the full server-side result
before filter and page. A ready first page cannot hide a revoked, degraded or
bad latest identity on another page. Two lifecycle-active adapter/version
identities for one external account block every active identity for that
account.

## Governance and replay boundary

The read projection validates canonical Approval, frozen plan/command,
receipt/readback, Kill Switch and Compensation rows where such observations
exist; arbitrary Evidence metadata cannot manufacture those authorities.
Approval and command hashes cover the complete authorization contract.
Compensation approval binds exact scope, Scope Grant hash, account/adapter,
source event, primary approval, command, receipt, plan hash, prestate, mutated
state, restore target, mode, freshness and automatic-execution flags. First
grant uses explicit disable/revoke/cleanup compensation; later changes bind the
previous canonical state and reject a stale restore after a newer state.

The latest canonical global Kill Switch as of the event must match the latest
exact-scope binding. A newer engaged, stale or bad global state cannot fall
back to an older released binding.

Committed event and Kill Switch replay is checked by exact scope and canonical
payload before revalidating now-expired Evidence, a retired Adapter, a newer
Scope Grant epoch or an advanced global fuse. Same idempotency key and same
payload returns the minimal original committed outcome without re-execution;
different payload conflicts. Concurrent first submission catches uniqueness
and deterministically rereads the committed winner rather than leaking a raw
`IntegrityError`.

There is deliberately no public production mutation path for grant, refresh,
rotation or revocation. Direct ORM fixtures prove repository invariants only;
they are not evidence of a reachable governance workflow. External provider
mutation, automatic compensation and all platform writes remain gated.

## Managed runtime identity

Production workers cannot authorize themselves with a boolean, caller-created
dataclass, environment credential or caller-selected transport. A server-owned
resolver issues a signed, database-backed, exact-scope lease handle and returns
resolver-attested material only after verifying issuer/key id, lease id,
revocation, issued/expiry time, scope, platform/account/adapter/version,
capability, secret-reference fingerprint, credential fingerprint, official
readback and fresh external-verifier state. Client construction rechecks the
attestation over every credential-material field.

Test credentials are isolated to an explicit test fixture plus
`httpx.MockTransport`. A direct constructor, forged material or fixture paired
with a real transport raises a stable domain error before `httpx.Client`,
transport or socket creation. Read, finance-read and write workers use the
fixed order:

`admission → managed secret resolution → Control Plane client → provider client → socket`.

The production resolver remains intentionally unbound. The rebuilt API, Web
and media-worker containers expose neither `OZON_CLIENT_ID` nor
`OZON_API_KEY`; environment-only provider secrets cannot make the workspace
ready or authorize a worker. Both read and write `--preflight` modes validate
only bounded parameters and non-secret endpoint/operation shape: they report
`credential_values_read=false`, read no control-plane API key, provider secret,
managed locator or fingerprint, and construct no client, transport or socket.
Execute mode admits the exact-scope signed resolver handle and resolves provider
material before it may read a control-plane API key or construct either client.

## Public API and OpenAPI

The only BAS-158 public path is:

- `GET /v1/channel-accounts/workspace`.

No BAS-158 `POST`, `PUT`, `PATCH` or `DELETE` path exists. The repository
OpenAPI snapshot exactly matches the rebuilt live runtime:

- canonical live SHA-256:
  `4aaee589b2b5c7fea5b0fc2654b5e18d0e9843097fd6ed9982f4a8799eb7cbcc`;
- canonical snapshot SHA-256:
  `4aaee589b2b5c7fea5b0fc2654b5e18d0e9843097fd6ed9982f4a8799eb7cbcc`;
- paths:
  `{"/v1/channel-accounts/workspace": ["get"]}`.

The file byte hash differs from the canonical JSON hash because the repository
snapshot retains formatting; its SHA-256 is
`a8017f7f87987e238eca47869b6cf0186dd59ed419dc5aa93a52e8d4a908f77a`.

## Current verification

- full backend command:
  `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local`;
- full backend result: `1126 passed`, `9 warnings`, 49.67 seconds;
- focused authority/Evidence/runtime identity/read-finance-write Worker/API/
  OpenAPI/replay/security/registry result: `288 passed`, `1 warning`;
- Ruff: all checks passed;
- `verify_secrets`: `1013` non-ignored worktree files and `581` historical
  paths passed;
- `git diff --check`: passed, with line-ending notices only;
- Web clean container build: Docker `dependencies` stage completed `npm ci`;
- Web executable tests: `121 passed`;
- Web production build: `54` routes including `/channel-accounts`;
- Alembic current/head: single `20260731_0081`;
- empty PostgreSQL replay:
  `base → 0081 → 0080 → 0081`;
- actual PostgreSQL downgrade/re-upgrade:
  `0081 → 0080 → 0081`;
- 0081 negative insert matrix rejects invalid action, non-hex digest and
  invalid time order;
- four final-source rebuilt containers: healthy.

No full-suite count is inferred from an Evidence marker.

## Live runtime

The rebuilt runtime returned:

- anonymous `401`;
- authenticated exact store `200`;
- unauthorized store `403`;
- readiness `200`;
- deterministic replay `true`;
- status `no_data`;
- total `0`;
- channel accounts `[]`;
- snapshot SHA-256:
  `c260c20823e10d2f5fda4878db482477aded143cae9dca95a94247d7b638a326`;
- native implementation status: `implemented_unverified`;
- `verified_native=false`;
- `external_write_allowed=false`;
- every secret, Cookie, internal Token, device session, private endpoint,
  CAPTCHA/access-control bypass, authorization mutation, self approval,
  Permit issuance, provider contact and fictional-authority permission:
  `false`.

This no-data response does not prove a real channel authorization, provider
credential, external account readback or Worker lease.

## Web and browser

The `/channel-accounts` page consumes one server projection and does not
recalculate authority, readiness, counts, permissions or snapshot state.
Executable tests cover error→retry→ready plus distinct ready/no_data/blocked
DOM models, page-two blockers and filtered-empty behavior. The live browser
rendered the final rebuilt server `no_data` response.

- desktop inner/scroll width: `1440/1440`;
- mobile inner/scroll width: `390/390`;
- console errors: `0`;
- page errors: `0`;
- temporary browser auth state: deleted.

Screenshots:

- `output/playwright/bas158-channel-accounts-desktop.png`;
  SHA-256
  `2baec5a47f47312fd4f5de5e3c8825c1e2a6d0616502bf97910797cfe8c16b31`;
- `output/playwright/bas158-channel-accounts-mobile-390.png`;
  SHA-256
  `2b6d15d68203995ddeda5a931a203eef712ad245e12e179c3436934cb622a002`.

## Harness and Graph

`scripts/seed_bas158_agent_graph.py` hashes the authority, managed-runtime,
Worker, composition-root, migration, API/OpenAPI, Web, screenshot and Evidence
artifacts. It executes the current focused test list, empty PostgreSQL replay,
single-head check, final live runtime verifier, four-container health probe and
all executable Web tests. Five independent verifier categories own the
tests/database/runtime/web/evidence chain; the Channel Account Agent cannot
certify itself.

Final materialization contains `5` BAS-158 tasks, `8` BAS-158 nodes, `7`
BAS-158 edges and `5` latest fresh `passed` observations. The shared project
Graph contains `121` tasks, `250` nodes and `244` edges. Its append-only global
observation count is reported by the verifier output rather than embedded in
this Evidence file: embedding that mutable count would make the Evidence hash
self-referential because every fresh Evidence binding appends observations.

All five latest BAS-158 observations are fresh `passed`. The evidence verifier
binds this file's current SHA-256; a status marker or historical full-suite
number is insufficient.

## Remaining real-data and product blockers

The production managed secret store/resolver, official or expressly authorized
provider readback, provider-specific fresh external verifier, real account
binding and public governed mutation workflow are all unbound. Until they
exist, business readiness remains `no_data/blocked`, the mutation surface
remains `read_only/mutation_gated`, and `verified_native` remains globally
false for BAS-158.

Commerce OS capability acceptance is intentionally not inferred from menu
presence, stage completion or this engineering status. Capability-granular
acceptance is frozen separately as BAS-159.

`DONE_ENGINEERING` here means the exact-scope read authority, non-secret
append-only contract, fail-closed runtime admission and honest no-data boundary
are complete. It does not claim a real authorized account, credential lease,
provider connection, external write, operating result or completion of the
global 0.59→M4 verifiable digital-enterprise goal.
