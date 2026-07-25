import assert from "node:assert/strict";
import test from "node:test";

import { fetchJson } from "./fetch-json.ts";

test("JSON mutations carry the same-origin CSRF request marker", async () => {
  const originalFetch = globalThis.fetch;
  let marker: string | null = null;
  globalThis.fetch = async (_input, init) => {
    marker = new Headers(init?.headers).get("x-kjds-csrf");
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    const response = await fetchJson("/backend/v1/example", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    assert.equal(response.ok, true);
    assert.equal(marker, "same-origin-fetch");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("safe JSON reads do not add the mutation marker", async () => {
  const originalFetch = globalThis.fetch;
  let marker: string | null = "unset";
  globalThis.fetch = async (_input, init) => {
    marker = new Headers(init?.headers).get("x-kjds-csrf");
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    await fetchJson("/backend/v1/example");
    assert.equal(marker, null);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
