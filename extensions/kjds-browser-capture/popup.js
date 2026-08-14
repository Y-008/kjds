const PENDING_KEY = "kjdsPendingCapture";
const KJDS_INBOX = "http://127.0.0.1:3000/capture-inbox";

function extractVisibleProduct() {
  const host = location.hostname.toLowerCase();
  const marketplace = host === "1688.com" || host.endsWith(".1688.com")
    ? "1688"
    : host === "ozon.ru" || host.endsWith(".ozon.ru")
      ? "ozon"
      : null;
  if (!marketplace) {
    return { error: "当前页面不是允许的 1688/Ozon 页面" };
  }

  const visibleText = (selectors, max = 12) => {
    for (const selector of selectors) {
      const nodes = Array.from(document.querySelectorAll(selector)).slice(0, max);
      for (const node of nodes) {
        const style = getComputedStyle(node);
        const text = (node.textContent ?? "").replace(/\s+/g, " ").trim();
        if (
          text
          && text.length <= 500
          && style.display !== "none"
          && style.visibility !== "hidden"
        ) {
          return { text, selector };
        }
      }
    }
    return null;
  };
  const meta = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.getAttribute("content");
      if (value?.trim()) return { text: value.trim(), selector };
    }
    return null;
  };
  const numeric = (value) => {
    if (!value) return null;
    const match = value.replace(/\s+/g, "").match(/(\d+(?:[.,]\d+)?)/);
    return match ? match[1].replace(",", ".") : null;
  };
  const jsonLdProducts = Array.from(document.querySelectorAll(
    "script[type='application/ld+json']",
  )).slice(0, 12).flatMap((node) => {
    try {
      const parsed = JSON.parse(node.textContent ?? "null");
      const values = Array.isArray(parsed) ? parsed : [parsed];
      return values.flatMap((value) => {
        if (value?.["@type"] === "Product") return [value];
        if (Array.isArray(value?.["@graph"])) {
          return value["@graph"].filter((item) => item?.["@type"] === "Product");
        }
        return [];
      });
    } catch {
      return [];
    }
  });
  const jsonLdProduct = jsonLdProducts[0] ?? null;

  const canonical = document.querySelector("link[rel='canonical']")
    ?.getAttribute("href") ?? location.href;
  const titleSignal = visibleText(["h1", "[itemprop='name']"], 8)
    ?? meta(["meta[property='og:title']", "meta[name='title']"])
    ?? { text: document.title, selector: "document.title" };
  const priceSignal = meta([
    "meta[property='product:price:amount']",
    "meta[itemprop='price']",
    "meta[name='price']",
  ]) ?? visibleText([
    "[itemprop='price']",
    "[class*='price-text']",
    "[class*='Price--price']",
    "[class~='price']",
    "[class*='price_off']",
    "[id='J_Price']",
    "[id='price']",
    "[class*='price']",
  ], 30);
  const displayedPrice = numeric(priceSignal?.text);
  if (!displayedPrice) {
    return {
      error: "未在当前可见商品页识别到明确价格；没有生成猜测价格",
    };
  }

  const idMatch = marketplace === "1688"
    ? location.href.match(/\/offer\/(\d+)\.html/i)
    : location.href.match(/(?:-|\/)(\d{5,})(?:\/|\?|$)/);
  if (!idMatch) {
    return { error: "未识别到稳定商品 ID；请打开具体商品详情页" };
  }
  const externalItemId = idMatch[1];
  const supplierSignal = meta([
    "meta[name='seller-id']",
    "meta[name='sellerId']",
  ]) ?? visibleText([
    "[data-seller-id]",
    "[class*='companyName']",
    "[class*='shopName']",
    ".company-name",
  ], 16);
  const selectedSignals = Array.from(document.querySelectorAll(
    "[aria-checked='true'],[data-selected='true'],[class~='selected']",
  )).slice(0, 12).map((node) => (
    (node.textContent ?? "").replace(/\s+/g, " ").trim()
  )).filter((text) => text && text.length <= 100);
  const variantKey = selectedSignals.length
    ? selectedSignals.join(" | ")
    : "unselected";
  const visibleSpecifications = {};
  Array.from(document.querySelectorAll("dt")).slice(0, 80).forEach((node) => {
    const style = getComputedStyle(node);
    const key = (node.textContent ?? "").replace(/\s+/g, " ").trim();
    const value = (node.nextElementSibling?.textContent ?? "")
      .replace(/\s+/g, " ").trim();
    if (
      key && value && key.length <= 160 && value.length <= 500
      && style.display !== "none" && style.visibility !== "hidden"
    ) visibleSpecifications[key] = value;
  });
  Array.from(document.querySelectorAll("tr")).slice(0, 80).forEach((row) => {
    const cells = Array.from(row.querySelectorAll("th,td"));
    if (cells.length < 2) return;
    const key = (cells[0].textContent ?? "").replace(/\s+/g, " ").trim();
    const value = (cells[1].textContent ?? "").replace(/\s+/g, " ").trim();
    if (key && value && key.length <= 160 && value.length <= 500) {
      visibleSpecifications[key] = value;
    }
  });
  if (selectedSignals.length) {
    visibleSpecifications.selected_variant = selectedSignals.join(" | ");
  }
  const jsonLdImages = Array.isArray(jsonLdProduct?.image)
    ? jsonLdProduct.image
    : jsonLdProduct?.image ? [jsonLdProduct.image] : [];
  const imageReferences = Array.from(new Set([
    ...jsonLdImages,
    ...Array.from(document.querySelectorAll(
      "img[src],img[data-src],meta[property='og:image']",
    )).slice(0, 80).map((node) => (
      node.getAttribute("content")
      ?? node.getAttribute("data-src")
      ?? node.getAttribute("src")
    )),
  ].flatMap((value) => {
    try {
      const url = new URL(String(value ?? ""), location.href);
      return url.protocol === "https:" ? [url.href] : [];
    } catch {
      return [];
    }
  }))).slice(0, 20);
  const moqSignal = visibleText([
    "[class*='beginAmount']",
    "[class*='moq']",
    "[class*='quantity']",
  ], 12);
  const moq = numeric(moqSignal?.text);
  const observedAt = new Date().toISOString();

  return {
    envelope: {
      contract_version: "kjds-browser-capture-envelope/1.1",
      source_profile: "browser_observation",
      marketplace,
      store_ref: "ozon-primary",
      source_url: location.href,
      observed_at: observedAt,
      idempotency_key: `capture-${crypto.randomUUID()}`,
      page: {
        title: titleSignal.text,
        canonical_url: canonical,
        language: document.documentElement.lang || null,
        extractor_version: "kjds-visible-dom/1.1",
        capture_mode: "active_tab_visible_dom",
      },
      items: [{
        external_item_id: externalItemId,
        supplier_ref: supplierSignal?.text
          ? supplierSignal.text.slice(0, 240)
          : `unresolved:${host}`,
        title: titleSignal.text,
        variant_key: variantKey,
        currency: marketplace === "1688" ? "CNY" : "RUB",
        displayed_price: displayedPrice,
        price_scope: "unit_price",
        price_kind: "public_display_price",
        min_order_quantity: moq ? Number(moq) : null,
        availability: "unknown",
        specifications: visibleSpecifications,
        product_identity: { external_item_id: externalItemId },
        observed_quantity: null,
        checkout_verified: false,
        tax_included: null,
        domestic_freight_included: null,
        purchase_available: false,
        confidence: priceSignal?.selector?.startsWith("meta") ? "0.7" : "0.45",
        supply_signals: {
          title_selector: titleSignal.selector,
          price_selector: priceSignal?.selector ?? "unknown",
          supplier_selector: supplierSignal?.selector ?? "unresolved",
          extraction_authority: "visible_dom_observation_only",
        },
        media_rights_status: "unverified_external_reference",
        image_references: imageReferences,
      }],
      confirmed: true,
    },
  };
}

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
      func: extractVisibleProduct,
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
