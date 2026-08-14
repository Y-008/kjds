import assert from "node:assert/strict";
import test from "node:test";

import { scopedCollection } from "./scoped-collection.ts";

test("scoped collections read canonical items and products envelopes", () => {
  assert.deepEqual(
    scopedCollection<{ id: string }>({ items: [{ id: "pilot-1" }] }, "items"),
    [{ id: "pilot-1" }],
  );
  assert.deepEqual(
    scopedCollection<{ id: string }>({ products: [{ id: "product-1" }] }, "products"),
    [{ id: "product-1" }],
  );
});

test("scoped collections retain legacy array compatibility and reject drift", () => {
  assert.deepEqual(scopedCollection<number>([1, 2], "items"), [1, 2]);
  assert.throws(
    () => scopedCollection({ status: "no_data" }, "items"),
    /missing items/,
  );
});
