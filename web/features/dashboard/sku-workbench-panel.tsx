"use client";

import { FormEvent, useState } from "react";
import { Search, ShieldCheck, TriangleAlert } from "lucide-react";
import { fetchJson } from "../../lib/fetch-json";
import type { SkuWorkbenchSnapshot } from "./contracts";

const unknownLabels: Record<string, string> = {
  candidate_product: "候选尚未晋升为正式商品",
  three_comparable_formal_quotes: "缺少三份同口径正式书面报价",
  ozon_ru_full_cost_scenario: "缺少 Ozon 俄罗斯全成本场景",
  complete_15_item_cost_evidence: "15 项成本仍有未知或缺证据",
  ozon_28_day_real_execution_demand_evidence: "缺少 Ozon 近 28 天真实需求证据",
  approved_product_compliance_quality_passports: "商品、合规或质量 Passport 未批准",
};

const listingFieldLabels: Record<string, string> = {
  sku_combinations_text: "SKU 规格组合",
  material_text: "材质",
  net_weight_text: "净重",
  gross_weight_text: "包装毛重",
  package_dimensions_text: "包装尺寸/体积",
  tier_pricing_text: "完整阶梯价",
  sample_price_text: "样品价",
  domestic_freight_text: "国内运费",
  delivery_time_text: "交期",
  current_stock_text: "当前库存",
  compression_method_text: "压缩方式",
  uncompressed_dimensions_text: "压缩前尺寸",
  compressed_dimensions_text: "压缩后尺寸",
  recovery_result_text: "恢复效果",
  repeat_compression_text: "重复压缩能力",
  defect_handling_text: "瑕疵处理",
  return_terms_text: "退换条件",
  quality_inspection_text: "质检方式",
  packaging_oem_text: "包装/OEM",
  asset_use_authorization_text: "图片/视频授权",
};

function fieldText(value: string | number | boolean | null | undefined) {
  if (value === null || value === undefined || value === "") return "未知";
  return String(value);
}

