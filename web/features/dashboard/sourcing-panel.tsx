"use client";

import { Boxes, ShieldCheck } from "lucide-react";
import { sourcingCostDefinitions, costStateLabels, procurementStatusLabels, procurementEventLabels } from "./dashboard-config";
import type { DashboardModel } from "./use-dashboard-controller";


export function SourcingPanel({ model }: { model: DashboardModel }) {
  const { approvedWithoutSample, backupOptions, backupRationales, calculateLogisticsCost, captureLogisticsRateCard, comparisons, createSampleOrder, evidenceRecords, gateReadiness, loadBackupOptions, logisticsBusy, logisticsCalculations, logisticsRateCards, pendingProcurementApprovals, procurementBusy, procurementDrafts, products, recordSampleEvent, requestBackupProcurement, requestProcurement, sampleOrders, setBackupRationales, setProcurementDrafts, skuReadiness, sourcingUploading, supplierPerformance, uploadSupplierComparison } = model;
  const rateCardEvidenceRecords = evidenceRecords.filter((item) => ["operator_logistics_rate_card", "carrier_rate_card", "logistics_rate_card", "carrier_quote"].includes(item.source.toLowerCase()) && ["A", "B"].includes(item.grade));
  const fxEvidenceRecords = evidenceRecords.filter((item) => ["fx_rate_snapshot", "central_bank_fx_rate", "bank_fx_quote"].includes(item.source.toLowerCase()) && ["A", "B"].includes(item.grade));
  return <><section className="sourcing-intake-panel logistics-workspace" id="logistics-workspace">
          <div className="panel-title"><div><p className="eyebrow">LOGISTICS COST INTELLIGENCE</p><h3>物流线路、计费重与 AI 决策辅助</h3></div><span className="badge">{logisticsRateCards.length} 个版本化线路 · {logisticsCalculations.length} 次测算</span></div>
          <p className="section-copy">公式按 Evidence 固化：实重、体积重、进位、最低收费和每票固定费均由确定性引擎计算；AI 只解释异常和建议比价，不能自动改利润、采购或上架。</p>
          <div className="logistics-layout">
            <form className="sourcing-intake logistics-rate-form" onSubmit={captureLogisticsRateCard}>
              <div className="comparison-title"><strong>1. 固化承运商线路版本</strong><span>报价表 → Evidence → 规则</span></div>
              <div className="sourcing-common">
                <label>承运商<input name="logistics_provider" required /></label><label>线路编码<input name="logistics_route_code" required /></label>
                <label>服务名称<input name="logistics_service_name" required /></label><label>平台<input name="logistics_marketplace" defaultValue="OZON" required /></label>
                <label>始发国家<input name="logistics_origin_country" defaultValue="CN" required /></label><label>目的国家<input name="logistics_destination_country" defaultValue="RU" required /></label>
                <label>计价币种<input name="logistics_currency" defaultValue="CNY" maxLength={3} required /></label><label>申报价值币种<input name="logistics_declared_value_currency" defaultValue="RUB" maxLength={3} required /></label>
                <label>每 kg 价格<input name="logistics_price_per_kg" type="number" min="0" step="0.0001" required /></label>
                <label>每票固定费<input name="logistics_base_charge" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>每票最低收费<input name="logistics_minimum_charge" type="number" min="0" step="0.01" defaultValue="0" required /></label>
                <label>体积重除数 cm³/kg<input name="logistics_volumetric_divisor" type="number" min="0" step="1" defaultValue="12000" required /></label><label>计重进位 kg<input name="logistics_weight_increment" type="number" min="0.001" step="0.001" defaultValue="0.001" required /></label>
                <label>最低实重 kg<input name="logistics_min_weight" type="number" min="0" step="0.001" defaultValue="0.001" required /></label><label>最高实重 kg<input name="logistics_max_weight" type="number" min="0.001" step="0.001" required /></label>
                <label>最大长 cm<input name="logistics_max_length" type="number" min="0" step="0.1" defaultValue="0" required /></label><label>最大宽 cm<input name="logistics_max_width" type="number" min="0" step="0.1" defaultValue="0" required /></label>
                <label>最大高 cm<input name="logistics_max_height" type="number" min="0" step="0.1" defaultValue="0" required /></label><label>三边和上限 cm<input name="logistics_max_dimension_sum" type="number" min="0" step="0.1" defaultValue="0" required /></label>
                <label>申报价值下限<input name="logistics_min_declared_value" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>申报价值上限<input name="logistics_max_declared_value" type="number" min="0" step="0.01" defaultValue="0" required /></label>
                <label>生效时间<input name="logistics_effective_at" type="datetime-local" required /></label>
                <label>失效时间<input name="logistics_effective_until" type="datetime-local" /></label><label>报价证据<select name="logistics_evidence_id" required><option value="">选择承运商报价 Evidence</option>{rateCardEvidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.source} · …{item.id.slice(-8)}</option>)}</select></label>
                <label>来源工作表<input name="logistics_source_sheet" placeholder="如 realFBS资费试算表" required /></label><label>来源区域<input name="logistics_source_range" placeholder="如 D5:M24" required /></label>
              </div>
              <button disabled={logisticsBusy}>{logisticsBusy ? "正在固化…" : "保存线路版本"}</button>
            </form>
            <form className="sourcing-intake logistics-calculation-form" onSubmit={calculateLogisticsCost}>
              <div className="comparison-title"><strong>2. 测算单件物流成本</strong><span>只产生 estimate</span></div>
              <div className="sourcing-common">
                <label>线路版本<select name="logistics_calculation_rate_card_id" required><option value="">选择线路</option>{logisticsRateCards.map((item) => <option value={item.id} key={item.id}>{item.provider} · {item.route_code}</option>)}</select></label>
                <label>实重 kg<input name="logistics_physical_weight" type="number" min="0.001" step="0.001" required /></label>
                <label>长 cm<input name="logistics_length" type="number" min="0" step="0.1" defaultValue="0" required /></label><label>宽 cm<input name="logistics_width" type="number" min="0" step="0.1" defaultValue="0" required /></label>
                <label>高 cm<input name="logistics_height" type="number" min="0" step="0.1" defaultValue="0" required /></label><label>申报价值<input name="logistics_declared_value" type="number" min="0" step="0.01" defaultValue="0" required /></label>
                <label>件数<input name="logistics_quantity" type="number" min="1" defaultValue="1" required /></label><label>计价币种兑 CNY<input name="logistics_currency_to_cny_rate" type="number" min="0.0001" step="0.0001" defaultValue="1" required /></label>
                <label>FX Evidence（非 CNY 必填）<select name="logistics_fx_evidence_id"><option value="">CNY 线路无需选择</option>{fxEvidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.source} · …{item.id.slice(-8)}</option>)}</select></label>
                <label className="wide">幂等键<input name="logistics_idempotency_key" placeholder="SKU-线路-报价日期" required /></label>
              </div>
              <button disabled={logisticsBusy || !logisticsRateCards.length}>{logisticsBusy ? "正在计算…" : "计算并生成决策辅助"}</button>
            </form>
          </div>
          {logisticsCalculations.length > 0 && <div className="logistics-result-grid">{logisticsCalculations.slice(0, 6).map((item) => <article className="comparison-card" key={item.id}><strong>预估 {item.total_charge_cny} CNY</strong><small>实重 {item.physical_weight_kg} kg · 体积重 {item.volumetric_weight_kg} kg</small><div className="cm3"><span>最终计费重</span><b>{item.billable_weight_kg} kg</b><small>Evidence …{item.evidence_id.slice(-8)} · actual 需承运商最终账单</small></div></article>)}</div>}
        </section><section className="sourcing-intake-panel" id="sourcing-intake">
          <div className="panel-title"><div><p className="eyebrow">THREE-QUOTE GATE</p><h3>三家供应商证据化比价</h3></div><span className="badge">{pendingProcurementApprovals} 项采购待审批</span></div>
          <form className="sourcing-intake" onSubmit={uploadSupplierComparison}>
            <div className="sourcing-common">
              <label>候选 SKU<select name="sourcing_product_id" required><option value="">选择 SKU</option>{products.map((item) => <option value={item.id} key={item.id}>{item.sku} · {item.name}</option>)}</select></label>
              <label>目标售价 RUB<input name="sale_price_rub" type="number" min="0.01" step="0.01" required /></label><label>RUB/CNY<input name="rub_per_cny" type="number" min="0.0001" step="0.0001" required /></label>
              <label>物流线路版本<select name="logistics_rate_card_id" defaultValue=""><option value="">手填 CNY/kg（兼容）</option>{logisticsRateCards.map((item) => <option value={item.id} key={item.id}>{item.provider} · {item.route_code}</option>)}</select></label><label>线路币种兑 CNY<input name="comparison_logistics_currency_to_cny_rate" type="number" min="0.0001" step="0.0001" defaultValue="1" required /></label>
              <label>线路 FX Evidence<select name="comparison_logistics_fx_evidence_id"><option value="">CNY 线路无需选择</option>{fxEvidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.source} · …{item.id.slice(-8)}</option>)}</select></label>
              <label>手填国际运费 CNY/kg<input name="international_freight" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>包装 CNY<input name="packaging_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>尾程 CNY<input name="last_mile_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>关税率<input name="customs_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
              <label>平台费率<input name="platform_fee_rate" type="number" min="0" max="0.9999" step="0.0001" required /></label><label>广告率<input name="advertising_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
              <label>退货准备率<input name="return_reserve_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label><label>仓储 CNY<input name="warehousing_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>税费 CNY<input name="tax_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>汇兑成本 CNY<input name="fx_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>资金占用 CNY<input name="capital_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>售后 CNY<input name="aftersales_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>损耗准备 CNY<input name="loss_reserve_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>未分类成本 CNY（放行须为 0）<input name="other_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>全成本依据清单<input name="assumption_evidence" type="file" required /></label>
            </div>
            <fieldset className="cost-state-grid"><legend>逐项证据状态 · v1.0.0</legend>{sourcingCostDefinitions.map(([key, label]) => <label key={key}>{label}<select name={`cost_state_${key}`} defaultValue="estimate">{(key === "product_cost" || key === "domestic_logistics" ? ["estimate", "actual"] : ["estimate", "actual", "unknown"]).map((state) => <option value={state} key={state}>{costStateLabels[state as keyof typeof costStateLabels]}</option>)}</select></label>)}</fieldset>
            <div className="supplier-entry-grid">{[1, 2, 3].map((index) => <details open key={index}><summary><span>{index}</span><strong>供应商 {index}</strong><small>原始报价与实测条件</small></summary><div className="supplier-fields">
              <label>供应商标识<input name={`supplier_ref_${index}`} required /></label><label>来源平台<select name={`platform_${index}`} defaultValue="1688"><option value="1688">1688</option><option value="alibaba">Alibaba</option><option value="manual">线下/人工</option></select></label>
              <label>报价快照编号<input name={`external_id_${index}`} required /></label><label>商品标题<input name={`offer_title_${index}`} required /></label>
              <label className="wide">原始链接<input name={`source_url_${index}`} type="url" required /></label><label>币种<input name={`currency_${index}`} defaultValue="CNY" maxLength={3} required /></label>
              <label>单价<input name={`unit_price_${index}`} type="number" min="0.01" step="0.01" required /></label><label>兑 CNY 汇率<input name={`source_to_cny_rate_${index}`} type="number" min="0.0001" step="0.0001" defaultValue="1" required /></label>
              <label>MOQ<input name={`moq_${index}`} type="number" min="1" required /></label><label>重量 kg<input name={`supplier_weight_${index}`} type="number" min="0.001" step="0.001" required /></label>
              <label>长 cm<input name={`supplier_length_${index}`} type="number" min="0" step="0.1" defaultValue="0" required /></label><label>宽 cm<input name={`supplier_width_${index}`} type="number" min="0" step="0.1" defaultValue="0" required /></label>
              <label>高 cm<input name={`supplier_height_${index}`} type="number" min="0" step="0.1" defaultValue="0" required /></label><label>国内物流/件<input name={`domestic_logistics_${index}`} type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label className="wide">报价证据<input name={`supplier_evidence_${index}`} type="file" required /></label>
            </div></details>)}</div>
            <div className="intake-submit"><p>三份报价和共同利润假设都会哈希固化；系统只生成比较与审批申请，不会自动采购。</p><button disabled={sourcingUploading}>{sourcingUploading ? "正在比较…" : "建立三家报价比较"}</button></div>
          </form>
        </section>{gateReadiness && <section className="comparison-panel">
          <div className="panel-title"><div><p className="eyebrow">THREE-CANDIDATE PORTFOLIO</p><h3>三候选组合决策台</h3></div><span className="badge">{gateReadiness.candidate_portfolio.selection_ready_count} / {gateReadiness.candidate_portfolio.target_count} 可进入人工选择</span></div>
          <p className="section-copy">只展示通过候选交接、原件复验和需求报告门的商品；排序只是决策辅助，不会自动选品、采购、定价或上架。</p>
          {gateReadiness.candidate_portfolio.rows.length ? <div className="comparison-grid">{gateReadiness.candidate_portfolio.rows.map((item, index) => <article className="comparison-card" key={item.product.id}>
            <div className="rank">#{index + 1}</div><strong>{item.product.sku} · {item.product.name}</strong>
            <small>{item.supplier_count}/3 家当前供应商 · {item.complete_profit_scenario_count} 个完整正 CM3 场景 · Passport {item.passports_ready ? "已通过" : "未完成"}</small>
            <div className="cm3"><span>当前最佳可用场景</span><b>{item.best_scenario ? `${item.best_scenario.cm3_cny} CNY` : "尚无场景"}</b><small>{item.best_scenario ? `${item.best_scenario.supplier_ref ?? "供应商未知"} · CM3 ${(Number(item.best_scenario.cm3_rate) * 100).toFixed(1)}% · 保本价 ${item.best_scenario.break_even_price_rub || "未知"} RUB` : "需要三报价和全成本证据"}</small></div>
            <div className={item.ready_for_g1_review ? "knowledge-status usable" : "knowledge-status invalid"}><span>{item.ready_for_g1_review ? "证据链满足人工选择门" : item.blockers.join("；")}</span><b>自动执行：禁止</b></div>
          </article>)}</div> : <div className="empty-state">还没有通过资格门的真实候选。历史目录和未复核商品不会进入本组合。</div>}
        </section>}{comparisons.length > 0 && <section className="comparison-panel">
          <div className="panel-title"><div><p className="eyebrow">SOURCING DECISION</p><h3>报价与 CM3 比较</h3></div><span className="gate ready">仅人工提交采购</span></div>
          {comparisons.map((comparison) => <div className="comparison-group" key={comparison.product.id}><div className="comparison-title"><strong>{comparison.product.sku} · {comparison.product.name}</strong><span>{comparison.supplier_count}/3 家供应商</span></div><div className="comparison-grid">{comparison.rows.map((row, index) => {
            const draft = procurementDrafts[row.offer.id] ?? { quantity: String(row.offer.min_order_quantity), rationale: "" };
            const passportReady = skuReadiness.find((item) => item.product.id === comparison.product.id)?.ready_for_validation;
            const unknownCosts = row.scenario ? Object.values(row.scenario.cost_states).filter((state) => state === "unknown").length : 0;
            return <article className="comparison-card" key={row.offer.id}><div className="rank">#{index + 1}</div><strong>{row.offer.supplier_ref}</strong><small>{row.offer.platform} · {row.offer.unit_price} {row.offer.currency} · MOQ {row.offer.min_order_quantity}</small><div className="cm3"><span>预计 CM3 · {row.scenario?.template_id ?? "无模板"}</span><b>{row.scenario ? `${row.scenario.cm3_cny} CNY` : "缺少场景"}</b><small>{row.scenario ? `${(Number(row.scenario.cm3_rate) * 100).toFixed(1)}% · 保本价 ${row.scenario.break_even_price_rub} RUB · ${unknownCosts ? `${unknownCosts} 项未知` : "成本项可追溯"}` : ""}</small></div>
              {row.scenario && <details className="cost-provenance"><summary>查看 15 项成本来源</summary><div>{sourcingCostDefinitions.map(([key, label]) => {
                const state = row.scenario?.cost_states[key] ?? "unknown";
                const evidenceId = row.scenario?.cost_evidence[key];
                return <p className={`cost-source ${state}`} key={key}><span>{label}</span><b>{costStateLabels[state]}</b><code>{evidenceId ? `证据 …${evidenceId.slice(-8)}` : "无证据"}</code></p>;
              })}</div></details>}
              <label>采购数量<input type="number" min={row.offer.min_order_quantity} value={draft.quantity} onChange={(event) => setProcurementDrafts((current) => ({ ...current, [row.offer.id]: { ...draft, quantity: event.target.value } }))} /></label>
              <label>选择理由<textarea value={draft.rationale} onChange={(event) => setProcurementDrafts((current) => ({ ...current, [row.offer.id]: { ...draft, rationale: event.target.value } }))} placeholder="为什么选择它，而不是另外两家？" /></label>
              <button disabled={!comparison.ready_for_procurement_review || !passportReady || !row.has_positive_cm3} onClick={() => requestProcurement(comparison, row)}>提交双人采购审批</button>{!passportReady && <em>需先批准三本 Passport</em>}
            </article>;
          })}</div></div>)}
        </section>}<section className="procurement-panel">
          <div className="panel-title">
            <div><p className="eyebrow">SAMPLE PROCUREMENT</p><h3>样品采购与供应商验证</h3></div>
            <span className="gate ready">每一步必须有证据</span>
          </div>
          <div className="procurement-guardrail"><ShieldCheck size={17} /><p><strong>真实付款不会自动执行。</strong><span>已批准候选只能建立样品跟踪；供应商切换会生成一项新的双人审批。</span></p></div>
          {approvedWithoutSample.length > 0 && <div className="approved-order-queue">
            <strong>已通过双人审批，等待建立样品单</strong>
            {approvedWithoutSample.map((approval) => <button key={approval.id} disabled={procurementBusy === approval.id} onClick={() => createSampleOrder(approval.id)}>
              {procurementBusy === approval.id ? "正在建立…" : `建立样品单 · ${String(approval.payload.quantity ?? "-")} 件`}
            </button>)}
          </div>}
          {sampleOrders.length ? <div className="sample-order-grid">{sampleOrders.map((order) => {
            const performance = supplierPerformance.find((item) => item.supplier_ref === order.supplier_ref);
            const terminal = order.next_events.length === 0;
            return <article className="sample-order-card" key={order.id}>
              <div className="sample-order-head"><div><strong>{order.product.sku} · {order.product.name}</strong><small>{order.supplier_ref} · {order.quantity} 件 · {order.unit_price} {order.currency}/件</small></div><span className={`sample-state ${terminal ? "terminal" : ""}`}>{procurementStatusLabels[order.status] ?? order.status}</span></div>
              <div className="sample-progress">{["确认", "发货", "签收", "验货", "定样"].map((label, index) => <span className={order.events.length > index ? "done" : ""} key={label}>{label}</span>)}</div>
              <div className="sample-facts">
                <div><span>证据事件</span><b>{order.events.length}</b></div><div><span>供应商评分</span><b>{performance?.score ? `${performance.score} 分` : "待形成"}</b></div><div><span>样品成功</span><b>{performance ? `${performance.completed_sample_count}/${performance.sample_order_count}` : "-"}</b></div>
              </div>
              {order.events.length > 0 && <details className="sample-timeline"><summary>查看不可变进度记录</summary><ol>{order.events.map((item) => <li key={item.id}><span>{item.sequence}</span><div><strong>{procurementEventLabels[item.event_type] ?? item.event_type}</strong><small>{new Date(item.effective_at).toLocaleString("zh-CN")} · 证据 {item.evidence_id.slice(-8)}</small></div></li>)}</ol></details>}
              {!terminal && <form className="sample-event-form" onSubmit={(event) => recordSampleEvent(event, order)}>
                <strong>下一步：{order.status === "inspected" ? "形成样品决定" : procurementEventLabels[order.next_events.find((item) => item !== "cancelled") ?? ""]}</strong>
                {order.status === "approved_to_order" && <div className="sample-event-fields"><label>供应商订单号<input name="supplier_order_ref" required /></label><label>承诺交付时间<input name="promised_delivery_at" type="datetime-local" required /></label></div>}
                {order.status === "order_confirmed" && <div className="sample-event-fields"><label>物流单号<input name="tracking_ref" required /></label><label>承运商<input name="carrier" required /></label></div>}
                {order.status === "shipped" && <div className="sample-event-fields"><label>签收数量<input name="received_quantity" type="number" min="0" max={order.quantity} defaultValue={order.quantity} required /></label><label>破损数量<input name="damaged_quantity" type="number" min="0" defaultValue="0" required /></label></div>}
                {(order.status === "received" || order.status === "rework_required") && <div className="sample-event-fields"><label>验货数量<input name="inspected_quantity" type="number" min="1" max={order.quantity} defaultValue={order.quantity} required /></label><label>通过数量<input name="passed_quantity" type="number" min="0" max={order.quantity} defaultValue={order.quantity} required /></label><label>缺陷数<input name="defect_count" type="number" min="0" defaultValue="0" required /></label><label>验货结论<select name="inspection_result" defaultValue="passed"><option value="passed">通过</option><option value="failed">不通过</option><option value="rework">需返工</option></select></label></div>}
                {order.status === "inspected" && <div className="sample-event-fields"><label>样品决定<select name="sample_decision" defaultValue="golden_sample_approved"><option value="golden_sample_approved">批准为黄金样</option><option value="rework_required">要求返工</option><option value="sample_rejected">淘汰供应商样品</option></select></label><label>黄金样编号 / 决定原因<input name="decision_detail" required /></label></div>}
                <label className="sample-evidence">本步原始证据<input name="event_evidence" type="file" required /></label>
                <button disabled={procurementBusy === order.id}>{procurementBusy === order.id ? "正在固化…" : "提交进度与证据"}</button>
              </form>}
              <div className="backup-control">
                <button className="secondary" disabled={procurementBusy === order.id} onClick={() => loadBackupOptions(order.id)}>查看备用供应商</button>
                <small>只提供建议，不自动切换</small>
              </div>
              {backupOptions[order.id] && <div className="backup-list">{backupOptions[order.id].length ? backupOptions[order.id].map((option) => {
                const rationaleKey = `${order.id}:${option.offer.id}`;
                return <div key={option.offer.id}><div><strong>{option.offer.supplier_ref}</strong><small>{option.offer.unit_price} {option.offer.currency} · MOQ {option.offer.min_order_quantity} · CM3 {option.scenario.cm3_cny} CNY</small><input value={backupRationales[rationaleKey] ?? ""} onChange={(event) => setBackupRationales((current) => ({ ...current, [rationaleKey]: event.target.value }))} placeholder="填写切换理由" /></div><button disabled={procurementBusy === order.id} onClick={() => requestBackupProcurement(order, option)}>重新提交审批</button></div>;
              }) : <p>暂无正 CM3 备用方案。</p>}</div>}
            </article>;
          })}</div> : <div className="empty"><Boxes size={25} /><strong>还没有受控样品单</strong><p>三家比价通过、Passport 批准并完成双人采购审批后，才会进入这里。</p></div>}
          {supplierPerformance.length > 0 && <div className="supplier-scoreboard"><strong>供应商实绩榜</strong><div>{supplierPerformance.map((item) => <article key={item.supplier_ref}><span>{item.supplier_ref}</span><b>{item.score ? `${item.score} 分` : "数据不足"}</b><small>质量 {item.quality_yield ? `${(Number(item.quality_yield) * 100).toFixed(0)}%` : "-"} · 准时 {item.on_time_rate ? `${(Number(item.on_time_rate) * 100).toFixed(0)}%` : "-"} · {item.evidence_count} 份证据</small></article>)}</div></div>}
        </section></>;
}
