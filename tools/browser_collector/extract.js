/* KJDS 只读采集脚本：识别当前站点并从可见 DOM 提取结构化数据。
   不修改页面、不提交表单、不读取密码/密钥。 */
(function () {
  "use strict";

  function text(el) {
    if (!el) return "";
    return (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  }

  function pick(selectors) {
    for (const s of selectors) {
      const el = document.querySelector(s);
      if (el) return el;
    }
    return null;
  }

  function imgs(limit) {
    const out = [];
    for (const img of document.querySelectorAll("img")) {
      const src = img.src || img.getAttribute("data-src") || "";
      if (src && /^https?:/.test(src) && out.length < limit) out.push(src);
    }
    return out;
  }

  function extract1688Detail() {
    const data = {
      kind: "1688_detail",
      title: text(pick(["h1", ".title-text", "[class*='title-text']"])) || document.title,
      price_hints: [],
      skus: [],
      attributes: [],
      supplier: "",
      images: imgs(8),
    };
    const priceEls = document.querySelectorAll("[class*='price'], [class*='Price'], [class*='offer-price']");
    const seen = new Set();
    for (const el of priceEls) {
      const t = text(el);
      if (t && !seen.has(t)) { seen.add(t); data.price_hints.push(t); }
      if (data.price_hints.length >= 8) break;
    }
    for (const el of document.querySelectorAll("[class*='sku'], [class*='SKU'], .obj-sku, .offer-sku-wrap")) {
      const t = text(el);
      if (t && t.length < 200) data.skus.push(t);
      if (data.skus.length >= 40) break;
    }
    for (const row of document.querySelectorAll(".obj-attrs tr, .attrs-list li, [class*='attrs'] tr, [class*='detail-info'] tr")) {
      const cells = Array.from(row.querySelectorAll("td, th, li, dt, dd")).map(text).filter(Boolean);
      if (cells.length >= 1 && cells.join("|").length < 160) data.attributes.push(cells.join("："));
      if (data.attributes.length >= 60) break;
    }
    data.supplier = text(pick(["[class*='company-name']", "[class*='company']", "[class*='seller-name']", "[class*='shop-name']"]));
    return data;
  }

  function extract1688List() {
    const cards = [];
    for (const li of document.querySelectorAll("li[offerId]")) {
      const body = li.innerHTML;
      const priceEl = li.querySelector(".su-price, [class*='su-price']");
      const cityEl = li.querySelector(".su-city, [class*='su-city']");
      const titleEl = li.querySelector("[class*='sm-offerShopwindow-title'], [class*='title'] a, img[alt]");
      const tradeEl = li.querySelector("[class*='sm-offerShopwindow-trade'], [class*='trade']");
      const rank = li.getAttribute("rank");
      const m = body.match(/alitalk='[^']*"id":"([^"]+)"/);
      const trade = tradeEl ? text(tradeEl) : "";
      const m2 = trade.match(/成交\s*([\d.]+)\s*(台|件|套|个|只|箱|批|双|盒)/);
      cards.push({
        rank: rank ? Number(rank) : null,
        offerId: li.getAttribute("offerId"),
        title: titleEl ? (titleEl.getAttribute("alt") || text(titleEl)) : "",
        price: priceEl ? text(priceEl) : "",
        sales_volume: m2 ? Number(m2[1]) : 0,
        sales_unit: m2 ? m2[2] : "",
        region: cityEl ? text(cityEl) : "",
        shop: m ? m[1] : "",
      });
      if (cards.length >= 120) break;
    }
    const countM = document.body.innerHTML.match(/找到(\d+)[條条]/);
    return { kind: "1688_supply_list", supplier_count: countM ? Number(countM[1]) : 0, cards };
  }

  function extractOzonSearch() {
    const items = [];
    const nodes = document.querySelectorAll("[data-widget='searchResultV2'], [data-widget='searchResultsV2'] [data-widget='searchResultV2']");
    for (const el of nodes) {
      const a = el.querySelector("a[href*='/product/']");
      const priceEl = el.querySelector("[data-widget='webPrice'], [class*='price'], [class*='Price']");
      const titleEl = el.querySelector("[data-widget='searchResultV2Title'], [class*='title'], h3, span");
      const ratingEl = el.querySelector("[class*='rating'], [class*='reviews'], [class*='price'] + div");
      items.push({
        title: titleEl ? text(titleEl).slice(0, 120) : "",
        url: a ? a.href : "",
        price: priceEl ? text(priceEl) : "",
        rating_hint: ratingEl ? text(ratingEl).slice(0, 60) : "",
      });
      if (items.length >= 60) break;
    }
    const bodyText = document.body ? document.body.innerText : "";
    const found = bodyText.match(/Найдено[^0-9]{0,40}(\d[\d\s]{0,12})/i) || bodyText.match(/(\d[\d\s]{1,12})\s+товар/);
    return {
      kind: "ozon_search",
      result_count_hint: found ? found[1].replace(/\s/g, "") : "",
      items,
    };
  }

  function extractOzonProduct() {
    const data = {
      kind: "ozon_product",
      title: text(pick(["h1", "[data-widget='webProductHeading']"])) || document.title,
      price_hints: [],
      characteristics: [],
      seller: "",
      images: imgs(8),
    };
    const priceEls = document.querySelectorAll("[data-widget='webPrice'], [class*='price'], [class*='Price']");
    const seen = new Set();
    for (const el of priceEls) {
      const t = text(el);
      if (t && !seen.has(t)) { seen.add(t); data.price_hints.push(t); }
      if (data.price_hints.length >= 6) break;
    }
    for (const row of document.querySelectorAll("[data-widget='webCharacteristics'] tr, [class*='characteristics'] tr, [class*='short-char'] div")) {
      const cells = Array.from(row.querySelectorAll("td, th, dt, dd, span")).map(text).filter(Boolean);
      if (cells.length >= 1 && cells.join("|").length < 140) data.characteristics.push(cells.join("："));
      if (data.characteristics.length >= 40) break;
    }
    data.seller = text(pick(["[data-widget='webSeller']", "[class*='seller']", "[class*='vendor']"]));
    return data;
  }

  function extractOzonErpBlocks() {
    const bodyText = document.body ? document.body.innerText : "";
    const out = [];
    const blocks = bodyText.split("\n").join(" ").split(/(?=SKU：)/);
    const g = (re) => {
      const m = re.exec(blocks[i]);
      return m ? m[1].trim() : "";
    };
    for (let i = 0; i < blocks.length; i++) {
      if (!blocks[i].includes("SKU：")) continue;
      const sku = g(/SKU：\s*(\d+)/);
      if (!sku) continue;
      out.push({
        sku,
        category: g(/类目：\s*([^|]{2,30})/),
        brand: g(/品牌：\s*([^|]{2,24})/),
        monthly_sales: g(/月销量：\s*([\d.]+)/),
        monthly_revenue_rub: g(/月销售额：\s*([\d.]+)/),
        followers: g(/跟卖列表：\s*([^|]{2,30})/),
        follow_min_cny: g(/跟卖最低价：\s*¥([\d.]+)/),
        follow_min_rub: g(/跟卖最低价：\s*¥[\d.]+\s*\(₽([\d.]+)\)/),
        follow_max_cny: g(/跟卖最高价：\s*¥([\d.]+)/),
        follow_max_rub: g(/跟卖最高价：\s*¥[\d.]+\s*\(₽([\d.]+)\)/),
      });
      if (out.length >= 60) break;
    }
    return out;
  }

  function extract1688Shop() {
    const bodyText = document.body ? document.body.innerText : "";
    const products = [];
    const re = /￥\s*([\d.]+)[\s\S]{0,120}?([^\n]{4,80})[\s\S]{0,60}?(?:已售出|成交)\s*(\d+)\s*笔/g;
    let m;
    const seen = new Set();
    while ((m = re.exec(bodyText)) !== null && products.length < 60) {
      const title = m[2].replace(/立即下单/g, "").trim();
      const key = m[1] + "|" + title;
      if (seen.has(key)) continue;
      seen.add(key);
      products.push({ price_cny: Number(m[1]), title, sales_volume: Number(m[3]) });
    }
    if (products.length === 0) {
      const re2 = /￥\s*([\d.]+)[\s\S]{0,120}?([^\n]{4,80})/g;
      while ((m = re2.exec(bodyText)) !== null && products.length < 60) {
        const title = m[2].replace(/立即下单/g, "").trim();
        products.push({ price_cny: Number(m[1]), title, sales_volume: 0 });
      }
    }
    return { kind: "1688_shop", products };
  }

  function extractGeneric() {
    return {
      kind: "generic",
      note: "非 1688/Ozon 结构化页面，仅存可见文本前 30k 字符",
      text: (document.body ? document.body.innerText : "").slice(0, 30000),
      links: document.querySelectorAll("a[href]").length,
      images: imgs(4),
    };
  }

  function extract() {
    const host = location.host || "";
    const base = {
      url: location.href,
      title: document.title,
      captured_at: new Date().toISOString(),
      host,
    };
    let data;
    if (host.includes("1688.com")) {
      if (/\/offer\/\d+/.test(location.pathname) || /detail\.1688\.com/.test(host)) {
        data = extract1688Detail();
      } else if (/\/item\/-/.test(location.pathname) || /tw\.1688\.com/.test(host)) {
        data = extract1688List();
      } else if (/shop\d/.test(host) || /\/shop/.test(location.pathname)) {
        data = extract1688Shop();
      } else {
        data = extractGeneric();
      }
    } else if (host.includes("ozon.ru")) {
      if (/^seller\./.test(host)) {
        data = { kind: "ozon_seller", note: "卖家后台页面（不采集 API 密钥等敏感字段）", heading: (document.body ? document.body.innerText : "").slice(0, 5000) };
      } else if (/\/product\//.test(location.pathname)) {
        data = extractOzonProduct();
        const erp = extractOzonErpBlocks();
        if (erp.length) data.erp_blocks = erp;
      } else if (/\/search\//.test(location.pathname) || /\/category\//.test(location.pathname)) {
        data = extractOzonSearch();
        const erp = extractOzonErpBlocks();
        if (erp.length) data.erp_blocks = erp;
      } else {
        data = extractGeneric();
        const erp = extractOzonErpBlocks();
        if (erp.length) data.erp_blocks = erp;
      }
    } else {
      data = extractGeneric();
    }
    return Object.assign(base, { site: host.includes("1688.com") ? "1688" : host.includes("ozon.ru") ? "ozon" : "other", data });
  }

  if (typeof window.__kjdsExtract !== "function") {
    window.__kjdsExtract = extract;
    window.__kjdsExtractLoaded = true;
    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (msg && msg.type === "capture") {
        try {
          sendResponse({ ok: true, payload: extract() });
        } catch (e) {
          sendResponse({ ok: false, error: String(e && e.message ? e.message : e) });
        }
        return true;
      }
      return false;
    });
  }
  return window.__kjdsExtract();
})();
