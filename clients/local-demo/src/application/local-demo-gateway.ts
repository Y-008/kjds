import {
  DEMO_ACTION_CONTRACTS,
  DEMO_CONTRACT_VERSION,
  DEMO_MARKERS,
  LocalDemoDomainError,
  type DemoSessionSnapshot,
  type DemoAction,
  type DemoSubjectKind,
  type DemoTransition,
  type DemoWorkspace,
  type JsonValue,
  type ScenarioPack,
} from "../domain/contracts.ts";
import { DemoSession } from "../domain/demo-session.ts";
import {
  canonicalJson,
  deterministicTimestamp,
  sha256Hex,
} from "../domain/scenario-pack.ts";
import { InMemorySessionStore } from "./in-memory-session-store.ts";
import {
  assertExactInputKeys,
  assertOfflineJsonPayload,
} from "./network-policy.ts";
import {
  deriveWorkspaceReadModel,
  latestActionForSubject,
} from "./transition-read-model.ts";

const WORKSPACES = new Set<DemoWorkspace>([
  "dashboard",
  "sourcing",
  "pim",
  "listings",
  "oms",
  "fulfillment",
  "customer_service",
  "growth",
  "profit",
]);

const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{8,128}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const CURSOR_PATTERN = /^demo-cursor-(\d+)$/;
const PAGE_SIZE = 20;

export interface DemoErrorView {
  readonly code: string;
  readonly http_status: number;
}

export interface DemoEnvelope<T> {
  readonly demo: true;
  readonly synthetic: true;
  readonly non_billable: true;
  readonly external_side_effect_allowed: false;
  readonly real_principal_ref: null;
  readonly real_entitlement_ref: null;
  readonly real_quota_ledger_ref: null;
  readonly real_approval_ref: null;
  readonly real_permit_ref: null;
  readonly contract_version: typeof DEMO_CONTRACT_VERSION;
  readonly session_id: string | null;
  readonly scenario_ref: string | null;
  readonly scenario_version: string | null;
  readonly scenario_sha256: string | null;
  readonly sequence: number;
  readonly state_sha256: string;
  readonly generated_at: string;
  readonly network_invoked: false;
  readonly data: T | null;
  readonly error: DemoErrorView | null;
}

interface GatewayDependencies {
  readonly store?: InMemorySessionStore;
  readonly gateway_scope_token?: string;
  readonly session_id_factory?: () => string;
  readonly uuid_factory?: () => string;
}

export interface WorkspaceQueryView {
  readonly workspace: DemoWorkspace;
  readonly items: readonly JsonValue[];
  readonly summary: JsonValue;
  readonly next_cursor: string | null;
  readonly read_model_sha256: string;
}

export interface ApplyView {
  readonly transition: DemoTransition;
  readonly replayed: boolean;
}

interface ResetView {
  readonly reset: true;
}

function deepFreeze<T>(value: T): T {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) {
    return value;
  }
  Object.freeze(value);
  for (const child of Object.values(value)) {
    deepFreeze(child);
  }
  return value;
}

function domainError(operation: () => void): LocalDemoDomainError | null {
  try {
    operation();
    return null;
  } catch (error) {
    if (error instanceof LocalDemoDomainError) {
      return error;
    }
    throw error;
  }
}

function defaultUuidFactory(): string {
  const randomUuid = globalThis.crypto?.randomUUID;
  if (typeof randomUuid !== "function") {
    throw new LocalDemoDomainError("demo_uuid_factory_unavailable", 500);
  }
  return randomUuid.call(globalThis.crypto);
}

function jsonObject(value: JsonValue): Record<string, JsonValue> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value
    : {};
}

export class LocalDemoGateway {
  readonly #pack: ScenarioPack;
  readonly #store: InMemorySessionStore;
  readonly #ownerScopeSha256: string;
  readonly #sessionIdFactory: () => string;
  readonly #knownSubjectKinds: Map<string, DemoSubjectKind>;

