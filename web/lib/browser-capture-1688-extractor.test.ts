import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const extractorSource = readFileSync(
  new URL("../../extensions/kjds-browser-capture/extract-page.js", import.meta.url),
  "utf8",
);

test("1688 serialized SSR extractor binds every price to its sku and spec", () => {
  const context = {
    result: {
      data: {
        productAttributes: { fields: { uiType: "placeholder-module" } },
        earlyReference: {
          numericSkuLookup: {
            "4494375919490": { price: "9.90" },
          },
          tradeWithoutPromotion: {
            skuMapOriginal: {
              0: { $ref: "$.result.data.mainPrice.skuMapOriginal.0" },
              1: { $ref: "$.result.data.mainPrice.skuMapOriginal.1" },
            },
          },
        },
        productTitle: {
          fields: {
            title: "加厚牛津布旅行收纳六件套",
            unit: "件",
            newSaleCount: "17",
            shopInfo: {
              companyName: "义乌市喜哥日用品厂",
              sellerSlrServiceScore: "4.5",
            },
            repeatRate: "69.96%",
            goodRates: "98.8%",
            goodsGrade: "4.9",
            totalReviewCount: 20,
          },
        },
        gallery: {
          fields: {
            offerId: "38547222320",
            mainImage: [
              { fullPathImageURI: "https://cbu01.alicdn.com/img/offer.jpg" },
            ],
          },
        },
        description: { fields: { leafCategoryId: "1036894" } },
        productPackInfo: { fields: { unitWeight: 0.24 } },
        mainPrice: {
          fields: {
            finalPriceModel: {
              tradeWithoutPromotion: {
                beginAmount: 1,
                mixAmount: 80,
                skuPriceScale: "3.90-9.90",
                skuMapOriginal: [
                  {
                    skuId: "sku-3",
                    specId: "spec-3",
                    specAttrs: "颜色:西瓜红三件套收纳袋",
                    price: "3.90",
                    canBookCount: 470,
                    saleCount: 2,
                  },
                  {
                    skuId: "sku-6",
                    specId: "spec-6",
                    specAttrs: "颜色:宝蓝六件套",
                    price: "9.90",
                    canBookCount: 13,
                    saleCount: 10,
                  },
                  {
                    skuId: "sku-logo",
                    specId: "spec-logo",
                    specAttrs: "可定制logo",
                    price: "3.30",
                    canBookCount: 100,
                    saleCount: 0,
                  },
                ],
              },
            },
          },
        },
        globalData: {
          model: {
            offerDetail: {
              featureAttributes: [
                { name: "货号", value: "A-2-1" },
                { name: "材质", value: "防水加厚牛津布" },
              ],
            },
          },
        },
      },
    },
  };
  const serializedContext = JSON.stringify(context)
    .replace('"numericSkuLookup":{"4494375919490":', '"numericSkuLookup":{4494375919490:');
  const scripts = [
    {
      // 1688 currently emits legal JavaScript object keys that are not strict
      // JSON. The extractor must parse this shape without evaluating it.
      textContent: `window.context=(function(a,b){return b})(window.contextPath,${serializedContext});`,
    },
    { textContent: 'window.FE_GLOBALS={offerLoginId:"戴贺喜188",loginId:"buyer-must-not-leak"};' },
  ];
  const location = new URL(
    "https://detail.1688.com/offer/38547222320.html",
  );
  const document = {
    scripts,
    title: "加厚牛津布旅行收纳六件套 - 阿里巴巴",
    documentElement: { lang: "zh-CN" },
    querySelector(selector: string) {
      if (selector === "link[rel='canonical']") {
        return { getAttribute: () => location.href };
      }
      return null;
    },
    querySelectorAll() {
      return [];
    },
  };

  const result = vm.runInNewContext(extractorSource, {
    URL,
    location,
    document,
    crypto: { randomUUID: () => "00000000-0000-4000-8000-000000000001" },
    getComputedStyle: () => ({ display: "block", visibility: "visible" }),
  });

  assert.equal(result.envelope.contract_version, "kjds-browser-capture-envelope/1.2");
  assert.equal(result.envelope.page.capture_kind, "product_detail_variant_matrix");
  assert.equal(result.envelope.items.length, 3);
  const bySku = new Map(
    result.envelope.items.map((item: Record<string, any>) => [
      item.product_identity.sku_id,
      item,
    ]),
  );
  assert.equal(bySku.get("sku-3")?.displayed_price, "3.9");
  assert.equal(bySku.get("sku-3")?.product_identity.spec_id, "spec-3");
  assert.equal(bySku.get("sku-3")?.comparison_dimensions.pack_count, "3");
  assert.equal(
    bySku.get("sku-3")?.comparison_dimensions.material,
    "防水加厚牛津布",
  );
  assert.equal(bySku.get("sku-6")?.displayed_price, "9.9");
  assert.equal(bySku.get("sku-6")?.comparison_dimensions.pack_count, "6");
  assert.equal(bySku.get("sku-logo")?.displayed_price, "3.3");
  assert.equal(bySku.get("sku-logo")?.comparison_dimensions.pack_count, undefined);
  assert.equal(
    bySku.get("sku-logo")?.comparison_dimensions.variant_role,
    "auxiliary_or_customization",
  );
  assert.equal(
    bySku.get("sku-logo")?.supply_signals.comparison_exclusion,
    "auxiliary_or_customization_variant",
  );
  assert.equal(result.envelope.merchant.login_id, "戴贺喜188");
  assert.equal(result.envelope.merchant.public_signals.good_rate_percent, "98.8%");
  assert.equal(JSON.stringify(result).includes("buyer-must-not-leak"), false);
});

