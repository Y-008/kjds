import { createHash } from "node:crypto";

import type {
  ApiCredential,
  WebActorBinding,
  WebAuthMode,
} from "./identity-config.ts";

const CONTRACT_ID = "kjds-authority-workflow-topology-v1";
const VERIFIER_ID = "authority-workflow-topology";
const VERIFIER_VERSION = "1";
const FRESHNESS_SECONDS = 900;
const ALLOWED_ROLES = new Set([
  "operator",
  "reviewer",
  "compliance",
  "approver",
  "risk",
  "admin",
  "pilot_reader",
  "executor",
  "monitor",
]);

type SafeActor = {
  actor_id: string;
  roles: string[];
  tenant_ref: string;
  store_refs: string[];
  scope_explicit: boolean;
};

type WorkflowChain = {
  subject_actor_id: string;
  owner_actor_id: string;
  reviewer_actor_id: string;
  recorder_actor_id: string;
};

type WebBinding = {
  user_ref_sha256: string;
  actor_id: string;
};

export type AuthorityWorkflowTopology = {
  contract_id: typeof CONTRACT_ID;
  verifier: {
    id: typeof VERIFIER_ID;
    version: typeof VERIFIER_VERSION;
    authority: "external_web_identity_configuration";
  };
  state: "passed" | "blocked" | "failed";
  freshness: "fresh";
  observed_at: string;
  fresh_until: string;
  as_of: string;
  scope: { tenant_ref: string; store_ref: string };
  auth_mode: WebAuthMode;
  current_session: { actor_id: string; roles: string[] };
  counts: {
    registered_actors: number;
    exact_scope_actors: number;
    web_user_bindings: number;
    api_chains: number;
    web_chains: number;
  };
  candidates: {
    subjects: string[];
    owners: string[];
    reviewers: string[];
    recorders: string[];
  };
  selected_api_chain: WorkflowChain | null;
  selected_web_chain: (WorkflowChain & {
    user_refs_sha256: {
      subject: string;
      owner: string;
      reviewer: string;
      recorder: string;
    };
  }) | null;
  api_chain_ready: boolean;
  web_chain_ready: boolean;
  blocker_codes: string[];
  why: string;
  next_safe_action: string;
  owner: string;
  sla_seconds: number;
  input_sha256: string;
  result_sha256: string;
  model_self_certification_allowed: false;
  role_switch_allowed: false;
  grant_created: false;
  external_write_allowed: false;
};

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonical(item)]),
    );
  }
  return value;
}

function sha256(value: unknown): string {
  return createHash("sha256")
    .update(JSON.stringify(canonical(value)))
    .digest("hex");
}

function hashUserRef(userRef: string): string {
  return sha256({ namespace: "kjds-web-user-ref-v1", user_ref: userRef });
}

function includesAny(actor: SafeActor, roles: string[]): boolean {
  return roles.some((role) => actor.roles.includes(role));
}

function exactScopeActors(
  actors: SafeActor[],
  tenantRef: string,
  storeRef: string,
): SafeActor[] {
  return actors.filter(
    (actor) =>
      actor.tenant_ref === tenantRef && actor.store_refs.includes(storeRef),
  );
}

function enumerateChains(actors: SafeActor[]): WorkflowChain[] {
  const subjects = actors.filter(
    (actor) =>
      actor.roles.includes("operator")
      && !includesAny(actor, ["admin", "monitor"]),
  );
  const owners = actors.filter((actor) =>
    includesAny(actor, ["reviewer", "admin"])
  );
  const reviewers = actors.filter((actor) =>
    includesAny(actor, ["reviewer", "risk", "compliance", "admin"])
  );
  const recorders = actors.filter((actor) =>
    includesAny(actor, ["compliance", "admin"])
  );
  const chains: WorkflowChain[] = [];
  for (const subject of subjects) {
    for (const owner of owners) {
      for (const reviewer of reviewers) {
        for (const recorder of recorders) {
          const actorIds = [
            subject.actor_id,
            owner.actor_id,
            reviewer.actor_id,
            recorder.actor_id,
          ];
          if (new Set(actorIds).size !== actorIds.length) continue;
          chains.push({
            subject_actor_id: subject.actor_id,
            owner_actor_id: owner.actor_id,
            reviewer_actor_id: reviewer.actor_id,
            recorder_actor_id: recorder.actor_id,
          });
        }
      }
    }
  }
  return chains.sort((left, right) =>
    JSON.stringify(left).localeCompare(JSON.stringify(right))
  );
}