  constructor(pack: ScenarioPack, dependencies: GatewayDependencies = {}) {
    this.#pack = pack;
    this.#store = dependencies.store ?? new InMemorySessionStore();
    const uuidFactory = dependencies.uuid_factory ?? defaultUuidFactory;
    const scopeToken = dependencies.gateway_scope_token ?? uuidFactory();
    this.#ownerScopeSha256 = sha256Hex(`local-demo-gateway:${scopeToken}`);
    this.#sessionIdFactory =
      dependencies.session_id_factory ??
      (() => `demo-session-${uuidFactory().toLowerCase()}`);
    this.#knownSubjectKinds = new Map([
      ...pack.workspace_projections.stores.map((item) => [item.store_id, "store"] as const),
      ...pack.workspace_projections.skus.map((item) => [item.sku_id, "sku"] as const),
      ...pack.workspace_projections.orders.map((item) => [item.order_id, "order"] as const),
    ]);
  }

  open_session(input: unknown): DemoEnvelope<DemoSessionSnapshot> {
    const validationError = domainError(() => {
      assertExactInputKeys(input, ["scenario_ref", "locale"]);
      if (
        input.scenario_ref !== this.#pack.scenario_ref ||
        input.locale !== this.#pack.locale
      ) {
        throw new LocalDemoDomainError("demo_scenario_not_found", 404);
      }
    });
    if (validationError) {
      return this.#errorEnvelope(null, null, validationError);
    }
    const session = new DemoSession(this.#pack, this.#sessionIdFactory());
    const snapshot = this.#store.create(this.#ownerScopeSha256, session);
    return this.#successEnvelope(snapshot, snapshot);
  }

  query(input: unknown): DemoEnvelope<WorkspaceQueryView> {
    const validationError = domainError(() => {
      assertExactInputKeys(input, ["session_id", "workspace", "cursor"]);
      if (
        typeof input.session_id !== "string" ||
        typeof input.workspace !== "string" ||
        !WORKSPACES.has(input.workspace as DemoWorkspace) ||
        !(
          input.cursor === undefined ||
          input.cursor === null ||
          typeof input.cursor === "string"
        )
      ) {
        throw new LocalDemoDomainError("demo_request_invalid", 400);
      }
    });
    if (validationError) {
      return this.#errorEnvelope(null, this.#requestedSessionId(input), validationError);
    }
    const request = input as {
      session_id: string;
      workspace: DemoWorkspace;
      cursor?: string | null;
    };
    const session = this.#store.find(this.#ownerScopeSha256, request.session_id);
    if (!session) {
      return this.#notFoundEnvelope(request.session_id);
    }
    const snapshot = session.snapshot();
    const cursorResult = this.#decodeCursor(request.cursor);
    if (cursorResult instanceof LocalDemoDomainError) {
      return this.#errorEnvelope(snapshot, request.session_id, cursorResult);
    }
    const projection = deriveWorkspaceReadModel(
      this.#pack,
      snapshot.transition_log,
      request.workspace,
    );
    const page = projection.items.slice(cursorResult, cursorResult + PAGE_SIZE);
    const nextOffset = cursorResult + page.length;
    const view: WorkspaceQueryView = deepFreeze({
      workspace: request.workspace,
      items: structuredClone(page) as JsonValue[],
      summary: structuredClone(projection.summary),
      next_cursor:
        nextOffset < projection.items.length ? `demo-cursor-${nextOffset}` : null,
      read_model_sha256: sha256Hex(canonicalJson(projection.read_model_sha256_input)),
    });
    return this.#successEnvelope(snapshot, view);
  }

  apply(input: unknown): DemoEnvelope<ApplyView> {
    const validationError = domainError(() => {
      assertExactInputKeys(input, [
        "session_id",
        "action",
        "subject_ref",
        "payload",
        "idempotency_key",
        "expected_state_sha256",
      ]);
      if (
        typeof input.session_id !== "string" ||
        typeof input.action !== "string" ||
        !(input.action in DEMO_ACTION_CONTRACTS) ||
        typeof input.subject_ref !== "string" ||
        this.#knownSubjectKinds.get(input.subject_ref) !==
          DEMO_ACTION_CONTRACTS[input.action as DemoAction].subject_kind ||
        typeof input.idempotency_key !== "string" ||
        !IDEMPOTENCY_KEY_PATTERN.test(input.idempotency_key) ||
        !(
          input.expected_state_sha256 === undefined ||
          (typeof input.expected_state_sha256 === "string" &&
            SHA256_PATTERN.test(input.expected_state_sha256))
        )
      ) {
        throw new LocalDemoDomainError("demo_request_invalid", 400);
      }
      assertOfflineJsonPayload(input.payload);
    });
    if (validationError) {
      return this.#errorEnvelope(null, this.#requestedSessionId(input), validationError);
    }
    const request = input as {
      session_id: string;
      action: DemoAction;
      subject_ref: string;
      payload: JsonValue;
      idempotency_key: string;
      expected_state_sha256?: string;
    };
    const session = this.#store.find(this.#ownerScopeSha256, request.session_id);
    if (!session) {
      return this.#notFoundEnvelope(request.session_id);
    }
    const fingerprintSha256 = sha256Hex(
      canonicalJson({
        action: request.action,
        expected_state_sha256: request.expected_state_sha256 ?? null,
        payload: request.payload,
        subject_ref: request.subject_ref,
      }),
    );
    const idempotencyKeySha256 = sha256Hex(request.idempotency_key);
    const replay = this.#store.getReplay<DemoEnvelope<ApplyView>>(
      this.#ownerScopeSha256,
      request.session_id,
      idempotencyKeySha256,
    );
    if (replay) {
      if (replay.fingerprint_sha256 !== fingerprintSha256) {
        return this.#errorEnvelope(
          session.snapshot(),
          request.session_id,
          new LocalDemoDomainError("demo_idempotency_payload_drift", 409),
        );
      }
      return replay.response;
    }
    const before = session.snapshot();
    if (this.#pack.scenario_version === "v2" && request.expected_state_sha256 === undefined) {
      return this.#errorEnvelope(
        before,
        request.session_id,
        new LocalDemoDomainError("demo_expected_state_required", 400),
      );
    }
    if (
      request.expected_state_sha256 !== undefined &&
      request.expected_state_sha256 !== before.state_sha256
    ) {
      return this.#errorEnvelope(
        before,
        request.session_id,
        new LocalDemoDomainError("demo_expected_state_mismatch", 409),
      );
    }
    const preconditionError = this.#transitionPrecondition(
      before,
      request.action,
      request.subject_ref,
      request.payload,
    );
    if (preconditionError) {
      return this.#errorEnvelope(before, request.session_id, preconditionError);
    }
    const nextSequence = before.sequence + 1;
    let transition: DemoTransition;
    try {
      transition = session.appendTransition({
        workspace: DEMO_ACTION_CONTRACTS[request.action].workspace,
        action: request.action,
        subject_ref: request.subject_ref,
        canonical_payload_sha256: fingerprintSha256,
        canonical_payload: request.payload,
        occurred_at: deterministicTimestamp(this.#pack, nextSequence),
      });
    } catch (error) {
      if (error instanceof LocalDemoDomainError) {
        return this.#errorEnvelope(session.snapshot(), request.session_id, error);
      }
      throw error;
    }
    const response = this.#successEnvelope(session.snapshot(), {
      transition,
      replayed: false,
    });
    this.#store.putReplay(
      this.#ownerScopeSha256,
      request.session_id,
      idempotencyKeySha256,
      { fingerprint_sha256: fingerprintSha256, response },
    );
    return response;
  }

  reset(input: unknown): DemoEnvelope<ResetView> {
    const validationError = domainError(() => {
      assertExactInputKeys(input, ["session_id"]);
      if (typeof input.session_id !== "string") {
        throw new LocalDemoDomainError("demo_request_invalid", 400);
      }
    });
    if (validationError) {
      return this.#errorEnvelope(null, this.#requestedSessionId(input), validationError);
    }
    const request = input as { session_id: string };
    const snapshot = this.#store.delete(this.#ownerScopeSha256, request.session_id);
    if (!snapshot) {
      return this.#notFoundEnvelope(request.session_id);
    }
    return this.#successEnvelope(snapshot, { reset: true });
  }

  #transitionPrecondition(
    snapshot: DemoSessionSnapshot,
    action: DemoAction,
    subjectRef: string,
    payload: JsonValue,
  ): LocalDemoDomainError | null {
    if (this.#pack.scenario_version !== "v2") return null;
    const previousBySubject: Partial<Record<DemoAction, DemoAction>> = {
      prepare_product_content: "advance_sourcing",
      generate_listing_preview: "prepare_product_content",
      advance_fulfillment: "advance_order_timeline",
      simulate_return_exception: "advance_fulfillment",
      assign_synthetic_fee: "allocate_settlement",
      recalculate_synthetic_profit: "assign_synthetic_fee",
    };
    const expectedAction = previousBySubject[action];
    if (expectedAction && latestActionForSubject(snapshot.transition_log, subjectRef) !== expectedAction) {
      return new LocalDemoDomainError("demo_action_precondition_failed", 409);
    }
    if (action === "reserve_inventory") {
      const orderRef = jsonObject(payload).order_ref;
      const order = this.#pack.workspace_projections.orders.find(
        (item) => item.order_id === orderRef && item.sku_id === subjectRef,
      );
      if (
        !order ||
        latestActionForSubject(snapshot.transition_log, order.order_id) !==
          "advance_order_timeline"
      ) {
        return new LocalDemoDomainError("demo_action_precondition_failed", 409);
      }
    }
    return null;
  }

  #decodeCursor(cursor: string | null | undefined): number | LocalDemoDomainError {
    if (cursor === undefined || cursor === null) {
      return 0;
    }
    const match = CURSOR_PATTERN.exec(cursor);
    if (!match) {
      return new LocalDemoDomainError("demo_cursor_invalid", 400);
    }
    const offsetText = match[1];
    if (offsetText === undefined) {
      return new LocalDemoDomainError("demo_cursor_invalid", 400);
    }
    const offset = Number(offsetText);
    if (!Number.isSafeInteger(offset) || offset < 0) {
      return new LocalDemoDomainError("demo_cursor_invalid", 400);
    }
    return offset;
  }

  #requestedSessionId(input: unknown): string | null {
    if (typeof input === "object" && input !== null && !Array.isArray(input)) {
      const sessionId = (input as Record<string, unknown>).session_id;
      if (typeof sessionId === "string") {
        return sessionId;
      }
    }
    return null;
  }

  #notFoundEnvelope(sessionId: string): DemoEnvelope<never> {
    return this.#errorEnvelope(
      null,
      sessionId,
      new LocalDemoDomainError("demo_session_not_found", 404),
    );
  }

  #successEnvelope<T>(snapshot: DemoSessionSnapshot, data: T): DemoEnvelope<T> {
    return this.#envelope(snapshot, snapshot.session_id, data, null);
  }

  #errorEnvelope(
    snapshot: DemoSessionSnapshot | null,
    sessionId: string | null,
    error: LocalDemoDomainError,
  ): DemoEnvelope<never> {
    return this.#envelope<never>(snapshot, sessionId, null, {
      code: error.code,
      http_status: error.http_status,
    });
  }

  #envelope<T>(
    snapshot: DemoSessionSnapshot | null,
    sessionId: string | null,
    data: T | null,
    error: DemoErrorView | null,
  ): DemoEnvelope<T> {
    const sequence = snapshot?.sequence ?? 0;
    return deepFreeze({
      ...DEMO_MARKERS,
      real_principal_ref: null,
      real_entitlement_ref: null,
      real_quota_ledger_ref: null,
      real_approval_ref: null,
      real_permit_ref: null,
      contract_version: DEMO_CONTRACT_VERSION,
      session_id: sessionId,
      scenario_ref: snapshot?.scenario_ref ?? null,
      scenario_version: snapshot?.scenario_version ?? null,
      scenario_sha256: snapshot?.scenario_sha256 ?? null,
      sequence,
      state_sha256:
        snapshot?.state_sha256 ??
        sha256Hex(
          canonicalJson({
            error_code: error?.code ?? "demo_unknown_error",
            session_id: sessionId,
          }),
        ),
      generated_at: deterministicTimestamp(this.#pack, sequence),
      network_invoked: false,
      data,
      error,
    });
  }
}
