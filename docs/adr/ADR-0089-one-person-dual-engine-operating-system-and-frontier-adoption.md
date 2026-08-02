# ADR-0089: One-person dual-engine operating system and frontier adoption

- Status: Accepted for operating design and bounded engineering
- Date: 2026-08-03
- Owners: Business Owner, Product, Engineering, Finance, Risk
- Related: BAS-171 through BAS-175

## Context

The project must operate a Russia/Ozon commerce business and commercialize the
software produced by that operation. Local social-media screenshots describe a
useful pattern: use content to discover demand, sell a small paid solution,
turn delivery cases into reusable modules, and let the stronger back system
improve future sales and delivery. The screenshots are observations, not
verified operating or financial facts. Their income, pricing and customer
outcome claims cannot become forecasts, pricing authority or Gate evidence.

The repository already contains exact-scope authorities, Evidence, approval,
outbox, a governed Agent runtime, causal knowledge and profit-truth controls.
Adding fashionable infrastructure without joining it to these authorities
would create another demo surface rather than a commercial operating system.

## Decision

1. Adopt one operating loop for both businesses:

   ```text
   evidence-backed signal or content
     -> qualified problem
     -> scoped diagnosis
     -> paid bounded MVP
     -> measured delivery
     -> consented case evidence
     -> reusable module or playbook
     -> managed product or software capability
     -> renewal, referral and next content signal
   ```

2. Keep three operating planes and four mandatory control rails:

   - Front: positioning, research, content, channel and lead qualification.
   - Middle: diagnosis, value hypothesis, scope, proposal, closing and Pilot.
   - Back: delivery, customer success, case abstraction and productization.
   - Rails: profit/cash truth, Evidence/compliance, identity/authority and
     platform/data/AI reliability.

3. "One-person company" means one accountable Business Owner, not one identity
   holding every power. Researcher, operator, finance reviewer, risk reviewer,
   approver and executor remain independently attributable. Agents may prepare,
   compare and verify work but cannot self-approve, issue a Permit, promote a
   Fact or perform an external write.

4. Join the two engines without leaking authority:

   - The owned Ozon operation provides consented, exact-scope cases and measured
     failure patterns.
   - The software converts repeated patterns into configurable modules,
     diagnostics and managed workspaces.
   - Customer tenants never become a pooled raw-data training set. Only
     approved, de-identified patterns or explicitly licensed artifacts may be
     reused, with provenance and revocation.

5. Treat content as a demand experiment, not as proof. Short content tests one
   problem and one call to action; long content explains the decision model and
   boundaries. Success is a qualified diagnostic conversation or paid Pilot,
   not follower count. Public claims require source, scope, effective date and
   consent.

6. Productize through a controlled offer ladder: public education, scoped
   diagnosis, paid Pilot, managed implementation, isolated subscription, then
   self-service multi-tenant SaaS. Before C0, only preparation and truthful
   public education are allowed; any paid offer requires C0, and self-service
   multi-tenant SaaS additionally requires G7. Prices remain experiments
   approved by the commercial owner; the screenshot prices are not copied.

7. Use `frontier_technology_adoption.json` as the machine-readable adoption
   truth. A technology must be classified as `adopt_now`, `pilot`, `watch` or
   `reject_now`, and must include an evidence source, KJDS use case, entry and
   exit Gate, risk, owner and review date. Novelty, model ranking or popularity
   is never an adoption reason.

8. Prioritize the following seams over new platforms:

   - Persist model/tool/prompt/eval/authority versions and outcome lineage for
     the existing governed Agent trace, without storing secrets or raw customer
     prompts by default.
   - Benchmark causal and temporal retrieval over the existing Graph and
     Evidence before adding vector infrastructure.
   - Keep current state machines and Outbox authoritative; test a durable
     workflow adapter only for measured multi-hour or multi-day replay pain.
   - Rehearse PostgreSQL 18, software provenance, SBOM/AI-BOM and workload
     identity in isolated lanes before production migration.
   - Keep Seller API or official export as the primary platform path. Browser
     automation remains an isolated, read-mostly fallback with no cookie store
     in the canonical control plane.

9. Measure the loop with paired value and risk metrics: qualified-problem rate,
   diagnosis-to-paid-Pilot, time to first verified value, Pilot-to-renewal,
   case-to-reusable-module, delivery gross margin, Actual Cash CM3 coverage,
   evidence completeness, human review time, defect escape, override rate and
   external-write incidents. Follower count, generated content volume and
   model tokens are not north-star metrics.

10. Preserve the Day 0 truth boundary. Real catalog and finance reads do not
    prove real orders, settlement, bank cash, Actual Cash Profit or provider
    writes. This ADR opens no commercial entitlement, Pilot, Fact, Approval,
    Permit or external action.

11. Build self-learning as a governed `TeamAgent` evolution loop, not an
    unbounded self-modifying process. Human corrections, verified failures,
    Evidence-backed outcomes, policy violations and official source changes
    may create an Observation or versioned Skill candidate. Promotion requires
    a frozen eval set, baseline comparison, negative/scope tests, shadow run,
    independent review and rollback artifact. Runtime Agents cannot modify
    code, permissions, Facts, Approval, Permit or external-write policy. Code
    evolution still occurs through an isolated worktree, tests, review and Git.
    Canonical Graph nodes and edges created by learning remain Observations
    until independently promoted, and raw cross-tenant learning is forbidden.

## Consequences

- Business discovery, delivery and software development now share one
  evidence-producing loop and one vocabulary.
- The founder can operate with small WIP while independent identities and
  review controls prevent concentration of authority.
- Existing modules are deepened before infrastructure is multiplied.
- Technology adoption becomes reversible and testable; several attractive
  technologies remain deferred until a measured trigger exists.
- Commercial progress must be demonstrated by paid, consented and
  evidence-backed outcomes, not social engagement or synthetic dashboards.
- TeamAgent quality can improve continuously while every Skill, model route,
  tool contract, policy, graph edge and rollback remains versioned and auditable.

## Alternatives rejected

- Copy the creator's product, prices or income claims: provenance and fit are
  insufficient.
- Optimize for audience size before problem qualification: it creates an
  expensive unqualified funnel.
- Let one super-Agent own research, finance, approval and execution: it defeats
  separation of duties and exact-scope authority.
- Install Temporal, Kafka, ClickHouse, Iceberg, a graph database or a vector
  database immediately: current volume and operating pain do not justify the
  complexity tax.
- Launch self-service multi-tenant SaaS before repeated paid delivery and G7:
  tenancy, billing, support, recovery and legal evidence are incomplete.

## Review triggers

Re-open this ADR when three independent customers repeat the same paid module,
when a long-running workflow misses its replay/SLO target, when PostgreSQL
query or storage measurements exceed the registered threshold, before raw
tenant data is reused across customers, or before an Agent, browser or external
protocol receives any production write authority.
