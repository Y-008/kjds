import assert from "node:assert/strict";
import test from "node:test";

import {
  transitionWarehouseState,
  warehouseView,
  type WarehouseStatus,
} from "./warehouse-fulfillment-state.ts";

test("warehouse error retry succeeds through executable state transitions", () => {
  let state: WarehouseStatus = "loading";
  state = transitionWarehouseState(state, { type: "failure" });
  assert.equal(warehouseView(state, 0).showRetry, true);
  assert.equal(warehouseView(state, 0).domState, "warehouse-error");
  state = transitionWarehouseState(state, { type: "request" });
  assert.equal(state, "loading");
  state = transitionWarehouseState(state, {
    type: "success",
    status: "ready",
  });
  assert.equal(warehouseView(state, 1).showRows, true);
  assert.equal(warehouseView(state, 1).domState, "warehouse-ready");
});

test("warehouse blocked no_data and ready expose distinct DOM models", () => {
  assert.deepEqual(
    (["blocked", "no_data", "ready"] as WarehouseStatus[]).map(
      (status) => {
        const view = warehouseView(status, status === "ready" ? 1 : 0);
        return [
          view.domState,
          view.showRows,
          Boolean(view.emptyMessage),
        ];
      },
    ),
    [
      ["warehouse-blocked", false, true],
      ["warehouse-no_data", false, true],
      ["warehouse-ready", true, false],
    ],
  );
});
