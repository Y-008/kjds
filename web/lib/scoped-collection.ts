export function scopedCollection<T>(
  payload: unknown,
  field: "items" | "products",
): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (
    payload
    && typeof payload === "object"
    && Array.isArray((payload as Record<string, unknown>)[field])
  ) {
    return (payload as Record<string, unknown>)[field] as T[];
  }
  throw new Error(`Scoped collection response is missing ${field}`);
}