test("1688 promotion skuMap remains exact when skuMapOriginal has no row prices", () => {
  const context = {
    result: {
      data: {
        productTitle: {
          fields: {
            title: "旅行包6件套牛津布收纳包",
            shopInfo: { companyName: "义乌市暖宏纺织品有限公司" },
          },
        },
        gallery: { fields: { offerId: "675097513713" } },
        description: { fields: { leafCategoryId: "121534005" } },
        mainPrice: {
          fields: {
            finalPriceModel: {
              tradeModel: {
                beginAmount: 2,
                unit: "套",
                offerPriceModel: {
                  currentPrices: [{ beginAmount: 2, price: "4.76" }],
                },
                skuMap: [
                  {
                    skuId: "5934582561130",
                    specId: "ad83bda4f5122c3126b551ae642adf4b",
                    specAttrs: "粉色#C0A6Y#",
                    discountPrice: "4.76",
                    canBookCount: 199383,
                  },
                  {
                    skuId: "5934582561131",
                    specId: "37ddd46f34feb6b80eb49db18ba5168f",
                    specAttrs: "灰色#C0A6R#",
                    discountPrice: "4.76",
                    canBookCount: 199388,
                  },
                ],
                tradeWithoutPromotion: {
                  offerBeginAmount: 4,
                  offerPriceDisplay: "6.80",
                  skuMapOriginal: [
                    {
                      skuId: "5934582561130",
                      specId: "ad83bda4f5122c3126b551ae642adf4b",
                      specAttrs: "粉色#C0A6Y#",
                    },
                    {
                      skuId: "5934582561131",
                      specId: "37ddd46f34feb6b80eb49db18ba5168f",
                      specAttrs: "灰色#C0A6R#",
                    },
                  ],
                },
              },
            },
          },
        },
        globalData: {
          model: {
            offerDetail: {
              featureAttributes: [{ name: "材质", value: "牛津布" }],
            },
          },
        },
      },
    },
  };
  const location = new URL(
    "https://detail.1688.com/offer/675097513713.html",
  );
  const document = {
    scripts: [{
      textContent: `window.context=(function(a,b){return b})(window.contextPath,${JSON.stringify(context)});`,
    }],
    title: "旅行包6件套牛津布收纳包 - 阿里巴巴",
    documentElement: { lang: "zh-CN" },
    querySelector(selector: string) {
      if (selector === "link[rel='canonical']") {
        return { getAttribute: () => location.href };
      }
      return null;
    },
    querySelectorAll() {
      return [];
    },
  };

  const result = vm.runInNewContext(extractorSource, {
    URL,
    location,
    document,
    crypto: { randomUUID: () => "00000000-0000-4000-8000-000000000003" },
    getComputedStyle: () => ({ display: "block", visibility: "visible" }),
  });

  assert.equal(result.envelope.items.length, 2);
  assert.equal(result.envelope.items[0].displayed_price, "4.76");
  assert.equal(result.envelope.items[0].min_order_quantity, 2);
  assert.equal(
    result.envelope.items[0].product_identity.spec_id,
    "ad83bda4f5122c3126b551ae642adf4b",
  );
  assert.equal(result.envelope.items[0].supply_signals.price_source_field, "discountPrice");
  assert.deepEqual(
    JSON.parse(JSON.stringify(result.envelope.items[0].supply_signals.price_tiers)),
    [{ minimum_quantity: 2, price: "4.76" }],
  );
  assert.equal(result.envelope.items.some((item: any) => item.displayed_price === "4.26"), false);
});

