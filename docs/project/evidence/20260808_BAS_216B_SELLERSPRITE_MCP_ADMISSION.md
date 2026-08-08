# BAS-216B SellerSprite MCP inventory admission Evidence

## Scope

BAS-216B adds a read-only preflight seam for the SellerSprite Streamable HTTP MCP endpoint. This slice does not invoke any research tool and does not turn live SellerSprite data into a KJDS Observation. It only initializes one authenticated MCP session, exhausts `tools/list`, validates budgets and structure, and returns names plus content-addressed hashes for independent review.

The exact implementation set is:

- `apps/control_plane/marketplace_research_mcp.py`
- `docs/project/registries/marketplace_research_mcp_admission.json`
- `scripts/inspect_sellersprite_mcp.py`
- `tests/test_marketplace_research_mcp.py`
- this Evidence record

## Official inputs

- SellerSprite documents the MCP product and an observed 44 tools / 10 Amazon sites at `https://open.sellersprite.com/mcp`.
- SellerSprite documents the Streamable HTTP endpoint and `secret-key` header at `https://open.sellersprite.com/mcp/16`.
- SellerSprite publishes MCP price observations at `https://open.sellersprite.com/pricing/mcp`; prices are dynamic observations and are not a KJDS entitlement, cost approval, or admission authority.
- The MCP Streamable HTTP transport contract is referenced at `https://modelcontextprotocol.io/specification/2025-11-25/basic/transports`.

These sources prove that the endpoint and commercial product are documented. They do not prove current server identity, a complete immutable inventory, license permission for KJDS use, cost approval, rate-limit entitlement, revocation handling, data quality, or business outcomes.

## Hard gates

- The endpoint is frozen to `https://mcp.sellersprite.com/mcp`; userinfo, query, fragment, alternate host, plain HTTP, redirects and environment proxies are rejected or disabled.
- The secret is read only from `KJDS_SELLERSPRITE_MCP_SECRET_KEY`. It is not a CLI argument, registry value, projection field, hash, log, Evidence value, or repository byte.
- The transport sets `follow_redirects=false`, `trust_env=false`, and `terminate_on_close=false`, preventing credential forwarding through redirects/proxies and preventing a DELETE side effect on close.
- This slice permits only MCP initialization (including its required `notifications/initialized` handshake) and complete paginated tool inventory. It has no tool invocation method, no retry policy, and no partial research receipt.
- Decoded inventory traversal rejects cursor cycles, malformed pages, duplicate names, unsafe names, empty inventory, non-finite JSON, unknown protocol versions, all local and remote schema references, invalid Draft 2020-12 schemas, excessive depth, excessive descriptor/page/envelope bytes, too many pages, and too many tools. `initialized` is exposed as true only after the complete initialize identity/protocol/capability/server-info validation succeeds.
- Every tool descriptor hash covers all server-provided fields, including title, description, input/output schemas, annotations, icons, `_meta`, execution, and future extra fields. Tool order is normalized by name; omitted and explicit-null fields remain distinct.
- Provider descriptions, server instructions, and raw schemas are treated as untrusted tool-poisoning input. They are hashed but never returned in the public projection or supplied to a model.
- `readOnlyHint` is an untrusted provider hint and cannot grant admission.
- A successful network inspection still returns `review_required`, with inventory, server identity, license, cost, rate limit, and revocation all unapproved or unverified. The registry fixes `live_admission=not_admitted` and has an empty allowed-tool list.
- Product, Fact, FinanceEntry, Approval, Permit, procurement, listing, outreach, model invocation, Evidence creation, and every external write remain false.

## Verification

The focused tests cover deterministic full pagination, stable ordering, every descriptor surface, omitted/null distinction, tool poisoning redaction, secret absence and exception redaction, duplicate tools, cursor loops, page/tool/byte/depth budgets including oversized nested page `_meta`, non-finite JSON, unsafe names, malformed initialize/page responses with `initialized=false`, unknown protocol versions, invalid and local/remote schema references, registry endpoint/redirect/operation/admission/public-output/control/schema-policy drift, transport settings, CLI argument sanitization, and missing-secret zero-network behavior.

Current literal Gate outputs for the stopped five-file bytes: focused MCP tests `65 passed in 0.51s`; combined marketplace workflow, MCP, and assignment tests `142 passed in 0.64s`; target Ruff PASS; isolated `py_compile` PASS; `git diff --check` PASS. No live endpoint call is required for engineering verification because no SellerSprite secret has been configured in this environment. A future live inventory capture must produce a new content-addressed inventory and independent server/license/cost/rate/revocation approvals before any tool invocation slice can begin.

## Residual UNKNOWN

- actual current MCP tool names, schemas, descriptions, pagination behavior, protocol version, and server identity;
- a transport-level response-body cap before the MCP SDK decodes a JSON-RPC message; the current budgets apply immediately after SDK decoding and before any public projection;
- live license terms and downstream data-retention permission;
- current price entitlement, rate limits, revocation semantics, production SLO, and failure behavior;
- mapping from live tools/results to the BAS-216A receipt contract;
- real marketplace data quality, customer outcome, profitability, or global leadership.

All remain `UNKNOWN` or `not_admitted`; no production, Top1, causal, revenue, buyer-intent, or customer-result claim is made.
