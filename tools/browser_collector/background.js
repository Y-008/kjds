/* KJDS 采集器后台：自动采集模式 + 数据投递到本地收集服务。 */
"use strict";

const COLLECTOR = "http://127.0.0.1:8123/capture";

async function deliver(payload) {
  try {
    const resp = await fetch(COLLECTOR, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const text = await resp.text();
    return { ok: resp.ok, status: resp.status, body: text.slice(0, 300) };
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "deliver") {
    deliver(msg.payload).then(sendResponse);
    return true;
  }
  if (msg && msg.type === "capture_auto") {
    const tabId = msg.tabId;
    if (!tabId) { sendResponse({ ok: false, error: "no tab" }); return false; }
    chrome.tabs
      .sendMessage(tabId, { type: "capture" })
      .then((resp) => {
        if (resp && resp.payload) return deliver(resp.payload);
        return { ok: false, error: resp && resp.error ? resp.error : "no payload" };
      })
      .then(sendResponse);
    return true;
  }
  return false;
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;
  const url = tab.url || "";
  if (!/1688\.com|ozon\.ru/.test(url)) return;
  chrome.storage.local.get({ autoCapture: false }, (opts) => {
    if (!opts.autoCapture) return;
    setTimeout(() => {
      chrome.tabs
        .sendMessage(tabId, { type: "capture" })
        .then((resp) => {
          if (resp && resp.payload) return deliver(resp.payload);
          return null;
        })
        .catch(() => {});
    }, 2500);
  });
});
