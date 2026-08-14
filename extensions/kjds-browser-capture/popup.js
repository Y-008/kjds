const PENDING_KEY = "kjdsPendingCapture";
const KJDS_INBOX = "http://127.0.0.1:3000/capture-inbox";

document.querySelector("#capture").addEventListener("click", async () => {
  const button = document.querySelector("#capture");
  const status = document.querySelector("#status");
  button.disabled = true;
  status.textContent = "正在读取当前标签页的可见商品字段…";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) throw new Error("没有可采集的当前标签页");
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["extract-page.js"],
    });
    const result = results[0]?.result;
    if (!result?.envelope) {
      throw new Error(result?.error ?? "当前页没有形成可验证商品 envelope");
    }
    await chrome.storage.session.set({ [PENDING_KEY]: result.envelope });
    const url = `${KJDS_INBOX}?extension_id=${encodeURIComponent(chrome.runtime.id)}`;
    await chrome.tabs.create({ url });
    status.textContent = "已打开 KJDS 预检；尚未保存或晋级。";
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "采集失败";
  } finally {
    button.disabled = false;
  }
});