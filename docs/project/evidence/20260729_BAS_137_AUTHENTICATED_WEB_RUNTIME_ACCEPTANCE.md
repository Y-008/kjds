# BAS-137 Evidence — Authenticated Web Runtime Acceptance

## Decision

`BAS-137` accepts the authenticated Web runtime correction and browser
acceptance on 2026-07-29. It does **not** accept M0, Release 0.59, Pilot or the
Final Gate.

The accepted slice:

- uses the browser-visible Host/public origin instead of the Next standalone
  bind address for both mutation-origin checks and auth redirects;
- keeps cross-site and originless mutations fail-closed;
- renders a rejected auth action as a no-store `403` HTML security message
  linking to the visible login page instead of exposing a raw JSON error;
- consumes scoped list read models through their canonical `items` or
  `products` envelopes;
- proves a real `r0-requester` Supabase Web session and current Graph
  projections in Chrome;
- keeps `external_write_allowed=false`.

No Ozon, 1688, supplier, purchase, payment, advertising, Approval, Permit or
scope-grant write was performed.

## Rejected-login presentation regression

The 2026-07-29 follow-up rebuilt the running Web image and verified:

- `GET /auth/login` returns `303 Location: http://127.0.0.1:3000/login`;
- an originless `POST /auth/login` remains fail-closed with a no-store,
  CSP-bounded `403 text/html` response and a link to the trusted login page;
- the rejection surface explains the security decision instead of exposing a
  raw JSON document;
- the existing authenticated Chrome session still renders the KJDS dashboard
  as `r0-requester · operator`;
- Web tests pass `64/64` and the production Webpack build exposes all 35
  expected routes.

## Reproduced failures

The first real Chrome login reached:

```json
{"detail":"Cross-site or originless login is not allowed"}
```

The deterministic HTTP reproduction returned `403` for a same-browser-origin
POST because Next constructed `request.url` from `HOSTNAME=0.0.0.0`. After the
origin check was corrected, Supabase authentication succeeded but the route
redirected Chrome to `http://0.0.0.0:3000/`, which Chrome blocked. Both failures
shared one missing browser-visible-origin authority.

After authentication, a fresh runtime log also exposed two real application
contract exceptions:

- `readOnlyPilots.find is not a function`;
- `e.map is not a function`.

The service responses were canonical scoped envelopes:

- `/v1/read-only-pilots` → `items`;
- `/v1/marketplace-catalog/items/latest` → `items`;
- `/v1/products` → `products`;
- `/v1/operations-control/queue` → `items`.

The dashboard still treated those responses as legacy arrays.

## Implementation

`web/lib/identity-config.ts` now owns both contracts:

- `mutationOriginIsAllowed()` accepts only the request URL, browser-visible
  Host origin or explicit `KJDS_WEB_PUBLIC_ORIGIN`;
- `webRequestUrl()` creates login, callback, MFA and logout redirects from the
  same public-origin authority.

Login, callback and logout routes no longer construct redirects directly from
the container bind URL.

`web/lib/scoped-collection.ts` is the single list-envelope adapter. It:

- reads canonical `items` and `products` arrays;
- retains legacy array compatibility during migration;
- throws on an unknown successful payload instead of silently substituting
  empty data.

The dashboard uses it for Catalog, Product, OperationsQueue and ReadOnlyPilot
reads, including explicit Catalog reload.

## HTTP and auth verification

The final running Web returned:

- real DPAPI-backed `r0-requester` credentials:
  `303 Location: http://127.0.0.1:3000/`;
- invalid credentials from the same origin:
  `303 Location: http://127.0.0.1:3000/login?error=invalid`;
- cross-site origin:
  `403`;
- originless POST:
  `403`.

The credential value was neither printed nor written to this Evidence. Chrome
then rendered the authenticated identity:

`r0-requester@kjds059.example.com · operator`.

## Verifier and Graph runtime

The Windows Task `KJDS-Evidence-Integrity-Health` completed an explicit run at
`2026-07-29T11:48:01+08:00` with native result `0`. The control-plane-only
health loop reported:

