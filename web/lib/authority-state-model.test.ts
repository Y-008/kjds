import assert from "node:assert/strict";
import test from "node:test";

import {
  authorityStateView,
  transitionAuthorityState,
  type AuthorityStatus,
} from "./authority-state-model.ts";

test("authority state machine recovers error through retry to success", () => {
  let state: AuthorityStatus = "loading";
  state = transitionAuthorityState(state, { type: "failure" });
  assert.equal(state, "error");
  assert.equal(authorityStateView(state, false).showRetry, true);
  state = transitionAuthorityState(state, { type: "request" });
  assert.equal(state, "loading");
  state = transitionAuthorityState(state, {
    type: "success",
    status: "ready",
  });
  assert.equal(state, "ready");
  assert.equal(authorityStateView(state, true).showRows, true);
});

test("blocked no_data and ready produce distinct executable views", () => {
  assert.deepEqual(
    ["blocked", "no_data", "ready"].map((status) => {
      const view = authorityStateView(status as AuthorityStatus, true);
      return [view.dataState, view.heading, view.showRows];
    }),
    [
      ["blocked", "blocked", true],
      ["no_data", "真实 no_data", false],
      ["ready", "ready", true],
    ],
  );
});
