import assert from "node:assert/strict";
import test from "node:test";

import {
  channelAccountView,
  transitionChannelAccountState,
  type ChannelAccountViewStatus,
} from "./channel-account-state.ts";

test("channel account error retry reaches a ready exact-scope projection", () => {
  let state: ChannelAccountViewStatus = "loading";
  state = transitionChannelAccountState(state, { type: "failure" });
  assert.equal(channelAccountView(state, 0).showRetry, true);
  assert.equal(channelAccountView(state, 0).domState, "channel-account-error");

  state = transitionChannelAccountState(state, { type: "request" });
  assert.equal(state, "loading");
  state = transitionChannelAccountState(state, {
    type: "success",
    status: "ready",
  });
  assert.equal(channelAccountView(state, 1).showRows, true);
  assert.equal(channelAccountView(state, 1).domState, "channel-account-ready");
});

test("no_data blocked and ready remain distinct executable view states", () => {
  assert.deepEqual(
    (["no_data", "blocked", "ready"] as ChannelAccountViewStatus[]).map(
      (status) => {
        const rows = status === "no_data" ? 0 : 1;
        const view = channelAccountView(status, rows);
        return [view.domState, view.showRows, view.showEmpty, view.heading];
      },
    ),
    [
      ["channel-account-no_data", false, true, "真实 no_data"],
      ["channel-account-blocked", true, false, "失败关闭"],
      ["channel-account-ready", true, false, "Exact-scope 权威可用"],
    ],
  );
});

test("blocked rows stay visible for revocation and fingerprint diagnosis", () => {
  const withBlockedAccount = channelAccountView("blocked", 1);
  const upstreamBlocked = channelAccountView("blocked", 0);
  assert.equal(withBlockedAccount.showRows, true);
  assert.match(withBlockedAccount.detail, /指纹/);
  assert.equal(upstreamBlocked.showEmpty, true);
  assert.match(upstreamBlocked.detail, /历史授权不会回退/);
});

test("a ready filtered empty page is not presented as authority no_data", () => {
  const view = channelAccountView("ready", 0, true);
  assert.equal(view.domState, "channel-account-ready");
  assert.equal(view.heading, "筛选结果为空");
  assert.match(view.detail, /服务端筛选/);
});
