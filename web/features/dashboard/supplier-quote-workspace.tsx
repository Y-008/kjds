"use client";

import { FileCheck2, Search, ShieldCheck } from "lucide-react";
import { sourcingCostDefinitions, costStateLabels } from "./dashboard-config";
import type { DashboardModel } from "./use-dashboard-controller";

const quoteKindLabels = {
  public_display_price: "公开展示价（只作研究）",
  supplier_confirmed_quote: "供应商确认报价",
  proforma_invoice: "形式发票",
} as const;

const quoteStatusLabels = {
  pending: "等待独立复核",
  accepted: "已独立接受",
  rejected: "已拒绝",
  research_only: "仅研究线索",
} as const;

export function SupplierQuoteWorkspace({ model }: { model: DashboardModel }) {
  const {
    canReviewSupplierQuotes,
    captureSupplierQuote,
    logisticsRateCards,
    products,
    reviewSupplierQuote,
    reviewingKey,
    sourcingUploading,
    supplierQuoteEvidence,
    uploadSupplierComparison,
  } = model;
  const acceptedQuotes = supplierQuoteEvidence.filter((item) => item.status === "accepted");

  return (
    <section className="sourcing-intake-panel quote-authority-workspace" id="supplier-quote-authority">
      <div className="panel-title">
        <div>
          <p className="eyebrow">SUPPLIER QUOTE AUTHORITY</p>
          <h3>线索 → 独立复核 → 三家正式比价</h3>
        </div>
        <span className="badge">{acceptedQuotes.length} 份已接受 · {supplierQuoteEvidence.length} 份原件</span>
      </div>
      <p className="section-copy">
        1688 页面价、聊天和文件先进入 B 级线索。公开展示价永远不能成为采购报价；上传人与复核人必须是不同身份。
      </p>

      <div className="quote-stage-grid">
        <form className="sourcing-intake quote-source-form" onSubmit={captureSupplierQuote}>
          <div className="comparison-title">
            <strong><Search size={16} /> 1. 固化单份供应商原件</strong>
            <span>不会创建 SupplierOffer</span>
          </div>
          <div className="sourcing-common">
            <label>候选 SKU<select name="quote_product_id" required><option value="">选择候选商品</option>{products.map((item) => <option value={item.id} key={item.id}>{item.sku} · {item.name}</option>)}</select></label>
            <label>资料类型<select name="quote_document_kind" required defaultValue=""><option value="" disabled>选择原件类型</option><option value="public_display_price">公开展示价（只作研究）</option><option value="supplier_confirmed_quote">供应商确认报价</option><option value="proforma_invoice">形式发票</option></select></label>
            <label>供应商标识<input name="quote_supplier_ref" required /></label>
            <label>来源平台<select name="quote_platform" defaultValue="1688"><option value="1688">1688</option><option value="alibaba">Alibaba</option><option value="manual">线下/人工</option></select></label>
            <label>报价快照编号<input name="quote_external_id" placeholder="供应商+日期+版本" required /></label>
            <label>商品标题<input name="quote_title" required /></label>
            <label className="wide">原始链接<input name="quote_source_url" type="url" required /></label>
            <label>币种<input name="quote_currency" defaultValue="CNY" maxLength={3} required /></label>
            <label>单价<input name="quote_unit_price" type="number" min="0.01" step="0.01" required /></label>
            <label>兑 CNY 汇率<input name="quote_source_to_cny_rate" type="number" min="0.0001" step="0.0001" defaultValue="1" required /></label>
            <label>MOQ<input name="quote_moq" type="number" min="1" required /></label>
            <label>重量 kg<input name="quote_weight" type="number" min="0.001" step="0.001" required /></label>
            <label>长 cm<input name="quote_length" type="number" min="0" step="0.1" defaultValue="0" required /></label>
            <label>宽 cm<input name="quote_width" type="number" min="0" step="0.1" defaultValue="0" required /></label>
            <label>高 cm<input name="quote_height" type="number" min="0" step="0.1" defaultValue="0" required /></label>
            <label>国内物流/件<input name="quote_domestic_logistics" type="number" min="0" step="0.01" defaultValue="0" required /></label>
            <label>报价生效时间<input name="quote_effective_at" type="datetime-local" required /></label>
            <label>报价失效时间<input name="quote_effective_until" type="datetime-local" /></label>
            <label className="wide">原始文件/截图<input name="quote_evidence_file" type="file" required /></label>
          </div>
          <p className="field-help">确认报价和形式发票必须填写失效时间；公开页面价可留空，但只会进入研究线索。</p>
          <button disabled={sourcingUploading}>{sourcingUploading ? "正在固化…" : "保存为 B 级报价线索"}</button>
        </form>

        <div className="quote-review-queue">
          <div className="comparison-title">
            <strong><ShieldCheck size={16} /> 2. 独立复核队列</strong>
            <span>{canReviewSupplierQuotes ? "当前身份可复核" : "需要 Reviewer / Compliance / Admin"}</span>
          </div>
          {supplierQuoteEvidence.length ? supplierQuoteEvidence.map((item) => {
            const source = item.evidence;
            const terms = source.metadata.offer_data;
            const busy = reviewingKey === `supplier-quote:${source.id}`;
            return <article className={`quote-review-card ${item.status}`} key={source.id}>
              <div>
                <span className={`gate ${item.status === "accepted" ? "ready" : item.status === "rejected" ? "blocked" : ""}`}>{quoteStatusLabels[item.status]}</span>
                <strong>{source.metadata.supplier_ref} · {terms.unit_price} {terms.currency}</strong>
                <small>{quoteKindLabels[source.metadata.document_kind]} · MOQ {terms.min_order_quantity} · {terms.weight_kg} kg</small>
                <code>{source.id}</code>
              </div>
              {item.status === "pending" && canReviewSupplierQuotes ? <form onSubmit={(event) => reviewSupplierQuote(event, source.id)}>
                <label><input name="quote_authentic_original" type="checkbox" /> 原件真实完整</label>
                <label><input name="quote_supplier_identity_matches" type="checkbox" /> 供应商身份匹配</label>
                <label><input name="quote_product_spec_matches" type="checkbox" /> 冻结规格匹配</label>
                <label><input name="quote_amount_currency_moq_matches" type="checkbox" /> 金额、币种、MOQ 匹配</label>
                <label><input name="quote_validity_and_delivery_terms_present" type="checkbox" /> 有效期和交付条件齐全</label>
                <select name="quote_review_decision" defaultValue="accepted"><option value="accepted">接受为确认报价</option><option value="rejected">拒绝</option></select>
                <textarea name="quote_review_rationale" placeholder="记录核验依据与差异" required />
                <button disabled={busy}>{busy ? "正在复核…" : "提交不可变复核"}</button>
              </form> : null}
            </article>;
          }) : <div className="empty-state">还没有供应商资料。先录入公开线索或真实报价原件。</div>}
        </div>
      </div>

      <form className="sourcing-intake quote-finalize-form" onSubmit={uploadSupplierComparison}>
        <div className="comparison-title">
          <strong><FileCheck2 size={16} /> 3. 最终化三家正式比价</strong>
          <span>只读取已复核冻结条款</span>
        </div>
        <div className="sourcing-common">
          <label>候选 SKU<select name="sourcing_product_id" required><option value="">选择 SKU</option>{products.map((item) => <option value={item.id} key={item.id}>{item.sku} · {item.name}</option>)}</select></label>
          {[1, 2, 3].map((index) => <label key={index}>已接受报价 {index}<select name={`quote_evidence_id_${index}`} required><option value="">选择报价原件</option>{acceptedQuotes.map((item) => <option value={item.evidence.id} key={item.evidence.id}>{item.evidence.metadata.supplier_ref} · {item.evidence.metadata.offer_data.unit_price} {item.evidence.metadata.offer_data.currency} · …{item.evidence.id.slice(-8)}</option>)}</select></label>)}
          <label>目标售价 RUB<input name="sale_price_rub" type="number" min="0.01" step="0.01" required /></label>
          <label>RUB/CNY<input name="rub_per_cny" type="number" min="0.0001" step="0.0001" required /></label>
          <label>物流线路版本<select name="logistics_rate_card_id" defaultValue=""><option value="">手填 CNY/kg（兼容）</option>{logisticsRateCards.map((item) => <option value={item.id} key={item.id}>{item.provider} · {item.route_code}</option>)}</select></label>
          <label>线路币种兑 CNY<input name="comparison_logistics_currency_to_cny_rate" type="number" min="0.0001" step="0.0001" defaultValue="1" required /></label>
          <label>线路 FX Evidence<input name="comparison_logistics_fx_evidence_id" placeholder="非 CNY 线路必填 Evidence ID" /></label>
          <label>手填国际运费 CNY/kg<input name="international_freight" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>包装 CNY<input name="packaging_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>尾程 CNY<input name="last_mile_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>关税率<input name="customs_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
          <label>平台费率<input name="platform_fee_rate" type="number" min="0" max="0.9999" step="0.0001" required /></label>
          <label>广告率<input name="advertising_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
          <label>退货准备率<input name="return_reserve_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
          <label>仓储 CNY<input name="warehousing_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>税费 CNY<input name="tax_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>汇兑成本 CNY<input name="fx_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>资金占用 CNY<input name="capital_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>售后 CNY<input name="aftersales_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>损耗准备 CNY<input name="loss_reserve_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>未分类成本 CNY<input name="other_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
          <label>全成本依据清单<input name="assumption_evidence" type="file" required /></label>
        </div>
        <fieldset className="cost-state-grid">
          <legend>逐项证据状态 · 报价成本强制 estimate</legend>
          {sourcingCostDefinitions.map(([key, label]) => {
            const quoted = key === "product_cost" || key === "domestic_logistics";
            return <label key={key}>{label}{quoted ? <><select defaultValue="estimate" disabled><option value="estimate">{costStateLabels.estimate}</option></select><input type="hidden" name={`cost_state_${key}`} value="estimate" /></> : <select name={`cost_state_${key}`} defaultValue="estimate"><option value="estimate">{costStateLabels.estimate}</option><option value="unknown">{costStateLabels.unknown}</option></select>}</label>;
          })}
        </fieldset>
        <div className="intake-submit">
          <p>系统会再次复验三份原件、复核凭证、候选归属和供应商唯一性；不会自动采购、联系供应商或上架。</p>
          <button disabled={sourcingUploading || acceptedQuotes.length < 3}>{sourcingUploading ? "正在最终化…" : "生成三家报价与 CM3"}</button>
        </div>
      </form>
    </section>
  );
}