export function SkuWorkbenchPanel() {
  const [snapshot, setSnapshot] = useState<SkuWorkbenchSnapshot | null>(null);
  const [message, setMessage] = useState("输入 Candidate Ref、Product ID 或 SKU，读取统一证据视图。");
  const [loading, setLoading] = useState(false);

  async function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const reference = (form.elements.namedItem("workbench_ref") as HTMLInputElement).value.trim();
    if (!reference) return;
    setLoading(true);
    setMessage("正在读取商品事实、研究证据、报价、成本、审批与样品状态…");
    const response = await fetchJson<SkuWorkbenchSnapshot | { detail?: unknown }>(
      `/backend/v1/workbench/skus/${encodeURIComponent(reference)}`,
      { cache: "no-store" },
    );
    const result = await response.json();
    if (response.ok && "contract_id" in result) {
      setSnapshot(result);
      setMessage("已加载只读聚合视图；研究证据没有自动晋升为正式商品事实。");
    } else {
      setSnapshot(null);
      const detail = "detail" in result ? result.detail : null;
      setMessage(typeof detail === "string" ? detail : "没有找到该候选或商品。");
    }
    setLoading(false);
  }

  const researchCount = snapshot
    ? Object.values(snapshot.research).reduce((total, rows) => total + rows.length, 0)
    : 0;
  const completeScenarios = snapshot?.profit_scenarios.filter((item) => item.cost_complete).length ?? 0;

  return <section className="sku-workbench-panel" id="sku-workbench">
    <div className="panel-title"><div><p className="eyebrow">REAL SKU WORKBENCH</p><h3>真实 SKU 证据工作台</h3></div><span className="gate">只读聚合</span></div>
    <form className="sku-workbench-search" onSubmit={load}>
      <label>候选 / 商品引用<input name="workbench_ref" placeholder="candidate://compression-main 或 SKU" required /></label>
      <button disabled={loading} type="submit"><Search size={15} />{loading ? "读取中…" : "读取工作台"}</button>
    </form>
    <p className="section-copy">{message}</p>
    {snapshot ? <>
      <div className="sku-workbench-facts">
        <article><span>商品状态</span><strong>{snapshot.product ? snapshot.product.sku : "候选未晋升"}</strong></article>
        <article><span>研究证据</span><strong>{researchCount}</strong></article>
        <article><span>正式报价</span><strong>{snapshot.formal_offers.length} / 3</strong></article>
        <article><span>完整成本场景</span><strong>{completeScenarios}</strong></article>
        <article><span>审批快照</span><strong>{snapshot.approvals.length}</strong></article>
        <article><span>销售单履约</span><strong>{snapshot.sales_fulfillment_plans.length}</strong></article>
      </div>
      <div className="sku-workbench-readiness">
        <div><strong>当前未知项</strong>{snapshot.unknowns.length ? <ul>{snapshot.unknowns.map((item) => <li key={item}>{unknownLabels[item] ?? item}</li>)}</ul> : <p>关键字段已齐备，仍需按审批门逐项复核。</p>}</div>
        <div className="workbench-guardrail"><ShieldCheck size={18} /><p><strong>外部写操作保持关闭</strong><span>不会自动发询价、采购、支付或上架；所有第三方结果仅为研究证据。</span></p></div>
      </div>
      <div className="source-listing-section">
        <div className="source-listing-heading"><strong>采集商品快照</strong><span>{snapshot.research.source_listings.length} 条，仅作研究证据</span></div>
        {snapshot.research.source_listings.length ? <div className="source-listing-grid">{snapshot.research.source_listings.map((item) => {
          const fields = item.fields;
          const unknownFields = fieldText(fields.unknown_fields_text) === "未知"
            ? []
            : fieldText(fields.unknown_fields_text).split(",").filter(Boolean);
          return <article className="source-listing-card" key={item.evidence_id}>
            <div className="source-listing-title"><div><small>Offer {fieldText(fields.listing_id)}</small><strong>{fieldText(fields.title)}</strong></div><span>{item.integrity_valid ? "完整性通过" : "完整性异常"}</span></div>
            <dl>
              <div><dt>供应商主体</dt><dd>{fieldText(fields.supplier_legal_entity ?? fields.supplier_company_name ?? fields.seller_name)}</dd></div>
              <div><dt>价格 / MOQ</dt><dd>{fieldText(fields.price_text)} · {fieldText(fields.moq_text)}</dd></div>
              <div><dt>库存 / 交期</dt><dd>{fieldText(fields.current_stock_text)} · {fieldText(fields.delivery_time_text)}</dd></div>
              <div><dt>SKU 规格组合</dt><dd>{fieldText(fields.sku_combinations_text)}</dd></div>
              <div><dt>材质</dt><dd>{fieldText(fields.material_text)}</dd></div>
              <div><dt>包装尺寸 / 页面件重</dt><dd>{fieldText(fields.package_dimensions_text)} · {fieldText(fields.listed_piece_weight_text)}</dd></div>
              <div><dt>包装 / OEM</dt><dd>{fieldText(fields.packaging_oem_text)}</dd></div>
              <div><dt>产地 / 店铺年限</dt><dd>{fieldText(fields.origin_place ?? fields.supplier_location)} · {fieldText(fields.supplier_years_on_platform_text)}</dd></div>
            </dl>
            <div className="listing-unknowns"><strong>待书面确认 {unknownFields.length} 项</strong>{unknownFields.length ? <p>{unknownFields.map((field) => listingFieldLabels[field] ?? field).join("、")}</p> : <p>页面字段已提取；仍须核验真实性和有效期。</p>}</div>
            <div className="source-listing-meta"><span>证据 …{item.evidence_id.slice(-8)} · {item.review_status ?? "待复核"}</span>{item.source_url ? <a href={item.source_url} rel="noreferrer" target="_blank">查看 1688 来源</a> : <span>来源链接未知</span>}</div>
          </article>;
        })}</div> : <div className="workbench-empty"><TriangleAlert size={20} /><span>尚无真实商品快照。先连接 Browser Bridge、登录专用 1688 会话并配置 Offer ID。</span></div>}
      </div>
    </> : <div className="workbench-empty"><TriangleAlert size={20} /><span>尚未选择真实候选。系统不会用零或推测值填补未知字段。</span></div>}
  </section>;
}