function webChain(
  chains: WorkflowChain[],
  bindings: WebBinding[],
): AuthorityWorkflowTopology["selected_web_chain"] {
  const byActor = new Map<string, string[]>();
  for (const binding of bindings) {
    const refs = byActor.get(binding.actor_id) ?? [];
    refs.push(binding.user_ref_sha256);
    refs.sort();
    byActor.set(binding.actor_id, refs);
  }
  for (const chain of chains) {
    const refs = {
      subject: byActor.get(chain.subject_actor_id)?.[0],
      owner: byActor.get(chain.owner_actor_id)?.[0],
      reviewer: byActor.get(chain.reviewer_actor_id)?.[0],
      recorder: byActor.get(chain.recorder_actor_id)?.[0],
    };
    if (Object.values(refs).some((value) => !value)) continue;
    if (new Set(Object.values(refs)).size !== 4) continue;
    return {
      ...chain,
      user_refs_sha256: refs as {
        subject: string;
        owner: string;
        reviewer: string;
        recorder: string;
      },
    };
  }
  return null;
}

export function verifyAuthorityWorkflowTopology({
  authMode,
  credentials,
  bindings,
  currentActorId,
  currentRoles,
  tenantRef,
  storeRef,
  environment,
  observedAt,
  externalWriteAllowed = false,
  configurationBlockers = [],
}: {
  authMode: WebAuthMode;
  credentials: Map<string, ApiCredential>;
  bindings: Map<string, WebActorBinding>;
  currentActorId: string;
  currentRoles: string[];
  tenantRef: string;
  storeRef: string;
  environment: string;
  observedAt: Date;
  externalWriteAllowed?: boolean;
  configurationBlockers?: string[];
}): AuthorityWorkflowTopology {
  const actors: SafeActor[] = [...credentials.values()]
    .map((credential) => ({
      actor_id: credential.actorId,
      roles: [...new Set(credential.roles)].sort(),
      tenant_ref: credential.tenantRef,
      store_refs: [...new Set(credential.storeRefs)].sort(),
      scope_explicit: credential.scopeExplicit,
    }))
    .sort((left, right) => left.actor_id.localeCompare(right.actor_id));
  const safeBindings: WebBinding[] = [...bindings.entries()]
    .map(([userRef, binding]) => ({
      user_ref_sha256: hashUserRef(userRef),
      actor_id: binding.actorId,
    }))
    .sort((left, right) =>
      `${left.actor_id}:${left.user_ref_sha256}`.localeCompare(
        `${right.actor_id}:${right.user_ref_sha256}`,
      )
    );
  const exactActors = exactScopeActors(actors, tenantRef, storeRef);
  const chains = enumerateChains(exactActors);
  const selectedApiChain = chains[0] ?? null;
  const selectedWebChain =
    authMode === "supabase" ? webChain(chains, safeBindings) : null;

  const blockerCodes = new Set<string>();
  for (const blocker of configurationBlockers) {
    if (blocker.trim()) blockerCodes.add(blocker.trim());
  }
  const duplicateActorCount = actors.length - new Set(actors.map((actor) => actor.actor_id)).size;
  if (duplicateActorCount) blockerCodes.add("ambiguous_actor_profile");
  if (
    actors.some((actor) =>
      actor.roles.some((role) => !ALLOWED_ROLES.has(role))
    )
  ) {
    blockerCodes.add("unknown_role");
  }
  if (
    actors.some(
      (actor) =>
        actor.roles.includes("operator")
        && actor.roles.includes("approver")
        && !actor.roles.includes("admin"),
    )
  ) {
    blockerCodes.add("operator_approver_role_conflict");
  }
  if (
    environment === "production"
    && actors.some((actor) => !actor.scope_explicit)
  ) {
    blockerCodes.add("production_scope_not_explicit");
  }
  if (safeBindings.some((binding) => !credentials.has(binding.actor_id))) {
    blockerCodes.add("web_binding_actor_unknown");
  }
  if (externalWriteAllowed) blockerCodes.add("external_write_enabled");
  const failed =
    configurationBlockers.length > 0
    || [
    "ambiguous_actor_profile",
    "unknown_role",
    "operator_approver_role_conflict",
    "production_scope_not_explicit",
    "web_binding_actor_unknown",
    "external_write_enabled",
    ].some((code) => blockerCodes.has(code));
  if (!selectedApiChain) blockerCodes.add("four_party_api_chain_missing");
  if (authMode !== "supabase") blockerCodes.add("web_auth_mode_not_supabase");
  if (authMode === "supabase" && !selectedWebChain) {
    blockerCodes.add("four_party_web_binding_chain_missing");
  }

  const state = failed
    ? "failed"
    : selectedApiChain && selectedWebChain
      ? "passed"
      : "blocked";
  const sortedBlockers = [...blockerCodes].sort();
  const observedIso = observedAt.toISOString();
  const freshUntil = new Date(
    observedAt.getTime() + FRESHNESS_SECONDS * 1000,
  ).toISOString();
  const input = {
    contract_id: CONTRACT_ID,
    verifier_version: VERIFIER_VERSION,
    environment,
    auth_mode: authMode,
    scope: { tenant_ref: tenantRef, store_ref: storeRef },
    actors,
    web_bindings: safeBindings,
    current_session: {
      actor_id: currentActorId,
      roles: [...new Set(currentRoles)].sort(),
    },
    configuration_blockers: configurationBlockers.length
      ? [...new Set(configurationBlockers)].sort()
      : undefined,
    external_write_allowed: externalWriteAllowed,
  };
  const inputSha256 = sha256(input);
  const resultCore = {
    state,
    blocker_codes: sortedBlockers,
    selected_api_chain: selectedApiChain,
    selected_web_chain: selectedWebChain,
    input_sha256: inputSha256,
  };
  const why =
    state === "passed"
      ? "Four distinct exact-scope API actors and four independently bound Supabase users form the authority workflow."
      : failed
        ? "The observed identity topology violates a fail-closed authority invariant."
        : selectedApiChain
          ? "The four-party API chain exists, but the Web does not yet expose four independently authenticated bound users."
          : "The running identity map cannot form a four-party exact-scope authority chain.";
  const nextSafeAction =
    state === "passed"
      ? "Use the independently authenticated owner session to submit real authority source Evidence."
      : failed
        ? "Repair the reported identity topology invariant, then obtain a new external observation."
        : selectedApiChain
          ? "Configure Supabase Web auth and bind four distinct users to the selected subject, owner, reviewer and recorder actors."
          : "Register four distinct exact-scope actors for subject, owner, reviewer and recorder responsibilities.";
  const owner =
    selectedApiChain && !selectedWebChain
      ? "account-owner+identity-engineering"
      : "identity-engineering+compliance";

  return {
    contract_id: CONTRACT_ID,
    verifier: {
      id: VERIFIER_ID,
      version: VERIFIER_VERSION,
      authority: "external_web_identity_configuration",
    },
    state,
    freshness: "fresh",
    observed_at: observedIso,
    fresh_until: freshUntil,
    as_of: observedIso,
    scope: { tenant_ref: tenantRef, store_ref: storeRef },
    auth_mode: authMode,
    current_session: {
      actor_id: currentActorId,
      roles: [...new Set(currentRoles)].sort(),
    },
    counts: {
      registered_actors: actors.length,
      exact_scope_actors: exactActors.length,
      web_user_bindings: safeBindings.length,
      api_chains: chains.length,
      web_chains: selectedWebChain ? 1 : 0,
    },
    candidates: {
      subjects: exactActors
        .filter(
          (actor) =>
            actor.roles.includes("operator")
            && !includesAny(actor, ["admin", "monitor"]),
        )
        .map((actor) => actor.actor_id),
      owners: exactActors
        .filter((actor) => includesAny(actor, ["reviewer", "admin"]))
        .map((actor) => actor.actor_id),
      reviewers: exactActors
        .filter((actor) =>
          includesAny(actor, ["reviewer", "risk", "compliance", "admin"])
        )
        .map((actor) => actor.actor_id),
      recorders: exactActors
        .filter((actor) => includesAny(actor, ["compliance", "admin"]))
        .map((actor) => actor.actor_id),
    },
    selected_api_chain: selectedApiChain,
    selected_web_chain: selectedWebChain,
    api_chain_ready: Boolean(selectedApiChain),
    web_chain_ready: Boolean(selectedWebChain),
    blocker_codes: sortedBlockers,
    why,
    next_safe_action: nextSafeAction,
    owner,
    sla_seconds: 86400,
    input_sha256: inputSha256,
    result_sha256: sha256(resultCore),
    model_self_certification_allowed: false,
    role_switch_allowed: false,
    grant_created: false,
    external_write_allowed: false,
  };
}
