"use client";

import { useEffect, useState } from "react";
import {
  BarChart3,
  CheckCircle2,
  CircleDollarSign,
  Database,
  Image as ImageIcon,
  Layers3,
  Link2,
  Megaphone,
  PackageSearch,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingDown,
} from "lucide-react";
import type { DashboardModel } from "./use-dashboard-controller";

const statusLabels: Record<string, string> = {
  compliance_hold: "合规冻结",
  compliance_review_required: "需要合规复核",
  out_of_stock: "缺货，停止买量",
  market_snapshot_stale: "同行快照已过期",
  cost_authority_required: "需要实际成本复核",
  source_cost_uncompetitive: "当前货源成本无竞争力",
  price_reset_required: "优先进行价格重置实验",
  content_rebuild_required: "优先重做内容",
  review_depth_required: "先积累真实评价",
  ad_test_eligible: "可进入限额广告实验",
  organic_conversion_required: "先证明自然转化",
};

const actionLabels: Record<string, string> = {
  hold_listing: "暂停增长动作并解决合规风险",
  complete_compliance_review: "完成独立合规复核",
  replenishment_review: "评估补货后再恢复流量",
  refresh_market_snapshot: "刷新同款同行价格证据",
  verify_actual_landed_cost: "复核十五项实际落地成本",
  replace_supplier_or_bundle: "更换供应商或重新定义商品组合",
  run_price_reset_experiment: "建立有止损线的价格实验",
  complete_content_roles: "补齐七类商品内容",
  build_verified_review_depth: "积累可验证的真实评价",
  prove_organic_conversion: "先证明自然转化率",
  keep_ads_off: "广告保持关闭",
  start_capped_ad_experiment: "建立有预算上限的广告实验",
};

const gateLabels: Record<string, string> = {
  snapshot_fresh: "同行快照 ≤ 7 天",
  cost_release_ready: "实际落地成本已复核",
  compliance_clear: "合规风险已清除",
  stock_available: "库存可售",
  price_economically_competitive: "成本允许进入市场价格带",
  price_market_aligned: "当前售价处于市场带",
  content_ready: "内容分 ≥ 90",
  rating_ready: "评分 ≥ 4.5",
  review_depth_ready: "真实评价 ≥ 5",
  conversion_observed: "已有真实转化率",
  orders_observed: "近 14 天有订单",
  positive_target_acos: "目标 ACOS 为正",
};

const roleLabels: Record<string, string> = {
  hero: "白底主图",
  dimensions: "尺寸与比例",
  anti_slip: "防滑与结构细节",
  load_proof: "承重证据",
  storage: "折叠收纳",
  use_cases: "真实使用场景",
  package: "包装与清单",
  benefits: "核心卖点",
  proof: "材料与性能证据",
  aftersales: "售后与限制",
};