- API and operations readiness `200`;
- Evidence integrity `58 scanned / 0 invalid`;
- database revision `20260728_0070`;
- bound operating subject `r0-requester`;
- `external_write_allowed=false`;
- M0 `no_data`, M1–M4 `blocked`.

The external Project/Engineering Graph verifier was then rerun rather than
pretending that the lightweight scheduler refreshes BAS-132/133/134. It
returned:

- `32` tasks;
- `110` nodes;
- `123` edges;
- `251` append-only observations;
- `77` bindings;
- `77` verified nodes;
- `26 passed / 4 blocked / 2 no_data / 0 stale`;
- workspace `blocked`;
- Release `REJECTED`.

## Browser acceptance

Authenticated Chrome rendered the dashboard and the three canonical Graph
projections from the running Web/API/PostgreSQL stack.

Desktop:

- Project Graph: `clientWidth=scrollWidth=2028`, `32/26/0/4/0`;
- Engineering Graph: `clientWidth=scrollWidth=2028`, `37` projection nodes,
  `28` verified projection nodes and `30` edges;
- Authority Graph: `clientWidth=scrollWidth=2028`, `18` projection nodes,
  `15` verified projection nodes and `14` edges;
- all three display `external write false`.

Chrome was already configured at 75% page zoom. The mobile verifier therefore
calibrated the browser override to an exact **390 CSS-pixel content viewport**.
For Project, Engineering and Authority:

- `clientWidth=scrollWidth=390`;
- every sampled card remained within `x=12..378.4`;
- the mobile media query matched;
- no page-level horizontal overflow occurred.

The two KJDS bundle `TypeError` stacks disappeared in a new post-build browser
tab. The final authenticated dashboard loaded `25` articles with
`clientWidth=scrollWidth=2028` and zero KJDS bundle stack errors. Generic
`Object` logs paired with the installed Chrome content extension remain
external-extension noise and are not claimed as KJDS runtime success.

## Frozen screenshots

All files are under `output/playwright/release-0.59.0/`.

| Artifact | SHA-256 |
|---|---|
| `dashboard-authenticated-desktop.png` | `004dc58b1118291f2252afd73df77d99805259f2cb6416f4a955ffb015661a24` |
| `project-graph-authenticated-desktop.png` | `a348d4acdb7bbe2c31c7d1f718d3cba2fd9c0926c6929db02362eef183b7212c` |
| `project-graph-authenticated-mobile-390.png` | `4e3d8710304d3e666914b2805646a6d0b6379d1c71c9d248e36329d807d509c4` |
| `engineering-graph-authenticated-desktop.png` | `cba6cc86846e79461372a5fdba75501528011f14d4e7bac35d58fa39e385fa23` |
| `engineering-graph-authenticated-mobile-390.png` | `cf4e47bb98c97f01803e675be95057e258b6871d0028bdda5deae0dfd813d7b1` |
| `authority-graph-authenticated-desktop.png` | `539a01fc1487c53cde1e10b8576c7437c2a2a37448b74a1492303d4b5e6f78ac` |
| `authority-graph-authenticated-mobile-390.png` | `2a389621896e61e45c926d91210558998ad1c4e0fe117e9f584bc477d3d9a101` |

## Quality evidence

- Web unit/contract suite: `64 passed`;
- Next production build: `35` routes generated successfully;
- secret scan: `771` non-ignored worktree files and `581` historical paths,
  passed;
- Web container rebuilt and healthy;
- PostgreSQL/API/media-worker/Web healthy during Graph verification;
- focused `git diff --check`: clean apart from existing line-ending warnings.

## Remaining Gate

M0 remains truthfully `no_data`. The current operating subject still requires
real owner source Evidence, an accepted independent risk review and compliance
recording before a scope grant can exist. A current grant alone would still
not authorize Ozon publication: real candidate data, downside CM3, Passport,
media rights/QA, independent Approval, one-time Permit, Readback and stop-loss
controls remain separate later gates.
