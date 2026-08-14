import {
  FORBIDDEN_SCOPE_KEYS,
  LocalDemoDomainError,
  type JsonValue,
} from "../domain/contracts.ts";

const FORBIDDEN_INPUT_KEYS = new Set<string>([
  ...FORBIDDEN_SCOPE_KEYS,
  ["access", "token"].join("_"),
  ["refresh", "token"].join("_"),
  ["client", "secret"].join("_"),
  "password",
  "authorization",
  "browser_profile",
  "channel_credentials",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function assertExactInputKeys(
  value: unknown,
  allowedKeys: readonly string[],
): asserts value is Record<string, unknown> {
  if (!isRecord(value)) {
    throw new LocalDemoDomainError("demo_request_invalid", 400);
  }
  const allowed = new Set(allowedKeys);
  for (const key of Object.keys(value)) {
    if (FORBIDDEN_INPUT_KEYS.has(key)) {
      throw new LocalDemoDomainError("demo_scope_override_rejected", 400);
    }
    if (!allowed.has(key)) {
      throw new LocalDemoDomainError("demo_request_invalid", 400);
    }
  }
}

export function assertOfflineJsonPayload(
  value: unknown,
  path = "payload",
): asserts value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new LocalDemoDomainError("demo_payload_invalid", 400);
    }
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((child, index) =>
      assertOfflineJsonPayload(child, `${path}[${index}]`),
    );
    return;
  }
  if (isRecord(value)) {
    for (const [key, child] of Object.entries(value)) {
      if (FORBIDDEN_INPUT_KEYS.has(key)) {
        throw new LocalDemoDomainError("demo_scope_override_rejected", 400);
      }
      assertOfflineJsonPayload(child, `${path}.${key}`);
    }
    return;
  }
  throw new LocalDemoDomainError(`demo_payload_invalid:${path}`, 400);
}

export function denyNetworkRequest(_request: unknown): never {
  throw new LocalDemoDomainError("demo_network_forbidden", 400);
}
