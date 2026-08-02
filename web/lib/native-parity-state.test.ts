import assert from "node:assert/strict";
import test from "node:test";
import { nativeParityView, stateLabel } from "./native-parity-state.ts";

test("native parity view keeps no-data and filtered-empty distinct", () => {
  assert.equal(nativeParityView("no_data", 0, false), "no_data");
  assert.equal(nativeParityView("ready", 0, true), "filtered_empty");
  assert.equal(nativeParityView("ready", 2, false), "ready");
  assert.equal(nativeParityView("error", 2, false), "error");
});

test("acceptance state labels do not equate mapping with verification", () => {
  assert.equal(stateLabel("mapped"), "仅完成映射");
  assert.equal(stateLabel("verified_native"), "原生验证通过");
});