test("1688 search cards remain offer-only candidates until detail enrichment", () => {
  const makeNode = (textContent: string) => ({
    textContent,
    getAttribute: () => null,
  });
  const makeCard = (
    offerId: string,
    price: string,
    title: string,
    supplier: string,
  ) => {
    const image = {
      textContent: "",
      getAttribute(name: string) {
        if (name === "alt") return title;
        if (name === "src") return `https://cbu01.alicdn.com/${offerId}.jpg`;
        return null;
      },
    };
    const card: any = {
      textContent: `${title} ￥${price} ${supplier}`,
      parentElement: null,
      querySelector(selector: string) {
        return selector.includes("img") ? image : null;
      },
      querySelectorAll(selector: string) {
        if (selector.includes("/offer/")) return [anchor];
        if (/company|shop|supplier|seller/.test(selector)) return [makeNode(supplier)];
        return [];
      },
    };
    const anchor: any = {
      href: `https://detail.1688.com/offer/${offerId}.html`,
      textContent: title,
      parentElement: card,
      getAttribute(name: string) {
        if (name === "href") return this.href;
        if (name === "title") return title;
        return null;
      },
      querySelectorAll() {
        return [];
      },
    };
    return { anchor, card };
  };
  const first = makeCard("10001", "8.80", "牛津布六件套 蓝色", "供应商甲");
  const second = makeCard("10002", "3.20", "牛津布三件套 红色", "供应商乙");
  const location = new URL(
    "https://s.1688.com/selloffer/offer_search.htm?keywords=%E6%94%B6%E7%BA%B3%E8%A2%8B",
  );
  const document = {
    scripts: [],
    title: "收纳袋 - 1688 搜索",
    documentElement: { lang: "zh-CN" },
    querySelector(selector: string) {
      if (selector === "input[type='search']") return { value: "收纳袋" };
      return null;
    },
    querySelectorAll(selector: string) {
      if (selector === "a[href*='/offer/']") {
        return [first.anchor, second.anchor];
      }
      return [];
    },
  };

  const result = vm.runInNewContext(extractorSource, {
    URL,
    location,
    document,
    crypto: { randomUUID: () => "00000000-0000-4000-8000-000000000002" },
    getComputedStyle: () => ({ display: "block", visibility: "visible" }),
  });

  assert.equal(result.envelope.page.capture_kind, "search_result_candidates");
  assert.equal(result.envelope.items.length, 2);
  assert.equal(result.envelope.items[0].variant_key, "unselected");
  assert.equal(
    result.envelope.items[0].product_identity.identity_resolution,
    "offer_only",
  );
  assert.equal(
    result.envelope.items[0].supply_signals.candidate_requires_detail_enrichment,
    true,
  );
  assert.equal(result.envelope.page.capture_coverage.exact_sku_identity_count, 0);
});
