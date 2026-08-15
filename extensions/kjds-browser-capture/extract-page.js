(() => {
  "use strict";

  const MAX_DETAIL_ITEMS = 500;
  const MAX_CANDIDATES = 50;
  const MAX_IMAGES = 20;
  const CONTRACT = "kjds-browser-capture-envelope/1.2";
  const EXTRACTOR = "kjds-visible-dom/1.2";

  const clean = (value, max = 2000) => {
    const text = String(value ?? "").replace(/<[^>]+>/g, " ")
      .replace(/&gt;/gi, ">").replace(/&amp;/gi, "&")
      .replace(/\s+/g, " ").trim();
    return text ? text.slice(0, max) : null;
  };
  const positiveNumber = (value) => {
    const match = String(value ?? "").replace(/,/g, "")
      .match(/\d+(?:\.\d+)?/);
    if (!match) return null;
    const number = Number(match[0]);
    return Number.isFinite(number) && number > 0 ? number : null;
  };
  const nonnegativeInteger = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const match = String(value).replace(/,/g, "").match(/\d+/);
    if (!match) return null;
    const number = Number(match[0]);
    return Number.isSafeInteger(number) && number >= 0 ? number : null;
  };
  const absoluteHttps = (value) => {
    try {
      const url = new URL(String(value ?? ""), location.href);
      if (url.protocol !== "https:") return null;
      url.search = "";
      url.hash = "";
      return url.href;
    } catch {
      return null;
    }
  };
  const uniqueImages = (values) => Array.from(new Set(
    values.flatMap((value) => {
      const url = absoluteHttps(value);
      return url ? [url] : [];
    }),
  )).slice(0, MAX_IMAGES);
  const visible = (node) => {
    if (!node) return false;
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden";
  };
  const textFrom = (root, selectors, max = 500) => {
    for (const selector of selectors) {
      for (const node of Array.from(root.querySelectorAll(selector)).slice(0, 20)) {
        const text = clean(node.textContent, max);
        if (text && visible(node)) return { text, selector };
      }
    }
    return null;
  };
  const metaFrom = (selectors) => {
    for (const selector of selectors) {
      const text = clean(document.querySelector(selector)?.getAttribute("content"));
      if (text) return { text, selector };
    }
    return null;
  };

  function quoteUnquotedNumericObjectKeys(text) {
    let output = "";
    let quoted = false;
    let escaped = false;
    for (let index = 0; index < text.length; index += 1) {
      const character = text[index];
      if (quoted) {
        output += character;
        if (escaped) escaped = false;
        else if (character === "\\") escaped = true;
        else if (character === "\"") quoted = false;
        continue;
      }
      if (character === "\"") {
        quoted = true;
        output += character;
        continue;
      }
      if (character !== "{" && character !== ",") {
        output += character;
        continue;
      }

      output += character;
      let keyStart = index + 1;
      while (keyStart < text.length && /\s/.test(text[keyStart])) {
        output += text[keyStart];
        keyStart += 1;
      }
      let keyEnd = keyStart;
      while (keyEnd < text.length && /\d/.test(text[keyEnd])) keyEnd += 1;
      let colon = keyEnd;
      while (colon < text.length && /\s/.test(text[colon])) colon += 1;
      if (keyEnd > keyStart && text[colon] === ":") {
        output += `"${text.slice(keyStart, keyEnd)}"`;
        output += text.slice(keyEnd, colon + 1);
        index = colon;
        continue;
      }
      index = keyStart - 1;
    }
    return output;
  }

  function jsonObjectAfterMarker(text, marker) {
    const markerIndex = text.indexOf(marker);
    if (markerIndex < 0) return null;
    let start = -1;
    for (let index = markerIndex + marker.length; index < text.length; index += 1) {
      if (text[index] === "{" || text[index] === "[") {
        start = index;
        break;
      }
      if (!/\s|,/.test(text[index])) return null;
    }
    if (start < 0) return null;
    const stack = [];
    let quoted = false;
    let escaped = false;
    for (let index = start; index < text.length; index += 1) {
      const character = text[index];
      if (quoted) {
        if (escaped) escaped = false;
        else if (character === "\\") escaped = true;
        else if (character === "\"") quoted = false;
        continue;
      }
      if (character === "\"") {
        quoted = true;
        continue;
      }
      if (character === "{" || character === "[") stack.push(character);
      if (character === "}" || character === "]") {
        const opening = stack.pop();
        if ((opening === "{" && character !== "}")
          || (opening === "[" && character !== "]")) return null;
        if (stack.length === 0) {
          const serialized = text.slice(start, index + 1);
          try {
            return JSON.parse(serialized);
          } catch {
            try {
              // Current 1688 SSR uses JavaScript object-literal numeric keys
              // (for example `skuMapOriginal:{0:{...}}`). Convert only those
              // keys outside quoted strings; never execute page-provided code.
              return JSON.parse(quoteUnquotedNumericObjectKeys(serialized));
            } catch {
              return null;
            }
          }
        }
      }
    }
    return null;
  }

  function serialized1688Context() {
    const markers = [
      "})(window.contextPath,",
      ")(window.contextPath,",
      "window.contextPath,",
    ];
    for (const script of Array.from(document.scripts).slice(0, 200)) {
      const text = script.textContent ?? "";
      if (!text.includes("window.context") || text.length > 8_000_000) continue;
      for (const marker of markers) {
        const parsed = jsonObjectAfterMarker(text, marker);
        if (parsed?.result?.data) return parsed;
      }
    }
    return null;
  }

  function findAllByKey(root, wantedKeys, maxDepth = 12, limit = 40) {
    const wanted = new Set(wantedKeys);
    const queue = [{ value: root, depth: 0 }];
    const seen = new Set();
    const matches = [];
    let visited = 0;
    while (queue.length && visited < 30000 && matches.length < limit) {
      const { value, depth } = queue.shift();
      visited += 1;
      if (!value || typeof value !== "object" || depth > maxDepth || seen.has(value)) {
        continue;
      }
      seen.add(value);
      if (!Array.isArray(value)) {
        for (const key of Object.keys(value)) {
          if (wanted.has(key) && value[key] !== null && value[key] !== undefined) {
            matches.push(value[key]);
            if (matches.length >= limit) break;
          }
        }
      }
      for (const child of Array.isArray(value) ? value : Object.values(value)) {
        if (child && typeof child === "object") {
          queue.push({ value: child, depth: depth + 1 });
        }
      }
    }
    return matches;
  }

  function findByKey(root, wantedKeys, maxDepth = 12) {
    return findAllByKey(root, wantedKeys, maxDepth, 1)[0] ?? null;
  }

  function publicSignal(root, keys) {
    const value = findByKey(root, keys);
    if (value === null || value === undefined || typeof value === "object") return null;
    return clean(value, 500);
  }

  function attributesFrom(context) {
    const result = {};
    const candidates = findAllByKey(context, [
      "featureAttributes",
      "productAttributes",
      "decisionCpv",
      "normalCpv",
    ], 12, 80).filter(Array.isArray);
    for (const raw of candidates) {
      for (const entry of raw.slice(0, 80)) {
        if (!entry || typeof entry !== "object") continue;
        const key = clean(entry.name ?? entry.key, 100);
        const value = clean(
          entry.value ?? (Array.isArray(entry.values) ? entry.values.join(",") : null),
          500,
        );
        if (key && value && result[key] === undefined) result[key] = value;
      }
    }
    return result;
  }

  function packCountSignal(text) {
    const normalized = String(text ?? "");
    const digit = normalized.match(/(\d{1,3})\s*(?:件|个|只|片)\s*套/);
    if (digit) return digit[1];
    const chinese = normalized.match(/([一二两三四五六七八九十])\s*(?:件|个|只|片)\s*套/);
    if (chinese) {
      return String({ 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6,
        七: 7, 八: 8, 九: 9, 十: 10 }[chinese[1]] ?? "") || null;
    }
    const englishDigit = normalized.match(
      /\b(\d{1,3})\s*(?:-|\s)?(?:pieces?|pcs?|pack)\b/i,
    );
    if (englishDigit) return englishDigit[1];
    const englishWord = normalized.match(
      /\b(one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:-|\s)?(?:pieces?|pcs?|pack)\b/i,
    );
    if (!englishWord) return null;
    return String({ one: 1, two: 2, three: 3, four: 4, five: 5, six: 6,
      seven: 7, eight: 8, nine: 9, ten: 10 }[englishWord[1].toLowerCase()] ?? "") || null;
  }

  function sizeSignal(text) {
    const matches = String(text ?? "").match(
      /\d+(?:\.\d+)?\s*(?:mm|cm|m|毫米|厘米|米)(?:\s*[x×*]\s*\d+(?:\.\d+)?\s*(?:mm|cm|m|毫米|厘米|米))*/gi,
    );
    return matches ? Array.from(new Set(matches.map((item) => clean(item, 100))))
      .filter(Boolean).join(" | ").slice(0, 500) : null;
  }

  function auxiliaryVariantSignal(text) {
    return /定制|logo|补差|差价|运费|邮费|样品|联系客服|咨询|测试|勿拍|专拍/i
      .test(String(text ?? ""));
  }

  function itemCode(attributes) {
    for (const [key, value] of Object.entries(attributes)) {
      if (/货号|型号|model|item\s*code/i.test(key)) return value;
    }
    return null;
  }

  function materialSignal(attributes) {
    for (const [key, value] of Object.entries(attributes)) {
      if (/材质|面料|material/i.test(key)) return value;
    }
    return null;
  }

  function materialComparisonDimensions(attributes, title) {
    const rawMaterial = materialSignal(attributes);
    if (!rawMaterial) return {};
    const material = /牛津布|oxford\s*cloth/i.test(rawMaterial)
      ? "oxford_cloth" : clean(rawMaterial, 500);
    if (!material) return {};
    const context = `${rawMaterial} ${String(title ?? "")}`;
    const finish = [];
    if (/加厚|thickened?/i.test(context)) finish.push("thickened");
    if (/防水|waterproof/i.test(context)) finish.push("waterproof");
    return {
      material,
      ...(finish.length ? { material_finish: finish.join("+") } : {}),
    };
  }

  function priceTiersForSku(priceTiers, skuPrice) {
    if (!priceTiers.length) return [];
    const priceKey = String(skuPrice);
    if (!priceTiers.some((tier) => String(tier.price) === priceKey)) {
      return [];
    }
    const quantityCounts = new Map();
    for (const tier of priceTiers) {
      quantityCounts.set(
        tier.minimum_quantity,
        (quantityCounts.get(tier.minimum_quantity) ?? 0) + 1,
      );
    }
    const hasAmbiguousQuantity = Array.from(quantityCounts.values()).some(
      (count) => count > 1,
    );
    const candidates = hasAmbiguousQuantity
      ? priceTiers.filter((tier) => String(tier.price) === priceKey)
      : priceTiers;
    const unique = new Map();
    for (const tier of candidates) {
      const existing = unique.get(tier.minimum_quantity);
      if (existing && existing.price !== tier.price) return [];
      unique.set(tier.minimum_quantity, tier);
    }
    return Array.from(unique.values()).sort(
      (left, right) => left.minimum_quantity - right.minimum_quantity,
    );
  }

  function feGlobalsOfferLoginId() {
    const pattern = /(?:["']?offerLoginId["']?)\s*:\s*(["'])([^"'\\]{1,240})\1/;
    for (const script of Array.from(document.scripts).slice(0, 200)) {
      const text = script.textContent ?? "";
      if (!text.includes("offerLoginId")) continue;
      const match = text.match(pattern);
      if (match) return clean(match[2], 240);
    }
    return null;
  }

  function galleryImages(data) {
    const gallery = data?.gallery?.fields ?? {};
    const raw = Array.isArray(gallery.mainImage) ? gallery.mainImage : [];
    return uniqueImages(raw.flatMap((entry) => {
      if (typeof entry === "string") return [entry];
      if (!entry || typeof entry !== "object") return [];
      const value = entry.fullPathImageURI ?? entry.size310x310ImageURI
        ?? entry.imageURI;
      if (!value) return [];
      return [String(value).startsWith("http")
        ? value : `https://cbu01.alicdn.com/${String(value).replace(/^\//, "")}`];
    }));
  }

  function skuImageMap(context) {
    const result = new Map();
    const raw = findByKey(context, ["skuProps"]);
    if (!Array.isArray(raw)) return result;
    for (const property of raw) {
      const values = Array.isArray(property?.value) ? property.value : [];
      for (const value of values) {
        const name = clean(value?.name, 500);
        const image = absoluteHttps(value?.imageUrl);
        if (name && image) result.set(name, image);
      }
    }
    return result;
  }

  function extract1688Detail() {
    const offerMatch = location.href.match(/\/offer\/(\d+)\.html/i);
    if (!offerMatch) return null;
    const context = serialized1688Context();
    if (!context) {
      return { error: "当前 1688 商品页没有可验证的序列化 SKU 数据；未退化为猜价" };
    }
    const data = context.result.data;
    const productTitle = data?.productTitle?.fields ?? {};
    const gallery = data?.gallery?.fields ?? {};
    const title = clean(productTitle.title ?? gallery.subject ?? document.title);
    const offerId = clean(gallery.offerId ?? offerMatch[1], 240);
    if (!title || !offerId || offerId !== offerMatch[1]) {
      return { error: "URL offer_id 与页面结构化商品身份不一致" };
    }
    const tradeModels = findAllByKey(
      context,
      ["tradeWithoutPromotion", "tradeModel"],
    ).filter((value) => value && typeof value === "object" && !Array.isArray(value));
    const skuMapCandidates = Array.from(new Set([
      ...tradeModels.map((value) => value.skuMap),
      ...tradeModels.map((value) => value.skuMapOriginal),
      ...findAllByKey(context, ["skuMap", "skuMapOriginal"]),
    ])).filter((value) => value && typeof value === "object");
    const completeSkuMap = (candidate) => {
      const candidateRows = Object.values(candidate);
      return candidateRows.length > 0 && candidateRows.every((row) => (
        row && typeof row === "object"
        && clean(row.skuId, 240)
        && clean(row.specId, 240)
        && positiveNumber(row.discountPrice ?? row.price ?? row.multiPrice) !== null
      ));
    };
    const skuMap = skuMapCandidates.find(completeSkuMap);
    const tradeModel = tradeModels.find((value) => (
      value.skuMap === skuMap || value.skuMapOriginal === skuMap
    ))
      ?? tradeModels.find((value) => (
        value.beginAmount || value.minOrderQty || value.skuPriceScale
      )) ?? null;
    if (!skuMap) {
      return { error: "页面没有形成可逐项绑定的 SKU 矩阵" };
    }
    const attributes = attributesFrom(context);
    const productItemCode = itemCode(attributes);
    const categoryId = clean(
      data?.description?.fields?.leafCategoryId
        ?? findByKey(context, ["leafCategoryId", "postCategoryId"]),
      100,
    );
    const packFields = data?.productPackInfo?.fields ?? {};
    const unitWeight = positiveNumber(
      packFields.unitWeight ?? findByKey(packFields, ["unitWeight"]),
    );
    const shop = productTitle.shopInfo ?? {};
    const loginId = feGlobalsOfferLoginId();
    const companyName = clean(shop.companyName ?? shop.authCompanyName, 500);
    const supplierRef = loginId ?? companyName ?? `unresolved:1688:${offerId}`;
    const unit = clean(
      tradeModel?.unit ?? tradeModel?.unitName ?? productTitle.unit,
      80,
    );
    const moq = nonnegativeInteger(
      tradeModel?.beginAmount ?? tradeModel?.minOrderQty,
    );
    const mixOrderQuantity = nonnegativeInteger(
      tradeModel?.mixAmount ?? tradeModel?.mixModel?.mixAmount
        ?? tradeModel?.mixOrderQuantity,
    );
    const priceRange = clean(
      tradeModel?.skuPriceScale ?? tradeModel?.priceRange
        ?? findByKey(context, ["skuPriceScale"]),
      200,
    );
    const rawTiers = tradeModel?.offerPriceModel?.currentPrices
      ?? tradeModel?.currentPrices ?? tradeModel?.priceTiers;
    const priceTiers = Array.isArray(rawTiers) ? rawTiers.slice(0, 20).flatMap((row) => {
      const minimumQuantity = nonnegativeInteger(row?.beginAmount ?? row?.minQty);
      const price = positiveNumber(row?.price);
      return minimumQuantity !== null && price !== null
        ? [{ minimum_quantity: minimumQuantity, price: String(price) }] : [];
    }) : [];
    const images = galleryImages(data);
    const perVariantImages = skuImageMap(context);
    const merchantPublicSignals = {
      service_score: clean(shop.sellerSlrServiceScore, 100),
      repeat_rate_3m: publicSignal(productTitle, [
        "repeatRate", "repeatPurchaseRate", "repurchaseRate", "repeatRate3m",
      ]),
      good_rate_percent: publicSignal(productTitle, ["goodRates", "goodRate"]),
      goods_grade: publicSignal(productTitle, ["goodsGrade"]),
      total_review_count: nonnegativeInteger(
        findByKey(productTitle, ["totalReviewCount", "totalCount", "commentCount"]),
      ),
      image_review_count: nonnegativeInteger(
        findByKey(productTitle, ["imageReviewCount", "picReviewCount"]),
      ),
      offer_sale_signal: clean(productTitle.newSaleCount, 100),
    };
    Object.keys(merchantPublicSignals).forEach((key) => {
      if (merchantPublicSignals[key] === null) delete merchantPublicSignals[key];
    });
    const entries = Object.entries(skuMap);
    if (entries.length > MAX_DETAIL_ITEMS) {
      return {
        error: `当前详情页有 ${entries.length} 个 SKU，超过 500 行合同上限；未生成不完整采集`,
      };
    }
    const rows = [];
    for (const [mapKey, raw] of entries) {
      if (!raw || typeof raw !== "object") continue;
      const skuId = clean(raw.skuId, 240);
      const specId = clean(raw.specId, 240);
      const variantKey = clean(raw.specAttrs ?? raw.spec ?? mapKey, 500);
      const price = positiveNumber(raw.discountPrice ?? raw.price ?? raw.multiPrice);
      if (!skuId || !specId || !variantKey || price === null) continue;
      const stock = nonnegativeInteger(raw.canBookCount ?? raw.stock);
      const saleCount = nonnegativeInteger(raw.saleCount);
      const skuPriceTiers = priceTiersForSku(priceTiers, price);
      const auxiliaryVariant = auxiliaryVariantSignal(variantKey);
      const packCount = packCountSignal(variantKey)
        ?? (auxiliaryVariant ? null : packCountSignal(title));
      const size = sizeSignal(variantKey) ?? sizeSignal(title);
      const materialDimensions = materialComparisonDimensions(attributes, title);
      const comparisonDimensions = {};
      if (categoryId) comparisonDimensions.category_id = categoryId;
      if (packCount) comparisonDimensions.pack_count = packCount;
      if (size) comparisonDimensions.size = size;
      Object.assign(comparisonDimensions, materialDimensions);
      if (unit) comparisonDimensions.trade_unit = unit;
      if (auxiliaryVariant) {
        comparisonDimensions.variant_role = "auxiliary_or_customization";
      }
      const firstVariantName = variantKey.split(/\s*>\s*/)[0];
      rows.push({
        external_item_id: offerId,
        supplier_ref: supplierRef,
        title,
        variant_key: variantKey,
        currency: "CNY",
        displayed_price: String(price),
        price_scope: "unit_price",
        price_kind: "public_display_price",
        min_order_quantity: moq && moq > 0 ? moq : null,
        availability: stock === 0 ? "out_of_stock" : stock > 0 ? "in_stock" : "unknown",
        specifications: {
          ...attributes,
          selected_variant: variantKey,
        },
        product_identity: {
          offer_id: offerId,
          sku_id: skuId,
          spec_id: specId,
          ...(productItemCode ? { item_code: productItemCode } : {}),
          ...(categoryId ? { category_id: categoryId } : {}),
        },
        comparison_dimensions: comparisonDimensions,
        observed_quantity: null,
        checkout_verified: false,
        tax_included: null,
        domestic_freight_included: null,
        purchase_available: false,
        confidence: "0.92",
        market_signals: {
          ...(saleCount !== null ? { sku_sale_count_signal: saleCount } : {}),
          ...(productTitle.newSaleCount
            ? { offer_sale_signal: clean(productTitle.newSaleCount, 100) } : {}),
        },
        supply_signals: {
          ...(stock !== null ? { stock_count: stock } : {}),
          ...(mixOrderQuantity !== null ? { mix_order_quantity: mixOrderQuantity } : {}),
          ...(unit ? { trade_unit: unit } : {}),
          ...(unitWeight !== null ? { unit_weight_kg_signal: String(unitWeight) } : {}),
          ...(priceRange ? { advertised_price_range: priceRange } : {}),
          ...(skuPriceTiers.length ? { price_tiers: skuPriceTiers } : {}),
          ...(auxiliaryVariant
            ? { comparison_exclusion: "auxiliary_or_customization_variant" }
            : {}),
          price_source_field: raw.discountPrice ? "discountPrice"
            : raw.price ? "price" : "multiPrice",
          extraction_authority: "serialized_ssr_current_document",
        },
        media_rights_status: "unverified_external_reference",
        image_references: uniqueImages([
          perVariantImages.get(firstVariantName),
          ...images,
        ]),
        source_url: location.href,
      });
    }
    if (!rows.length || rows.length !== entries.length) {
      return {
        error: `SKU 矩阵共 ${entries.length} 行，只有 ${rows.length} 行同时具备 sku_id、spec_id 与价格；未生成漏行采集`,
      };
    }
    return {
      envelope: {
        contract_version: CONTRACT,
        source_profile: "browser_observation",
        marketplace: "1688",
        store_ref: "ozon-primary",
        source_url: location.href,
        observed_at: new Date().toISOString(),
        idempotency_key: `capture-${crypto.randomUUID()}`,
        page: {
          title,
          canonical_url: document.querySelector("link[rel='canonical']")
            ?.getAttribute("href") ?? location.href,
          language: document.documentElement.lang || "zh-CN",
          extractor_version: EXTRACTOR,
          capture_mode: "active_tab_visible_dom",
          capture_kind: "product_detail_variant_matrix",
          provider_id: "1688-current-document-provider",
          provider_version: "1.0.0",
          structured_data_source: "serialized_ssr_window.context",
          capture_coverage: {
            discovered_count: entries.length,
            captured_count: rows.length,
            truncated: false,
            exact_sku_identity_count: rows.length,
          },
        },
        merchant: {
          supplier_ref: supplierRef,
          company_name: companyName,
          login_id: loginId,
          public_signals: merchantPublicSignals,
        },
        items: rows,
        confirmed: true,
      },
      search_seed: title,
    };
  }

  function cardContainer(anchor) {
    let node = anchor;
    for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
      const text = clean(node.textContent, 5000) ?? "";
      const offerLinks = node.querySelectorAll?.("a[href*='/offer/']").length ?? 0;
      if (offerLinks >= 1 && offerLinks <= 4 && /[¥￥]\s*\d|\d+(?:\.\d+)?\s*元/.test(text)) {
        return node;
      }
    }
    return anchor.parentElement ?? anchor;
  }

  function extract1688Candidates() {
    const anchors = Array.from(document.querySelectorAll("a[href*='/offer/']"));
    const byOffer = new Map();
    for (const anchor of anchors) {
      const url = absoluteHttps(anchor.href ?? anchor.getAttribute("href"));
      const match = url?.match(/\/offer\/(\d+)\.html/i);
      if (match && !byOffer.has(match[1])) byOffer.set(match[1], { anchor, url });
    }
    if (byOffer.size < 2) return null;
    const path = `${location.pathname}${location.search}`.toLowerCase();
    const captureKind = /search|selloffer|keywords|query/.test(path)
      ? "search_result_candidates" : "store_catalog_candidates";
    const rows = [];
    for (const [offerId, { anchor, url }] of Array.from(byOffer).slice(0, MAX_CANDIDATES)) {
      const card = cardContainer(anchor);
      const cardText = clean(card.textContent, 5000) ?? "";
      const priceMatch = cardText.match(/[¥￥]\s*(\d+(?:\.\d+)?)/)
        ?? cardText.match(/(\d+(?:\.\d+)?)\s*元/);
      const price = positiveNumber(priceMatch?.[1]);
      if (price === null) continue;
      const image = card.querySelector("img[src],img[data-src]");
      const title = clean(
        anchor.getAttribute("title") ?? image?.getAttribute("alt")
          ?? anchor.textContent,
        2000,
      );
      if (!title) continue;
      const supplier = textFrom(card, [
        "[class*='company']", "[class*='shop']", "[class*='supplier']",
        "[data-seller-id]",
      ], 240);
      rows.push({
        external_item_id: offerId,
        supplier_ref: supplier?.text ?? `unresolved:1688:${offerId}`,
        title,
        variant_key: "unselected",
        currency: "CNY",
        displayed_price: String(price),
        price_scope: "unit_price",
        price_kind: "range_minimum",
        min_order_quantity: null,
        availability: "unknown",
        specifications: {},
        product_identity: {
          offer_id: offerId,
          identity_resolution: "offer_only",
        },
        comparison_dimensions: {},
        observed_quantity: null,
        checkout_verified: false,
        tax_included: null,
        domestic_freight_included: null,
        purchase_available: false,
        confidence: "0.55",
        market_signals: {},
        supply_signals: {
          extraction_authority: "visible_current_page_card",
          candidate_requires_detail_enrichment: true,
        },
        media_rights_status: "unverified_external_reference",
        image_references: uniqueImages([
          image?.getAttribute("src"), image?.getAttribute("data-src"),
        ]),
        source_url: url,
      });
    }
    if (!rows.length) return { error: "发现商品链接，但没有卡片内可绑定的公开价格" };
    const searchQuery = clean(
      new URL(location.href).searchParams.get("keywords")
        ?? new URL(location.href).searchParams.get("keyword")
        ?? document.querySelector("input[type='search']")?.value,
      500,
    );
    return {
      envelope: {
        contract_version: CONTRACT,
        source_profile: "browser_observation",
        marketplace: "1688",
        store_ref: "ozon-primary",
        source_url: location.href,
        observed_at: new Date().toISOString(),
        idempotency_key: `capture-${crypto.randomUUID()}`,
        page: {
          title: clean(document.title) ?? "1688 当前候选页",
          canonical_url: location.href,
          language: document.documentElement.lang || "zh-CN",
          extractor_version: EXTRACTOR,
          capture_mode: "active_tab_visible_dom",
          capture_kind: captureKind,
          provider_id: "1688-current-document-provider",
          provider_version: "1.0.0",
          structured_data_source: "visible_current_page_product_cards",
          search_query: searchQuery,
          capture_coverage: {
            discovered_count: byOffer.size,
            captured_count: rows.length,
            truncated: byOffer.size > MAX_CANDIDATES,
            exact_sku_identity_count: 0,
          },
        },
        merchant: null,
        items: rows,
        confirmed: true,
      },
      search_seed: searchQuery,
    };
  }

  function extractGenericProduct(marketplace) {
    const idMatch = marketplace === "1688"
      ? location.href.match(/\/offer\/(\d+)\.html/i)
      : location.href.match(/(?:-|\/)(\d{5,})(?:\/|\?|$)/);
    if (!idMatch) return { error: "未识别到稳定商品 ID；请打开商品详情或搜索结果页" };
    const titleSignal = textFrom(document, ["h1", "[itemprop='name']"], 2000)
      ?? metaFrom(["meta[property='og:title']", "meta[name='title']"])
      ?? { text: clean(document.title), selector: "document.title" };
    const priceSignal = metaFrom([
      "meta[property='product:price:amount']", "meta[itemprop='price']",
      "meta[name='price']",
    ]) ?? textFrom(document, [
      "[itemprop='price']", "[class*='price-text']", "[class*='Price--price']",
      "[class~='price']", "[class*='price']",
    ], 500);
    const price = positiveNumber(priceSignal?.text);
    if (!titleSignal?.text || price === null) {
      return { error: "未在当前页识别到一一对应的商品身份与价格；没有生成猜测价格" };
    }
    const supplier = metaFrom(["meta[name='seller-id']", "meta[name='sellerId']"])
      ?? textFrom(document, ["[data-seller-id]", "[class*='companyName']",
        "[class*='shopName']", ".company-name"], 240);
    const images = uniqueImages(Array.from(document.querySelectorAll(
      "img[src],img[data-src],meta[property='og:image']",
    )).slice(0, 80).map((node) => node.getAttribute("content")
      ?? node.getAttribute("data-src") ?? node.getAttribute("src")));
    const itemId = idMatch[1];
    return {
      envelope: {
        contract_version: CONTRACT,
        source_profile: "browser_observation",
        marketplace,
        store_ref: "ozon-primary",
        source_url: location.href,
        observed_at: new Date().toISOString(),
        idempotency_key: `capture-${crypto.randomUUID()}`,
        page: {
          title: titleSignal.text,
          canonical_url: document.querySelector("link[rel='canonical']")
            ?.getAttribute("href") ?? location.href,
          language: document.documentElement.lang || null,
          extractor_version: EXTRACTOR,
          capture_mode: "active_tab_visible_dom",
          capture_kind: "generic_product",
          provider_id: "generic-visible-product-provider",
          provider_version: "1.0.0",
          structured_data_source: "visible_dom",
          capture_coverage: {
            discovered_count: 1,
            captured_count: 1,
            truncated: false,
            exact_sku_identity_count: 0,
          },
        },
        merchant: null,
        items: [{
          external_item_id: itemId,
          supplier_ref: supplier?.text ?? `unresolved:${location.hostname}`,
          title: titleSignal.text,
          variant_key: "unselected",
          currency: marketplace === "1688" ? "CNY" : "RUB",
          displayed_price: String(price),
          price_scope: "unit_price",
          price_kind: "public_display_price",
          min_order_quantity: null,
          availability: "unknown",
          specifications: {},
          product_identity: { offer_id: itemId, identity_resolution: "offer_only" },
          comparison_dimensions: {},
          observed_quantity: null,
          checkout_verified: false,
          tax_included: null,
          domestic_freight_included: null,
          purchase_available: false,
          confidence: priceSignal.selector?.startsWith("meta") ? "0.7" : "0.45",
          market_signals: {},
          supply_signals: {
            title_selector: titleSignal.selector,
            price_selector: priceSignal.selector,
            extraction_authority: "visible_dom_observation_only",
          },
          media_rights_status: "unverified_external_reference",
          image_references: images,
          source_url: location.href,
        }],
        confirmed: true,
      },
      search_seed: titleSignal.text,
    };
  }

  const host = location.hostname.toLowerCase();
  const marketplace = host === "1688.com" || host.endsWith(".1688.com")
    ? "1688" : host === "ozon.ru" || host.endsWith(".ozon.ru")
      ? "ozon" : null;
  if (!marketplace) return { error: "当前页面不是允许的 1688/Ozon 页面" };
  if (marketplace === "1688") {
    const detail = extract1688Detail();
    if (detail) return detail;
    const candidates = extract1688Candidates();
    if (candidates) return candidates;
  }
  return extractGenericProduct(marketplace);
})();
