const PENDING_KEY = "kjdsPendingCapture";
const KJDS_INBOX = "http://127.0.0.1:3000/capture-inbox";

async function readCurrentPage() {
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
  return result;
}

document.querySelector("#capture").addEventListener("click", async () => {
  const button = document.querySelector("#capture");
  const status = document.querySelector("#status");
  button.disabled = true;
  status.textContent = "正在读取当前标签页的可见商品字段…";
  try {
    const result = await readCurrentPage();
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

document.querySelector("#search-similar").addEventListener("click", async () => {
  const button = document.querySelector("#search-similar");
  const status = document.querySelector("#status");
  button.disabled = true;
  status.textContent = "正在读取当前商品标题并打开 1688 同类搜索…";
  try {
    const result = await readCurrentPage();
    const keyword = String(result.search_seed ?? result.envelope.page.title ?? "")
      .replace(/\s+/g, " ").trim().slice(0, 120);
    if (!keyword) throw new Error("当前页没有可用于搜索的商品标题");
    const url = `https://s.1688.com/selloffer/offer_search.htm?keywords=${encodeURIComponent(keyword)}`;
    await chrome.tabs.create({ url });
    status.textContent = "已打开 1688 搜索；在结果页再次点击采集即可进入候选比价。";
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "同类搜索失败";
  } finally {
    button.disabled = false;
  }
});
