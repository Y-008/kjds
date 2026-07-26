"use client";

import { Copy, FileCheck2, Search, ShieldCheck } from "lucide-react";
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

const dispatchStatusLabels = {
  pending: "等待独立复核",
  accepted: "已核验真实发送",
  rejected: "发送证明已拒绝",
} as const;

export function SupplierQuoteWorkspace({ model }: { model: DashboardModel }) {
  const {
    canReviewSupplierQuotes,
    captureSupplierRfqDispatch,
    captureSupplierQuote,
    copySupplierRfqMessage,
    createSupplierRfq,
    logisticsRateCards,
    marketplaceCatalogItems,
    marketplaceCatalogStoreRef,
    products,
    reviewSupplierRfqDispatch,
    reviewSupplierQuote,
    reviewingKey,
    sourcingUploading,
    supplierRfqBusy,
    supplierRfqDispatchBusy,
    supplierRfqDispatches,
    supplierRfqPackages,
    supplierQuoteEvidence,
    uploadSupplierComparison,
  } = model;
  const acceptedQuotes = supplierQuoteEvidence.filter((item) => item.status === "accepted");
  const acceptedDispatches = supplierRfqDispatches.filter((item) => item.status === "accepted");
  const boundCatalogItems = marketplaceCatalogItems.filter((item) => item.canonical_product_id);

  return (
    <section className="sourcing-intake-panel quote-authority-workspace" id="supplier-quote-authority">
      <div className="panel-title">
        <div>
          <p className="eyebrow">SUPPLIER QUOTE AUTHORITY</p>
          <h3>询价包 → 发送证明 → 回复归因 → 报价复核 → 三家 CM3</h3>
        </div>
        <span className="badge">
          {supplierRfqPackages.length} 个询价包 · {acceptedDispatches.length} 个已核验发送 · {acceptedQuotes.length} 份已接受报价
        </span>
      </div>
      <p className="section-copy">
        先从已绑定且哈希仍为最新的 Ozon 商品冻结统一采购要求，再由运营人工发送给供应商并上传平台原始证明。复制不等于发送，发送不等于送达或回复；公开展示价永远不能成为采购报价，上传人与复核人必须是不同身份。
      </p>

      <div className="rfq-workspace-grid">
        <form className="sourcing-intake rfq-create-form" onSubmit={createSupplierRfq}>
          <div className="comparison-title">
            <strong><Search size={16} /> 1. 冻结可比询价包</strong>
            <span>{marketplaceCatalogStoreRef} · 只生成草稿</span>
          </div>
          <div className="sourcing-common">
            <label className="wide">已绑定 Ozon Listing
              <select name="rfq_offer_id" required defaultValue="">
                <option value="" disabled>选择当前目录商品</option>
                {boundCatalogItems.map((item) => <option value={item.offer_id} key={`${item.snapshot_id}:${item.offer_id}`}>
                  {item.offer_id} · {item.name} · SKU {item.marketplace_sku ?? "—"}
                </option>)}
              </select>
            </label>
            <label>幂等编号<input name="rfq_idempotency_key" placeholder="例如 2105343364UB-20260726-v1" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,159}" required /></label>
            <label>数量阶梯<input name="rfq_quantity_breaks" defaultValue="1,10,50,100" required /></label>
            <label>回复截止<input name="rfq_response_due_at" type="datetime-local" required /></label>
            <label>交付目的地<input name="rfq_destination" placeholder="国内集货仓；最终地址下单前确认" required /></label>
            <label className="wide">采购规格（每行“名称=要求”）
              <textarea name="rfq_specifications" rows={7} placeholder={"额定载重=必须明确本次报价档位\n电压频率=220V±10%，50Hz\n控制方式=有线与无线配置逐项确认"} required />
            </label>
            <label className="wide">必需文件（每行一项）
              <textarea name="rfq_required_documents" rows={4} placeholder={"营业执照与生产主体\n已有合规证书编号，不得虚构\n质检报告、说明书与质保条款"} required />
            </label>
            <label className="wide">包装要求（每行一项）
              <textarea name="rfq_packaging_requirements" rows={4} placeholder={"确认单件净重、毛重与外箱尺寸\n防潮防跌落方案\n中性包装与定制包装分别报价"} required />
            </label>
            <label className="wide">运营备注<textarea name="rfq_operator_notes" rows={3} placeholder="例如：不接受低载重引流价；每个数量阶梯必须对应同一冻结规格。" /></label>
          </div>
          <div className="rfq-checks">
            <label><input name="rfq_sample_required" type="checkbox" defaultChecked /> 需要样品报价</label>
            <label><input name="rfq_tax_invoice_required" type="checkbox" defaultChecked /> 需要含税发票</label>
          </div>
          <p className="field-help">
            商品标题、重量和尺寸只是 Ozon 目录观察；采购规格必须由运营明确填写，系统不会把目录属性猜成供应商承诺。
          </p>
          <button disabled={supplierRfqBusy || !boundCatalogItems.length}>
            {supplierRfqBusy ? "正在复验并冻结…" : boundCatalogItems.length ? "创建 C 级不可变询价包" : "先绑定当前 Ozon Listing"}
          </button>
        </form>

        <div className="rfq-package-list">
          <div className="comparison-title">
            <strong><Copy size={16} /> 待人工发送</strong>
            <span>复制 ≠ 已发送 ≠ 已报价</span>
          </div>
          {supplierRfqPackages.length ? supplierRfqPackages.map((item) => {
            const requirement = item.package.buyer_requirement;
            const observation = item.package.catalog_observation;
            const dimensions = observation.package_dimensions_cm;
            const dispatches = supplierRfqDispatches.filter(
              (dispatch) => dispatch.dispatch.rfq.evidence_id === item.evidence.id,
            );
            return <article className="rfq-package-card" key={item.evidence.id}>
              <div className="rfq-card-heading">
                <div>
                  <span className="gate">C 级草稿</span>
                  <strong>{item.package.product.sku}</strong>
                  <small>Ozon Offer {item.package.listing.offer_id} · SKU {item.package.listing.marketplace_sku ?? "—"}</small>
                </div>
                <button type="button" onClick={() => copySupplierRfqMessage(item)}><Copy size={13} /> 复制询价文案</button>
              </div>
              <div className="rfq-facts">
                <span>阶梯 <strong>{requirement.quantity_breaks.join(" / ")}</strong></span>
                <span>截止 <strong>{new Date(requirement.response_due_at).toLocaleString("zh-CN")}</strong></span>
                <span>目录实重 <strong>{observation.package_weight_kg ?? "未知"} kg</strong></span>
                <span>目录尺寸 <strong>{dimensions ? `${dimensions.length}×${dimensions.width}×${dimensions.height} cm` : "未知"}</strong></span>
              </div>
              <details>
                <summary>查看并手工复制完整询价正文</summary>
                <pre>{item.package.message_text}</pre>
              </details>
              <code>Evidence {item.evidence.id} · package {item.package.package_hash}</code>
              <p>未自动联系供应商、未采购、未付款、未创建正式报价、未写入 Ozon。</p>

              <form
                className="rfq-dispatch-form"
                onSubmit={(event) => captureSupplierRfqDispatch(event, item)}
              >
                <div className="rfq-dispatch-heading">
                  <strong>2. 登记一次真实人工发送</strong>
                  <span>必须逐字发送上方冻结正文</span>
                </div>
                <div className="sourcing-common">
                  <label>
                    供应商标识
                    <input name="dispatch_supplier_ref" placeholder="1688 店铺/供应商稳定编号" required />
                  </label>
                  <label>
                    来源平台
                    <select name="dispatch_supplier_platform" defaultValue="1688">
                      <option value="1688">1688</option>
                      <option value="alibaba">Alibaba</option>
                      <option value="manual">线下/人工</option>
                    </select>
                  </label>
                  <label className="wide">
                    供应商主页或稳定定位
                    <input
                      name="dispatch_supplier_locator"
                      placeholder="1688/Alibaba 必须填写对应平台原始 URL"
                      required
                    />
                  </label>
                  <label>
                    会话/消息编号
                    <input name="dispatch_conversation_ref" placeholder="可回查的会话或消息编号" required />
                  </label>
                  <label>
                    实际发送时间
                    <input name="dispatch_sent_at" type="datetime-local" required />
                  </label>
                  <label>
                    幂等编号
                    <input
                      name="dispatch_idempotency_key"
                      placeholder="供应商+RFQ+发送时间"
                      pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,159}"
                      required
                    />
                  </label>
                  <label className="wide">
                    平台原始截图/会话导出
                    <input name="dispatch_proof_file" type="file" required />
                  </label>
                </div>
                <p className="field-help">
                  仅在你已经实际发送后上传。证明须同时看清供应商身份、完整询价正文、发送时间和会话；本按钮不会替你联系供应商。
                </p>
                <button
                  disabled={supplierRfqDispatchBusy === `capture:${item.evidence.id}`}
                >
                  {supplierRfqDispatchBusy === `capture:${item.evidence.id}`
                    ? "正在逐字复验并固化…"
                    : "固化为 B 级发送证明"}
                </button>
              </form>

              {dispatches.length ? <div className="rfq-dispatch-list">
                {dispatches.map((dispatch) => {
                  const busy = supplierRfqDispatchBusy === `review:${dispatch.evidence.id}`;
                  return <article
                    className={`rfq-dispatch-card ${dispatch.status}`}
                    key={dispatch.evidence.id}
                  >
                    <div className="rfq-dispatch-card-heading">
                      <span className={`gate ${dispatch.status === "accepted" ? "ready" : dispatch.status === "rejected" ? "blocked" : ""}`}>
                        {dispatchStatusLabels[dispatch.status]}
                      </span>
                      <strong>
                        {dispatch.dispatch.supplier.supplier_ref} · {dispatch.dispatch.supplier.supplier_platform}
                      </strong>
                      <small>
                        {new Date(dispatch.dispatch.sent_at).toLocaleString("zh-CN")} · 会话 {dispatch.dispatch.conversation_ref}
                      </small>
                      <code>
                        Evidence {dispatch.evidence.id} · proof {dispatch.dispatch.proof.sha256}
                      </code>
                    </div>
                    <div className="rfq-dispatch-truth">
                      已登记发送证明；送达、供应商回复、有效报价、采购、付款与 Ozon 写入仍全部为 false。
                    </div>
                    {dispatch.status === "pending" && canReviewSupplierQuotes ? <form
                      className="rfq-dispatch-review"
                      onSubmit={(event) => reviewSupplierRfqDispatch(event, dispatch.evidence.id)}
                    >
                      <label><input name="dispatch_authentic_platform_proof" type="checkbox" /> 平台原件真实完整</label>
                      <label><input name="dispatch_supplier_identity_matches" type="checkbox" /> 供应商身份匹配</label>
                      <label><input name="dispatch_frozen_message_matches" type="checkbox" /> 冻结正文逐字匹配</label>
                      <label><input name="dispatch_timestamp_and_conversation_match" type="checkbox" /> 时间与会话匹配</label>
                      <select name="dispatch_review_decision" defaultValue="accepted">
                        <option value="accepted">接受为已核验发送</option>
                        <option value="rejected">拒绝证明</option>
                      </select>
                      <textarea
                        name="dispatch_review_rationale"
                        placeholder="记录平台原件、供应商身份、正文与会话时间的核验依据"
                        required
                      />
                      <button disabled={busy}>{busy ? "正在固化复核…" : "提交不可变复核"}</button>
                    </form> : null}
                  </article>;
                })}
              </div> : null}
            </article>;
          }) : <div className="empty-state">还没有询价包。先选择已绑定的当前 Ozon Listing，明确采购规格后冻结。</div>}
        </div>
      </div>

      <div className="quote-stage-grid">
        <form className="sourcing-intake quote-source-form" onSubmit={captureSupplierQuote}>
          <div className="comparison-title">
            <strong><Search size={16} /> 3. 固化单份供应商回复</strong>
            <span>不会创建 SupplierOffer</span>
          </div>
          <div className="sourcing-common">
            <label>候选 SKU<select name="quote_product_id" required><option value="">选择候选商品</option>{products.map((item) => <option value={item.id} key={item.id}>{item.sku} · {item.name}</option>)}</select></label>
            <label>对应询价包<select name="quote_rfq_package_evidence_id" defaultValue=""><option value="">未关联历史询价包</option>{supplierRfqPackages.map((item) => <option value={item.evidence.id} key={item.evidence.id}>{item.package.product.sku} · …{item.evidence.id.slice(-8)}</option>)}</select></label>
            <label className="wide">
              对应已核验发送证明
              <select name="quote_rfq_dispatch_evidence_id" defaultValue="">
                <option value="">未关联发送证明</option>
                {acceptedDispatches.map((item) => <option value={item.evidence.id} key={item.evidence.id}>
                  {item.dispatch.rfq.product_sku} · {item.dispatch.supplier.supplier_ref} · …{item.evidence.id.slice(-8)}
                </option>)}
              </select>
            </label>
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
          <p className="field-help">
            确认报价和形式发票必须填写失效时间；如选择发送证明，后端会强制校验候选商品、询价包与供应商身份一致，并把回复绑定到同一次真实发送。
          </p>
          <button disabled={sourcingUploading}>{sourcingUploading ? "正在固化…" : "保存为 B 级报价线索"}</button>
        </form>

        <div className="quote-review-queue">
          <div className="comparison-title">
            <strong><ShieldCheck size={16} /> 4. 报价独立复核队列</strong>
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
          <strong><FileCheck2 size={16} /> 5. 最终化三家正式比价</strong>
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
