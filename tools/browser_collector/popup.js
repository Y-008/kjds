"use strict";

const COLLECTOR = "http://127.0.0.1:8123/capture";
const statusEl = document.getElementById("status");

function setStatus(text, isErr) {
  statusEl.className = isErr ? "err" : "ok";
  statusEl.textContent = text;
}

chrome.storage.local.get({ autoCapture: false }, (opts) => {
  document.getElementById("auto").checked = opts.autoCapture;
});
chrome.storage.local.get({ pageEnhance: true }, (opts) => {
  document.getElementById("enhance").checked = opts.pageEnhance;
});

document.getElementById("auto").addEventListener("change", (e) => {
  chrome.storage.local.set({ autoCapture: e.target.checked }, () => {
    setStatus(e.target.checked ? "自动采集已开启：新打开的 1688/Ozon 页面加载后会自动采集。" : "自动采集已关闭。");
  });
});

document.getElementById("enhance").addEventListener("change", (e) => {
  chrome.storage.local.set({ pageEnhance: e.target.checked }, () => {
    setStatus(e.target.checked ? "页面增强已开启：Ozon 页面将显示 KJDS 数据卡。" : "页面增强已关闭。");
  });
});

document.getElementById("capture").addEventListener("click", async () => {
  setStatus("采集中…");
  let tab;
  try {
    [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  } catch (e) {
    setStatus("无法读取当前标签：" + e.message, true);
    return;
  }
  if (!tab || !tab.id) { setStatus("无活动标签", true); return; }
  let payload = null;
  try {
    const resp = await chrome.tabs.sendMessage(tab.id, { type: "capture" });
    payload = resp && resp.payload ? resp.payload : null;
  } catch (_) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["extract.js"] });
      const resp = await chrome.tabs.sendMessage(tab.id, { type: "capture" });
      payload = resp && resp.payload ? resp.payload : null;
    } catch (e2) {
      setStatus("无法注入采集脚本（页面可能不支持）：" + e2.message, true);
      return;
    }
  }
  if (!payload) { setStatus("页面未返回数据（可能不是 1688/Ozon 页面）", true); return; }
  const kind = payload.data && payload.data.kind ? payload.data.kind : "generic";
  try {
    const resp = await fetch(COLLECTOR, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const out = await resp.json();
    if (out && out.ok) {
      setStatus("已保存：" + out.file + "\n类型：" + kind + "\n页面：" + payload.title.slice(0, 60));
    } else {
      setStatus("本地服务返回异常：" + JSON.stringify(out), true);
    }
  } catch (e) {
    setStatus("本地采集服务未启动：请运行 collector.py（127.0.0.1:8123）。\n错误：" + e.message, true);
  }
});
