import {
  DEMO_MARKERS,
  LocalDemoDomainError,
  type DemoSessionSnapshot,
  type DemoTransition,
  type DemoWorkspace,
  type ScenarioPack,
} from "./contracts.ts";
import {
  canonicalJson,
  deterministicTimestamp,
  sha256Hex,
} from "./scenario-pack.ts";

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const SESSION_ID_PATTERN = /^demo-session-[a-z0-9][a-z0-9._-]*$/;
const SUBJECT_REF_PATTERN = /^demo-[a-z0-9][a-z0-9._-]*$/;
const SESSION_TTL_MINUTES = 60 as const;

export interface DemoTransitionDraft {
  readonly workspace: DemoWorkspace;
  readonly action: string;
  readonly subject_ref: string;
  readonly canonical_payload_sha256: string;
  readonly occurred_at: string;
}

function immutableSnapshot<T>(value: T): T {
  const clone = structuredClone(value);
  const freeze = (item: unknown): void => {
    if (typeof item !== "object" || item === null || Object.isFrozen(item)) {
      return;
    }
    Object.freeze(item);
    for (const child of Object.values(item)) {
      freeze(child);
    }
  };
  freeze(clone);
  return clone;
}

export class DemoSession {
  readonly #pack: ScenarioPack;
  readonly #sessionId: string;
  readonly #openedAt: string;
  readonly #expiresAt: string;
  #sequence = 0;
  #stateSha256: string;
  readonly #transitionLog: DemoTransition[] = [];

  constructor(pack: ScenarioPack, sessionId: string) {
    if (!SESSION_ID_PATTERN.test(sessionId)) {
      throw new LocalDemoDomainError("demo_session_id_invalid", 400);
    }
    this.#pack = pack;
    this.#sessionId = sessionId;
    this.#openedAt = deterministicTimestamp(pack, 0);
    this.#expiresAt = new Date(
      Date.parse(this.#openedAt) + SESSION_TTL_MINUTES * 60_000,
    ).toISOString();
    this.#stateSha256 = sha256Hex(
      canonicalJson({
        session_id: sessionId,
        scenario_sha256: pack.scenario_sha256,
        sequence: 0,
      }),
    );
  }

  isExpired(at: string): boolean {
    const atMs = Date.parse(at);
    if (!Number.isFinite(atMs)) {
      throw new LocalDemoDomainError("demo_timestamp_invalid", 400);
    }
    return atMs >= Date.parse(this.#expiresAt);
  }

  appendTransition(draft: DemoTransitionDraft): DemoTransition {
    if (this.isExpired(draft.occurred_at)) {
      throw new LocalDemoDomainError("demo_session_expired", 410);
    }
    if (this.#sequence >= this.#pack.workspace_projections.summary.demo_capacity) {
      throw new LocalDemoDomainError("demo_capacity_exhausted", 409);
    }
    if (
      draft.action.length === 0 ||
      !SUBJECT_REF_PATTERN.test(draft.subject_ref) ||
      !SHA256_PATTERN.test(draft.canonical_payload_sha256)
    ) {
      throw new LocalDemoDomainError("demo_transition_invalid", 400);
    }
    const nextSequence = this.#sequence + 1;
    const expectedOccurredAt = deterministicTimestamp(this.#pack, nextSequence);
    if (draft.occurred_at !== expectedOccurredAt) {
      throw new LocalDemoDomainError("demo_transition_clock_drift", 409);
    }
    const previousStateSha256 = this.#stateSha256;
    const nextStateSha256 = sha256Hex(
      canonicalJson({
        action: draft.action,
        canonical_payload_sha256: draft.canonical_payload_sha256,
        occurred_at: draft.occurred_at,
        previous_state_sha256: previousStateSha256,
        sequence: nextSequence,
        subject_ref: draft.subject_ref,
        workspace: draft.workspace,
      }),
    );
    const transition: DemoTransition = immutableSnapshot({
      transition_id: `${this.#sessionId}-transition-${String(nextSequence).padStart(4, "0")}`,
      sequence: nextSequence,
      workspace: draft.workspace,
      action: draft.action,
      subject_ref: draft.subject_ref,
      canonical_payload_sha256: draft.canonical_payload_sha256,
      previous_state_sha256: previousStateSha256,
      state_sha256: nextStateSha256,
      occurred_at: draft.occurred_at,
      network_invoked: false,
      external_side_effect_allowed: false,
    });
    this.#sequence = nextSequence;
    this.#stateSha256 = nextStateSha256;
    this.#transitionLog.push(transition);
    return transition;
  }

  snapshot(): DemoSessionSnapshot {
    return immutableSnapshot({
      session_id: this.#sessionId,
      scenario_ref: this.#pack.scenario_ref,
      scenario_version: this.#pack.scenario_version,
      scenario_sha256: this.#pack.scenario_sha256,
      opened_at: this.#openedAt,
      expires_at: this.#expiresAt,
      ttl_minutes: SESSION_TTL_MINUTES,
      sequence: this.#sequence,
      state_sha256: this.#stateSha256,
      transition_log: this.#transitionLog,
      ...DEMO_MARKERS,
      real_principal_ref: null,
      real_entitlement_ref: null,
      real_quota_ledger_ref: null,
      real_approval_ref: null,
      real_permit_ref: null,
    });
  }
}
