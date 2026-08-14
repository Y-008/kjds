/* KJDS 页面增强：在 Ozon 市场页 / 卖家后台注入本地数据卡（只读显示，不改动页面数据）。 */
(function () {
  "use strict";
  const HUB = "http://127.0.0.1:8123";
  let enabled = true;
  chrome.storage.local.get({ pageEnhance: true }, (o) => {
    enabled = !!o.pageEnhance;
    if (enabled) start();
  });
  chrome.storage.onChanged.addListener((ch, area) => {
    if (area === "local" && ch.pageEnhance) {
      enabled = !!ch.pageEnhance.newValue;
      if (enabled) start();
    }
  });

  async function fetchJson(path) {
    try {
      const r = await fetch(HUB + path, { cache: "no-store" });
      return await r.json();
    } catch (_) {
      return null;
    }
  }

  function badge(html, accent) {
    const div = document.createElement("div");
    div.className = "kjds-badge";
    div.style.cssText =
      "margin:4px 0;padding:4px 6px;border-left:3px solid " +
      (accent || "#1a7f37") +
      ";background:#f0fdf4;color:#14532d;font-size:11px;line-height:1.45;border-radius:4px;font-family:'Microsoft YaHei',Arial,sans-serif;";
    div.innerHTML = html;
    return div;
  }

  function firstPriceRub(text) {
    const m = String(text || "").match(/(\d[\d\s\u00a0]{2,12})\s*₽/);
    return m ? Number(m[1].replace(/[\s\u00a0]/g, "")) : null;
  }

  function supplyLine(s, margin) {
    const p = s.price_median;
    const rub = p ? Math.round(p * 12.8) : 0;
    const region = s.top_regions && s.top_regions[0] ? s.top_regions[0].region : "";
    let html =
      "<b>KJDS</b> 1688同款: ¥" +
      p.toFixed(0) +
      " (₽" +
      rub +
      ") · " +
      s.supplier_count +
      "家 · " +
      region;
    const top = s.top_sold && s.top_sold[0];
    if (top && top.volume > 0) html += "<br>成交王: " + top.title.slice(0, 36) + " (" + top.volume + "件)";
    if (margin && margin.net_rub !== undefined) {
      html +=
        "<br>参考毛利: ₽" +
        margin.net_rub +
        " (" +
        margin.net_margin_pct +
        "%) [采购₽" +
        margin.purchase_rub +
        " 物流₽" +
        margin.logistics_rub +
        " 费₽" +
        margin.fees_rub +
        "]";
    }
    return html;
  }

  async function injectMarketCard(card) {
    if (card.querySelector(".kjds-badge")) return;
    const titleEl = card.querySelector("a[href*='/product/']");
    const title = (titleEl ? titleEl.textContent : "") || (card.innerText || "").slice(0, 90);
    if (!title || title.length < 8) return;
    const priceRub = firstPriceRub(card.innerText);
    const cat = extractCat(card);
    const path =
      "/data/match?q=" +
      encodeURIComponent(title) +
      (cat ? "&cat=" + encodeURIComponent(cat) : "") +
      (priceRub ? "&price_rub=" + priceRub : "");
    const m = await fetchJson(path);
    if (!m || !m.matched) return;
    const b = badge(supplyLine(m.supply, m.margin), "#1a7f37");
    b.setAttribute("data-kjds", "market");
    card.appendChild(b);
  }

  async function injectProductPage() {
    const titleEl = document.querySelector("h1");
    const title = titleEl ? titleEl.textContent : document.title;
    const priceEl = document.querySelector("[data-widget='webPrice']");
    const priceRub = priceEl ? firstPriceRub(priceEl.innerText) : firstPriceRub(document.body ? document.body.innerText : "");
    const cat = extractCat(document.body);
    const m = await fetchJson(
      "/data/match?q=" +
        encodeURIComponent(title) +
        (cat ? "&cat=" + encodeURIComponent(cat) : "") +
        (priceRub ? "&price_rub=" + priceRub : "")
    );
    if (!m || !m.matched) return;
    const anchor = priceEl || document.querySelector("h1") || document.body;
    if (!anchor || anchor.querySelector(".kjds-badge")) return;
    const b = badge(supplyLine(m.supply, m.margin), "#1a7f37");
    b.setAttribute("data-kjds", "product");
    if (anchor.parentNode) anchor.parentNode.insertBefore(b, anchor.nextSibling);
  }

  function extractCat(scope) {
    const t = (scope && (scope.innerText || scope.textContent)) || "";
    const m = t.match(/类目：\s*([^|\n]{2,24})/);
    return m ? m[1].trim() : "";
  }

  async function injectSellerRows() {
    const cat = await fetchJson("/data/catalog");
    if (!cat || !cat.rows || cat.rows.length === 0) return;
    const rows = cat.rows;
    const byOffer = {};
    rows.forEach((r) => {
      byOffer[r.offer_id] = r;
    });
    const seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        return /[A-Z0-9]{8,}/.test(n.textContent || "") ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    let node;
    let count = 0;
    while ((node = walker.nextNode()) && count < 40) {
      const t = (node.textContent || "").trim();
      const offer = rows.find((r) => t.includes(r.offer_id));
      if (!offer || seen.has(offer.offer_id)) continue;
      seen.add(offer.offer_id);
      count += 1;
      const priceRub = Number(offer.retail_rub || 0);
      const margin = offer.landed || {};
      const html =
        "<b>KJDS</b> " +
        (offer.name || "").slice(0, 24) +
        " | 月销" +
        (offer.orders_6m || 0) +
        " 销额" +
        (offer.revenue_6m_rub || 0).toFixed(0) +
        "₽ | 市场最低" +
        Math.round(offer.market_min_rub || 0) +
        "₽ 指数" +
        (offer.price_index || 0) +
        " | 1688采购¥" +
        (offer.supply_price_median || 0).toFixed(0) +
        " | 参考毛利₽" +
        (margin && margin.net_rub !== undefined ? margin.net_rub : "n/a");
      const b = badge(html, "#b45309");
      b.setAttribute("data-kjds", "seller");
      node.parentNode.insertBefore(b, node.nextSibling);
    }
  }

  let started = false;
  function start() {
    if (started) return;
    started = true;
    const host = location.host || "";
    if (/^seller\./.test(host)) {
      setTimeout(injectSellerRows, 1500);
      const mo = new MutationObserver(() => injectSellerRows());
      mo.observe(document.body, { childList: true, subtree: true });
      setInterval(injectSellerRows, 8000);
    } else if (/\/product\//.test(location.pathname)) {
      setTimeout(injectProductPage, 1200);
    } else if (/\/search\//.test(location.pathname) || /\/category\//.test(location.pathname) || location.pathname === "/") {
      const sel = "[data-widget='searchResultV2']";
      function scan() {
        if (!enabled) return;
        document.querySelectorAll(sel).forEach(injectMarketCard);
      }
      setTimeout(scan, 1200);
      const mo = new MutationObserver(scan);
      mo.observe(document.body, { childList: true, subtree: true });
      setInterval(scan, 5000);
    }
  }
})();