export function MarketplaceGrowthPanel({ model }: { model: DashboardModel }) {
  const [localNow, setLocalNow] = useState("");
  const canBindExistingListing = model.webSession?.roles.some(
    (role) => role === "operator" || role === "admin",
  ) ?? false;
  const scenarioOptions = model.comparisons.flatMap((comparison) =>
    comparison.rows.flatMap((row) =>
      row.scenario ? [{
        id: row.scenario.id,
        label: `${comparison.product.sku} · ${row.offer.supplier_ref} · CM3 ${row.scenario.cm3_rate}`,
      }] : [],
    ),
  );
  const plan = model.marketplaceGrowthPlan;
  const ozonRawEvidence = model.evidenceRecords.filter(
    (item) => item.source === "ozon-isolated-read-worker" && item.grade === "A",
  );

  useEffect(() => {
    setLocalNow(new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 16));
  }, []);

  return (
    <div className="workspace-page growth-page">
      <section className="growth-hero">
        <div>
          <span><Sparkles size={15} /> EVIDENCE-AWARE GROWTH</span>
          <h2>先判断“为什么不出单”，再决定价格、内容还是广告。</h2>
          <p>系统不会把 1688 展示价当成落地成本，也不会因为能创建广告就建议投放。方案必须同时穿过利润、市场、库存、评价、内容、转化和合规门。</p>
        </div>
        <div className="growth-boundary">
          <ShieldCheck size={23} />
          <strong>本页面只生成建议</strong>
          <p>自动改价：关闭<br />自动投广告：关闭<br />自动发布：关闭</p>
        </div>
      </section>

      <section className="growth-fact-hub catalog-hub">
        <div className="section-heading">
          <div>
            <span>VERIFIED COMMERCE DATA HUB</span>
            <h3>真实 Ozon 商品目录</h3>
            <p>只从完整性已复验的 Seller 原始响应同步 SKU、详情、价格、库存、属性和媒体引用。</p>
          </div>
          <button
            type="button"
            onClick={() => void model.loadMarketplaceCatalog()}
            disabled={model.marketplaceCatalogBusy}
          >
            <Database size={14} />
            {model.marketplaceCatalogBusy ? "正在同步…" : "刷新目录"}
          </button>
        </div>
        <form className="catalog-import-form" onSubmit={model.importMarketplaceCatalog}>
          <label>店铺范围
            <input name="catalog_store_ref" defaultValue={model.marketplaceCatalogStoreRef} required />
            <small>内部隔离标识，不是 Ozon 密钥或 Client ID。</small>
          </label>
          <label>本次幂等键
            <input name="catalog_idempotency_key" placeholder="例如 ozon-catalog-2026-07-26-01" required />
            <small>同一键只能对应同一组不可变 Evidence。</small>
          </label>
          <label className="wide">已验证 Seller 原始响应
            <select name="catalog_evidence_ids" multiple size={Math.min(Math.max(ozonRawEvidence.length, 2), 5)} required>
              {ozonRawEvidence.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.id} · {new Date(item.effective_at).toLocaleString("zh-CN")}
                </option>
              ))}
            </select>
            <small>可多选最多 50 份。原始正文不会显示在页面，也不会被复制到日志。</small>
          </label>
          <button type="submit" disabled={!ozonRawEvidence.length || model.marketplaceCatalogBusy}>
            <Database size={14} /> 导入不可变目录快照
          </button>
        </form>
        {!model.marketplaceCatalogLoaded ? (
          <div className="growth-facts-empty">正在读取商品目录…</div>
        ) : model.marketplaceCatalogItems.length ? (
          <div className="growth-fact-list catalog-item-list">
            {model.marketplaceCatalogItems.map((item) => (
              <article key={item.offer_id}>
                <div>
                  <strong>{item.name}</strong>
                  <span>Offer {item.offer_id} · SKU {item.marketplace_sku ?? "未返回"}</span>
                </div>
                <dl>
                  <div><dt>售价</dt><dd>{String(item.prices.price ?? "—")} {item.currency_code ?? ""}</dd></div>
                  <div><dt>可售库存</dt><dd>{item.available_stock ?? "—"}</dd></div>
                  <div><dt>图片引用</dt><dd>{item.image_references.length}</dd></div>
                  <div><dt>视频引用</dt><dd>{item.video_references.length}</dd></div>
                </dl>
                <small>
                  媒体：未核权外部引用 · 观察于 {new Date(item.observed_at).toLocaleString("zh-CN")} · Evidence {item.source_evidence_id}
                </small>
                {item.canonical_product_id ? (
                  <div className="catalog-binding-state">
                    <CheckCircle2 size={14} />
                    已建立标准商品档案 · {item.canonical_product_id}
                  </div>
                ) : (
                  <button
                    type="button"
                    className="catalog-binding-action"
                    disabled={!canBindExistingListing || model.marketplaceCatalogBusy}
                    onClick={() => void model.bindExistingMarketplaceListing(item)}
                  >
                    <Link2 size={14} />
                    建立已有 Listing 运营档案
                  </button>
                )}
                {!item.canonical_product_id && (
                  <small>
                    仅建立店内现有商品身份和报价/利润工作台；不计入新选品，不改价、不发布、不采购、不投广告。
                  </small>
                )}
              </article>
            ))}
          </div>
        ) : (
          <div className="growth-facts-empty">
            <PackageSearch size={25} />
            <strong>{ozonRawEvidence.length ? "已有原始响应，等待导入目录" : "暂无可导入的 A 级 Seller 原始响应"}</strong>
            <p>目录导入不会自动创建 Product、修改 Ozon、采购或投放广告。</p>
          </div>
        )}
      </section>

      <section className="growth-fact-hub">
        <div className="section-heading">
          <div>
            <span>STORE FACT PORTFOLIO</span>
            <h3>最新店铺事实与全店方案</h3>
            <p>每个 SKU 只采用最新观测；历史版本、采集身份和 Evidence 保持可追溯。</p>
          </div>
          <button
            type="button"
            onClick={() => void model.planLatestMarketplaceGrowth()}
            disabled={!model.marketplaceGrowthObservations.length || model.marketplaceGrowthBusy}
          >
            <Layers3 size={14} />
            {model.marketplaceGrowthBusy ? "正在计算…" : "生成全店方案"}
          </button>
        </div>
        {!model.marketplaceGrowthFactsLoaded ? (
          <div className="growth-facts-empty">正在读取最新店铺事实…</div>
        ) : model.marketplaceGrowthObservations.length ? (
          <div className="growth-fact-list">
            {model.marketplaceGrowthObservations.map((item) => (
              <article key={item.marketplace_sku}>
                <div>
                  <strong>{item.marketplace_sku}</strong>
                  <span>{item.category} · {item.snapshot_source}</span>
                </div>
                <dl>
                  <div><dt>库存</dt><dd>{item.stock}</dd></div>
                  <div><dt>14 天订单</dt><dd>{item.orders_14d}</dd></div>
                  <div><dt>评价</dt><dd>{item.review_count}</dd></div>
                  <div><dt>内容分</dt><dd>{item.content_score}</dd></div>
                </dl>
                <small>观察于 {new Date(item.observed_at).toLocaleString("zh-CN")} · 快照 {item.snapshot_id}</small>
              </article>
            ))}
          </div>
        ) : (
          <div className="growth-facts-empty">
            <PackageSearch size={25} />
            <strong>还没有已确认的店铺事实</strong>
            <p>在下方录入一个真实 SKU；保存后即可逐步形成全店、铺货或精细化运营组合。</p>
          </div>
        )}
      </section>

      <section className="growth-layout">
        <form className="growth-form" onSubmit={model.planMarketplaceGrowth}>
          <div className="section-heading">
            <div><span>SKU DIAGNOSIS</span><h3>生成现有商品增长方案</h3></div>
            <span className="status-pill">保存 1 个 SKU · 规划全店</span>
          </div>

          {scenarioOptions.length ? (
            <div className="growth-fields">
              <label className="wide">全成本利润场景
                <select name="growth_scenario_id" defaultValue="" required>
                  <option value="">选择已经有证据的供应商与利润场景</option>
                  {scenarioOptions.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}
                </select>
                <small>只有实际成本权威复核完成的场景才能解锁价格与广告建议。</small>
              </label>
              <label>Ozon SKU / Offer ID<input name="growth_marketplace_sku" placeholder="例如 1990014542NP" required /></label>
              <label>同款类目<input name="growth_category" placeholder="例如 家用两步折叠梯" required /></label>
              <label className="wide">同款同行价格（RUB）
                <textarea name="growth_competitor_prices" placeholder="至少 3 个，用逗号或换行分隔，例如 1600, 1750, 1850, 2000" required />
                <small>必须是同规格、同材质、同用途商品；木梯、三步梯等不可混入两步钢梯价格。</small>
              </label>
              <label>当前库存<input name="growth_stock" type="number" min="0" defaultValue="0" required /></label>
              <label>近 14 天订单<input name="growth_orders_14d" type="number" min="0" defaultValue="0" required /></label>
              <label>真实评价数<input name="growth_review_count" type="number" min="0" defaultValue="0" required /></label>
              <label>评分<input name="growth_rating" type="number" min="0" max="5" step="0.1" defaultValue="5" required /></label>
              <label>内容完整度<input name="growth_content_score" type="number" min="0" max="100" step="0.1" defaultValue="90" required /></label>
              <label>真实转化率（0–1）<input name="growth_conversion_rate" type="number" min="0" max="1" step="0.0001" placeholder="没有就留空" /></label>
              <label>合规风险
                <select name="growth_compliance_risk" defaultValue="low">
                  <option value="low">低：已有明确合规依据</option>
                  <option value="medium">中：需要独立复核</option>
                  <option value="high">高：品牌/IP/资质红线</option>
                </select>
              </label>
              <label>目标 CM3 率<input name="growth_target_cm3_rate" type="number" min="0.01" max="0.49" step="0.01" defaultValue="0.15" required /></label>
              <label>观察时间<input name="growth_observed_at" type="datetime-local" defaultValue={localNow} required /></label>
              <label className="wide">Evidence IDs
                <textarea name="growth_evidence_ids" placeholder="店铺快照、同行价格和来源证据 ID，用逗号分隔" required />
              </label>
            </div>
          ) : (
            <div className="growth-empty">
              <CircleDollarSign size={28} />
              <strong>还没有可用的全成本利润场景</strong>
              <p>先到“1688 与供应链”完成三家报价和十五项成本，再返回生成增长方案。</p>
            </div>
          )}

          <div className="growth-submit">
            <div><ShieldAlert size={16} /><span>建议生成后仍不会触发 Ozon 写入或广告花费。</span></div>
            <button type="submit" disabled={!scenarioOptions.length || model.marketplaceGrowthBusy}>
              {model.marketplaceGrowthBusy ? "正在保存并复验…" : "保存事实并生成全店方案"}
            </button>
          </div>
        </form>

        <aside className="growth-method">
          <div className="section-heading"><div><span>DECISION ORDER</span><h3>系统判断顺序</h3></div></div>
          {[
            ["01", "合规与库存", "有红线或缺货时，停止一切增长动作。"],
            ["02", "实际落地成本", "1688 展示价不能替代物流、税费、退货和售后。"],
            ["03", "同行价格带", "使用 P25 / 中位数 / P75 判断售价位置。"],
            ["04", "内容与评价", "内容不足、评价过少时不靠广告掩盖问题。"],
            ["05", "自然转化", "没有真实转化率就无法计算可靠 CPC。"],
            ["06", "广告实验", "只有全部门通过才给出 ACOS/CPC 上限。"],
          ].map(([step, title, description]) => (
            <div className="method-step" key={step}>
              <span>{step}</span><div><strong>{title}</strong><p>{description}</p></div>
            </div>
          ))}
        </aside>
      </section>

      {plan ? (
        <section className="growth-result" aria-live="polite">
          <div className="section-heading">
            <div><span>RECOMMENDATION ONLY · {plan.plan_id}</span><h3>组合增长方案</h3><p>评估时间 {new Date(plan.evaluated_at).toLocaleString("zh-CN")}</p></div>
            <div className="result-summary">
              <span>价格实验 <b>{plan.summary.price_reset_count}</b></span>
              <span>广告可测 <b>{plan.summary.ad_test_eligible_count}</b></span>
              <span>阻断 <b>{plan.summary.blocked_count}</b></span>
            </div>
          </div>

          {plan.portfolio.map((item) => (
            <article className="growth-result-card" key={item.marketplace_sku}>
              <header>
                <div><span>优先级 {item.priority_score}</span><h4>{item.product_name}</h4><p>{item.marketplace_sku} · {item.scenario_id}</p></div>
                <strong className={item.ad_eligible ? "result-status eligible" : "result-status"}>
                  {statusLabels[item.commercial_status] ?? item.commercial_status}
                </strong>
              </header>

              <div className="growth-price-grid">
                <div><span>当前售价</span><strong>₽{item.current.price_rub}</strong><small>{item.current.price_position}</small></div>
                <div><span>同行中位数</span><strong>₽{item.market.median_rub}</strong><small>P25 ₽{item.market.p25_rub} · P75 ₽{item.market.p75_rub}</small></div>
                <div><span>目标 CM3 底价</span><strong>₽{item.economics.target_floor_price_rub}</strong><small>固定成本 ¥{item.economics.fixed_costs_cny}</small></div>
                <div className="recommended"><span>建议测试价</span><strong>{item.economics.recommended_test_price_rub ? `₽${item.economics.recommended_test_price_rub}` : "不可降到市场带"}</strong><small>需另行建立价格实验</small></div>
              </div>

              <div className="growth-analysis-grid">
                <div className="gate-checklist">
                  <h5><ShieldCheck size={16} /> 增长门禁</h5>
                  {Object.entries(item.gates).map(([key, ready]) => (
                    <div className={ready ? "ready" : "blocked"} key={key}>
                      {ready ? <CheckCircle2 size={14} /> : <ShieldAlert size={14} />}
                      <span>{gateLabels[key] ?? key}</span>
                    </div>
                  ))}
                </div>
                <div className="ad-ceiling">
                  <h5><Megaphone size={16} /> 广告承受力</h5>
                  <div><span>Break-even ACOS</span><strong>{(Number(item.economics.break_even_acos) * 100).toFixed(2)}%</strong></div>
                  <div><span>目标 ACOS 上限</span><strong>{(Number(item.economics.target_acos_ceiling) * 100).toFixed(2)}%</strong></div>
                  <div><span>单笔最大广告费</span><strong>¥{item.economics.max_ad_spend_per_order_cny}</strong></div>
                  <div><span>最大 CPC</span><strong>{item.economics.max_cpc_cny ? `¥${item.economics.max_cpc_cny}` : "缺真实转化率"}</strong></div>
                  <p>{item.ad_eligible ? "可建立有预算和止损线的广告实验。" : "当前广告保持关闭，先完成阻断项。"}</p>
                </div>
                <div className="content-plan">
                  <h5><ImageIcon size={16} /> 七类内容计划</h5>
                  <div>{item.content_plan.image_roles.map((role, index) => (
                    <span key={`${role.role}-${index}`}><b>{index + 1}</b>{roleLabels[role.role] ?? role.role}</span>
                  ))}</div>
                  <p>所有图片必须使用已批准商品事实和拥有权利的原始素材。</p>
                </div>
              </div>

              <footer className="growth-actions">
                <h5><BarChart3 size={16} /> 建议动作顺序</h5>
                {item.actions.map((action, index) => (
                  <div key={`${action.type}-${index}`}>
                    <span>{index + 1}</span>
                    <strong>{actionLabels[action.type] ?? action.type}</strong>
                    <p>{action.reason}</p>
                  </div>
                ))}
                <div className="growth-no-write"><TrendingDown size={15} /> 本方案没有执行权限；改价、内容发布和广告必须另行审批。</div>
              </footer>
            </article>
          ))}
        </section>
      ) : null}
    </div>
  );
}
