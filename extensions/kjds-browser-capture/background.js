const PENDING_KEY = "kjdsPendingCapture";
const ALLOWED_KJDS_ORIGINS = new Set([
  "http://127.0.0.1:3000",
  "http://localhost:3000",
]);

chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  let senderOrigin;
  try {
    senderOrigin = new URL(sender.url ?? "").origin;
  } catch {
    sendResponse({ ok: false, error: "invalid_sender" });
    return false;
  }
  if (!ALLOWED_KJDS_ORIGINS.has(senderOrigin)) {
    sendResponse({ ok: false, error: "sender_not_allowed" });
    return false;
  }
  if (message?.type === "KJDS_CAPTURE_PEEK") {
    chrome.storage.session.get(PENDING_KEY).then((value) => {
      sendResponse({
        ok: true,
        envelope: value[PENDING_KEY] ?? null,
      });
    }).catch(() => {
      sendResponse({ ok: false, error: "session_read_failed" });
    });
    return true;
  }
  if (message?.type === "KJDS_CAPTURE_ACK") {
    chrome.storage.session.get(PENDING_KEY).then(async (value) => {
      const pending = value[PENDING_KEY];
      if (!pending || pending.idempotency_key !== message.idempotency_key) {
        sendResponse({ ok: false, error: "capture_ack_mismatch" });
        return;
      }
      await chrome.storage.session.remove(PENDING_KEY);
      sendResponse({ ok: true, cleared: true });
    }).catch(() => {
      sendResponse({ ok: false, error: "session_clear_failed" });
    });
    return true;
  }
  sendResponse({ ok: false, error: "unknown_message" });
  return false;
});
