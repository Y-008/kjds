# ADR-0074: Native exact-scope customer-service authority

- Date: 2026-07-30
- Status: Accepted for BAS-154
- Requirement: BR-128
- Decision owner: Customer operations and privacy architecture
- Approval owner: Operations, compliance and security leadership

## Context

BAS-153 can verify an exact returned order and its financial consequence, but
it truthfully reports customer-service cases, messages, disputes and RMA as
gated. KJDS needs native authority for those objects without copying a Seller
ERP inbox or letting a model call “drafted” messages “sent”.

Customer communications can contain personal data. Copying raw body, name,
address, phone, email or platform account into normal tables, Agent artifacts,
Graph nodes, logs or browser list responses would create an uncontrolled
secondary PII store.

## Decision

### Unique immutable authority

Migration 0079 creates:

- `customer_service_cases`;
- `customer_service_events`.

It also extends the existing governed execution-plan source discriminator with
`approved_customer_service_reply`. This does not enable a message Adapter; it
only makes the already-required Approval → Plan → one-time command lineage
representable without misusing a Listing or causal-policy source kind.

Both are immutable and exact tenant/entity/store/grant/as-of records. A Case
binds one external source case, channel, Order, Product/SKU, source Evidence,
locale, classification, priority and opened timestamp. An Event binds the Case,
source event, ordered sequence, event type, direction, non-sensitive summary,
message body SHA-256, source Evidence, effective/recorded timestamps and
optional complete execution authority.

Raw message body and PII remain only in governed Evidence Blob. The business
tables never store customer name, address, phone, email, platform handle,
Cookie, Token or raw message. Agent and Web receive only the explicitly
non-sensitive projection.

### One deep projection

Add:

`ScopedCustomerServiceWorkspace.project(...)`.

It owns scope validation, source reads, latest-event failure closure, state
transitions, Return binding, execution-authority observation, deterministic
filter/cursor/counts and stable artifact/snapshot hashes. Router, Web and
prompts stay shallow.

### State and execution authority

Case states include:

`opened → triaged → reply_drafted → reply_approval_pending →
reply_permit_pending → reply_readback_pending → awaiting_customer |
return_in_progress | dispute_in_progress | resolved | closed`.

An observed outbound `message_sent_readback` is valid only when it binds:

- an independently approved `customer_service.send_reply` decision;
- an exact, unexpired, one-time LimitedExecutionCommand;
- a successful immutable Readback Evidence record;
- the exact Case, event and approved body SHA-256.

The uploader/drafter cannot approve their own reply. A draft, Approval or
command alone never means a message was sent. BAS-154 does not register a
message Adapter and cannot create external execution.

### Privacy failure closure

Case/Event intake rejects raw PII fields and suspicious PII-like content in
the non-sensitive summary. Source Evidence access remains governed separately.
List/workspace responses expose Evidence IDs and hashes, never Blob content.

Latest damaged, revoked, future, cross-scope, duplicate, out-of-sequence or
illegal-transition authority blocks the Case and cannot fall back to an older
apparently healthy state.

### Agent boundary

The Agent artifact may produce a versioned reply draft hash and internal task
suggestion from the non-sensitive projection. It cannot:

- retrieve unauthorized Evidence Blob or raw PII;
- create or modify Case/Event authority;
- approve its own draft;
- issue or consume a Permit;
- mark a message sent;
- start a refund, dispute or RMA;
- contact a customer or call an external platform/Seller ERP.

Private endpoints, Cookies, internal Tokens and CAPTCHA bypass remain
prohibited. Official APIs, formal exports and explicitly authorized adapters
are the only external intake paths.

## Verification

BAS-154 must prove:

- missing entity performs zero Case/Event/Return/Approval/Command reads;
- exact scope/as-of and immutable idempotent intake;
- PII fields and PII-like summaries fail closed;
- deterministic transition/sequence/latest-bad handling;
- Return/Order/Product binding;
- independent Approval, one-time command and Readback separation;
- anonymous 401 and unauthorized 403;
- 0079 empty/live/downgrade-forward replay;
- Web ready/no_data/partial/blocked/error/retry at desktop and 390px;
- fresh Harness/Graph observations;
- no message Adapter, self-approval, Permit issuance, refund or external write.
