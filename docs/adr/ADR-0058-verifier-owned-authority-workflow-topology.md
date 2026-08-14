# ADR-0058 — Verifier-owned Authority Workflow Topology

## Status

Accepted for BAS-134 on 2026-07-29.

## Context

BAS-133 made the exact-scope owner-source → independent-review → zero-write
preflight workflow executable, but one authenticated Web session can only perform the
actions owned by its current actor. A collection of API role profiles is not proof that
the workflow is usable from the Web, and a client-side role switch would defeat the
identity and separation-of-duty boundary.

The runtime must distinguish:

- registered API identities that can form the four-party subject, owner, reviewer and
  recorder chain;
- independently authenticated Web users bound to those actors;
- the current external deployment observation; and
- the later business Evidence and formal scope grant, which remain separate.

## Decision

Add one pure, versioned `AuthorityWorkflowTopologyVerifier` owned by the Web identity
module:

1. Its input is a secret-free projection of the running Web process configuration:
   auth mode, exact tenant/store, registered actor/role/scope profiles, hashed Web user
   references, current session actor and external-write boundary.
2. It deterministically enumerates a four-party chain:
   - subject: non-admin/non-monitor `operator`;
   - owner: `reviewer` or `admin`;
   - reviewer: `reviewer`, `risk`, `compliance` or `admin`;
   - recorder/preflight: `compliance` or `admin`.
3. All four actors must be distinct and authorized for the same tenant/store. Duplicate
   or ambiguous actor profiles, unknown bindings, scope drift, role conflicts or an
   enabled external-write flag are `failed`.
4. A valid API chain is reported separately from a usable Web chain. Web readiness
   requires `supabase` mode and four different hashed user references bound to the four
   selected actors. Legacy single-credential mode is `blocked`, never silently passed.
5. The result freezes contract/verifier version, `as_of`, input/result SHA-256,
   candidates, selected chain, blockers, why/next/Owner/SLA and explicit
   `grant_created=false` / `external_write_allowed=false`.
6. Authenticated `GET /auth/authority-topology` exposes only the secret-free result.
   Authority Intake renders it as a dynamic status and handoff map; it does not add a
   role switch or formal grant action.
7. An external observer calls the live Web endpoint, freezes the response in a
   content-addressed artifact, and appends a registered Agent Harness Observation.
   Stable Project/Requirements/Engineering/Runtime/Evidence/Authority nodes receive
   state only through an immutable Node→GoalTask binding.

## Consequences

- Existing API actors may prove that the backend chain is structurally possible while
  the real Web workflow remains blocked.
- Changing an actor profile, scope, auth mode or user binding changes the input hash and
  invalidates the previous observation.
- User IDs and API keys never enter the API response, artifact, Graph or logs.
- BAS-134 engineering can pass while its runtime-topology task remains `blocked`; M0
  and Release remain rejected until real identities and business Evidence exist.
- No Evidence, scope grant, Approval, Permit or external commerce write is created.

## Rejected alternatives

- Add an in-page role selector: it impersonates identities and collapses independent
  control.
- Treat four API keys as four Web users: API registration does not prove interactive
  authentication or user binding.
- Infer owner/reviewer/recorder from labels in the Graph: labels are not runtime
  authority.
- Store raw user IDs or credential keys in the Graph: the verifier only needs stable
  secret-free projections.
- Mark the task passed when the code exists: only a fresh external topology observation
  owns runtime state.
