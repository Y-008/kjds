import {
  LocalDemoDomainError,
  type DemoSessionSnapshot,
} from "../domain/contracts.ts";
import { DemoSession } from "../domain/demo-session.ts";

export interface StoredReplay<T = unknown> {
  readonly fingerprint_sha256: string;
  readonly response: T;
}

interface StoredSessionRecord {
  readonly owner_scope_sha256: string;
  readonly session: DemoSession;
  readonly replays: Map<string, StoredReplay>;
}

export class InMemorySessionStore {
  readonly #sessions = new Map<string, StoredSessionRecord>();

  create(ownerScopeSha256: string, session: DemoSession): DemoSessionSnapshot {
    const snapshot = session.snapshot();
    if (this.#sessions.has(snapshot.session_id)) {
      throw new LocalDemoDomainError("demo_session_conflict", 409);
    }
    this.#sessions.set(snapshot.session_id, {
      owner_scope_sha256: ownerScopeSha256,
      session,
      replays: new Map(),
    });
    return snapshot;
  }

  find(ownerScopeSha256: string, sessionId: string): DemoSession | undefined {
    const record = this.#sessions.get(sessionId);
    if (!record || record.owner_scope_sha256 !== ownerScopeSha256) {
      return undefined;
    }
    return record.session;
  }

  getReplay<T>(
    ownerScopeSha256: string,
    sessionId: string,
    idempotencyKeySha256: string,
  ): StoredReplay<T> | undefined {
    const record = this.#sessions.get(sessionId);
    if (!record || record.owner_scope_sha256 !== ownerScopeSha256) {
      return undefined;
    }
    return record.replays.get(idempotencyKeySha256) as StoredReplay<T> | undefined;
  }

  putReplay<T>(
    ownerScopeSha256: string,
    sessionId: string,
    idempotencyKeySha256: string,
    replay: StoredReplay<T>,
  ): void {
    const record = this.#sessions.get(sessionId);
    if (!record || record.owner_scope_sha256 !== ownerScopeSha256) {
      throw new LocalDemoDomainError("demo_session_not_found", 404);
    }
    if (record.replays.has(idempotencyKeySha256)) {
      throw new LocalDemoDomainError("demo_idempotency_record_conflict", 409);
    }
    record.replays.set(idempotencyKeySha256, replay);
  }

  delete(ownerScopeSha256: string, sessionId: string): DemoSessionSnapshot | undefined {
    const record = this.#sessions.get(sessionId);
    if (!record || record.owner_scope_sha256 !== ownerScopeSha256) {
      return undefined;
    }
    const snapshot = record.session.snapshot();
    this.#sessions.delete(sessionId);
    return snapshot;
  }
}
