"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Boxes,
  CircleDollarSign,
  ExternalLink,
  RefreshCw,
  SearchCheck,
  ShieldAlert,
  ShieldCheck,
  Target,
} from "lucide-react";
import { fetchJson } from "../../lib/fetch-json";

type Observation = {
  id: string;
  external_item_id: string;
  supplier_ref: string;
  title: string;
  variant_key: string;
  currency: string;
  displayed_price: string;
  price_kind: string;
  price_basis: "observed";
  min_order_quantity: number | null;
  availability: string;
  specifications: Record<string, string>;
  target_product_id: string | null;
  source_url: string;
  observed_at: string;
  evidence_id: string;
  formal_fact_promoted: false;
  supplier_offer_created: false;
  actual_cost_created: false;
};

type ObservationEnvelope = {
  contract_id: "kjds-scoped-marketplace-observation-v1";
  status: "ready" | "partial" | "no_data" | "blocked";
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    scope_grant_authority_sha256: string | null;
  };
  items: Observation[];
  counts: {
    queried_in_exact_store_scope: number;
    included: number;
    excluded: number;
  };
  source_gaps: string[];
  control_envelope: {
    observation_input_ready: boolean;
    candidate_scoring_allowed: boolean;
    pilot_approval_allowed: false;
    external_write_allowed: false;
  };
};

type SpecificationMatch = {
  status: "exact" | "partial" | "mismatch";
  matched: string[];
  missing: string[];
  mismatched: Array<{ key: string; required: string; observed: string }>;
};

type PilotCandidate = Observation & {
  specification_match: SpecificationMatch;
  economics: {
    currency: string;
    listing_price: string;
    observed_display_price: string;
    observed_spread: string | null;
    screening_contribution_base: string | null;
    screening_contribution_downside: string | null;
    estimated_downside_loss: string | null;
    scenario_cm3: string | null;
    actual_profit: null;
    authority: "research_screening_only";
  };
  state: "ready" | "partial" | "blocked";
  pilot_ready: boolean;
  blockers: string[];
  next_action: string;
  automatic_supplier_contact: false;
  automatic_listing: false;
  external_write_allowed: false;
};

type PilotView = {
  run_id: string;
  contract_version: string;
  product: { id: string; sku: string; name: string };
  target_listing: {
    offer_id: string;
    marketplace_sku: string | null;
    price: string;
    currency: string;
    stock: number | null;
  };
  policy: {
    id: string;
    assumption_breakdown: Record<string, Record<string, string>>;
    authority: "research_screening_only";
  };
  limits: {
    candidate_target: number;
    pilot_limit: number;
    max_loss_cny: string;
    cm3_floor_cny: string;
  };
  counts: {
    observed: number;
    screened: number;
    positive_lower_bound: number;
    draft_ready: number;
    pilot_ready: number;
  };
  ranked_candidates: PilotCandidate[];
  blockers: string[];
  next_action: string;
  operating_task: { id: string; status: string } | null;
  actual_profit_available: false;
  automatic_supplier_contact: false;
  automatic_listing: false;
  external_write_allowed: false;
};

const targetSpecification = {
  rated_load_kg: "500",
  voltage_v: "220",
  lifting_height_m: "7.6",
  power_w: "1500",
  wire_rope_mm: "6",
  control_mode: "wireless+wired+manual",
  plug: "russia",
  duty_cycle: "continuous",
};

const blockerLabels: Record<string, string> = {
  cross_currency_fx_missing: "缺少同日 FX，禁止跨币种比较",
  required_specifications_missing: "关键规格未证实",
  required_specifications_mismatch: "规格与目标不一致",
  downside_screening_contribution_not_positive: "下行情景贡献不为正",
  pilot_loss_exceeds_budget: "下行损失超过单批预算",
  full_cost_profit_scenario_missing: "缺少十五项全成本利润场景",
};

function money(value: string | null, currency = "CNY") {
  return value === null ? "—" : `${value} ${currency}`;
}

export function PortfolioPilotPanel() {
  const searchParams = useSearchParams();
  const storeRef = searchParams?.get("store_ref")?.trim() || "ozon-primary";
  const [observations, setObservations] = useState<Observation[]>([]);
  const [candidateScoringAllowed, setCandidateScoringAllowed] = useState(false);
  const [pilot, setPilot] = useState<PilotView | null>(null);
  const [busy, setBusy] = useState(true);
  const [notice, setNotice] = useState("正在读取受控市场观察…");

  const productId = useMemo(
    () => observations.find((item) => item.target_product_id)?.target_product_id ?? null,
    [observations],
  );

  const loadObservations = useCallback(async () => {
    setBusy(true);
    const query = new URLSearchParams({
      marketplace: "1688",
      limit: "100",
      store_ref: storeRef,
    });
    const response = await fetchJson<ObservationEnvelope>(
      `/backend/v1/marketplace-observations?${query.toString()}`,
    );
    const payload = await response.json();
    if (
      !response.ok
      || !payload
      || typeof payload !== "object"
      || !("items" in payload)
      || !Array.isArray(payload.items)
    ) {
      setNotice(`观察数据读取失败（HTTP ${response.status || "offline"}）`);
      setCandidateScoringAllowed(false);
      setBusy(false);
      return;
    }
    setObservations(payload.items);
    setCandidateScoringAllowed(payload.control_envelope.candidate_scoring_allowed);
    setNotice(
      payload.items.length
        ? `店铺 ${payload.scope.store_ref} 已读取 ${payload.items.length} 条作用域 Evidence 观察；下游 Catalog/成本仍待作用域化，候选排序保持锁定。`
        : payload.status === "blocked"
          ? `观察数据被作用域门禁阻断：${payload.source_gaps.join("、")}`
          : `店铺 ${payload.scope.store_ref} 暂无通过作用域 Evidence 的 1688 观察，不能生成候选排序。`,
    );
    setBusy(false);
  }, [storeRef]);

  useEffect(() => {
    void loadObservations();
  }, [loadObservations]);

  const preparePilot = async () => {
    if (!productId) {
      setNotice("观察项尚未绑定标准 Product，无法运行 Pilot。");
      return;
    }
    setBusy(true);
    setNotice("服务端正在执行规格、下行情景、全成本和损失预算门禁…");
    const response = await fetchJson<PilotView>("/backend/v1/portfolio-pilot/prepare", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        store_ref: storeRef,
        product_id: productId,
        target_specification: targetSpecification,
        policy_id: "ozon-cny-research-screening-v1",
        candidate_target: 100,
        pilot_limit: 10,
        max_loss_cny: "500.00",
        cm3_floor_cny: "0.00",
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload || typeof payload !== "object" || !("run_id" in payload)) {
      setNotice(`Pilot 生成失败（HTTP ${response.status || "offline"}）`);
      setBusy(false);
      return;
    }
    setPilot(payload);
    setNotice(
      payload.counts.pilot_ready
        ? `服务端确认 ${payload.counts.pilot_ready} 个候选穿过旧版研究门禁；仍需冻结计划、独立批准与一次性 Permit。`
        : "当前没有候选穿过全部门禁；已投影为内部运营任务。",
    );
    setBusy(false);
  };

  return (
    <div className="workspace-page pilot-page">
      <section className="pilot-hero">
        <div>
          <span><Target size={15} /> OBSERVE · SCREEN · PILOT</span>
          <h2>先把真实观察绑定成可追溯事实，再由全成本筛出审批候选。</h2>
          <p>
            公开价格可用于找机会，但不是供应商报价或实际采购成本。服务端统一做规格差距、
            基准/下行贡献、损失预算和十五项全成本门禁；浏览器不重算利润。
          </p>
        </div>
        <div className="pilot-boundary">
          <ShieldCheck size={22} />
          <div>
            <strong>本轮经营边界</strong>
            <p>候选目标 100 · 审批分配 ≤ 10 · 初始 Pilot 每 SKU ≤ 3 件 · 单批最大损失 500 CNY</p>
          </div>
          <small>供应商联系：关闭 · 自动上架：关闭 · Ozon 写入：关闭</small>
        </div>
      </section>

      <section className="pilot-toolbar">
        <div>
          <span>REAL MARKET OBSERVATIONS</span>
          <h3>Evidence 绑定的 1688 候选观察</h3>
          <p>{notice}</p>
        </div>
        <div>
          <button type="button" className="secondary" onClick={() => void loadObservations()} disabled={busy}>
            <RefreshCw size={14} /> 刷新观察
          </button>
          <button
            type="button"
            onClick={() => void preparePilot()}
            disabled={busy || !productId || !candidateScoringAllowed}
          >
            <SearchCheck size={14} /> {busy ? "正在处理…" : "生成服务端排序"}
          </button>
        </div>
      </section>

      <section className="pilot-target-specs" aria-label="冻结目标规格">
        <div><span>额定载荷</span><strong>500 kg</strong></div>
        <div><span>电压 / 功率</span><strong>220 V / 1500 W</strong></div>
        <div><span>钢丝绳 / 高度</span><strong>6 mm / 7.6 m</strong></div>
        <div><span>控制</span><strong>无线 + 有线 + 手动</strong></div>
        <div><span>插头 / 工况</span><strong>俄罗斯 / 连续工作</strong></div>
      </section>

      {pilot ? (
        <>
          <section className="pilot-kpis">
            <article><Boxes size={18} /><span>观察候选</span><strong>{pilot.counts.observed}</strong></article>
            <article><SearchCheck size={18} /><span>下行贡献为正</span><strong>{pilot.counts.positive_lower_bound}</strong></article>
            <article><CircleDollarSign size={18} /><span>全成本草稿就绪</span><strong>{pilot.counts.draft_ready}</strong></article>
            <article className={pilot.counts.pilot_ready ? "ready" : "blocked"}>
              {pilot.counts.pilot_ready ? <ShieldCheck size={18} /> : <ShieldAlert size={18} />}
              <span>旧版研究门禁通过</span><strong>{pilot.counts.pilot_ready}</strong>
            </article>
          </section>

          <section className="pilot-list">
            {pilot.ranked_candidates.map((item, index) => (
              <article className={`pilot-candidate ${item.state}`} key={item.id}>
                <header>
                  <div className="pilot-rank">{String(index + 1).padStart(2, "0")}</div>
                  <div>
                    <span>{item.supplier_ref}</span>
                    <h3>{item.variant_key}</h3>
                    <p>{item.title}</p>
                  </div>
                  <strong className={`pilot-state ${item.state}`}>
                    {item.state === "ready" ? "READY" : item.state === "partial" ? "PARTIAL" : "BLOCKED"}
                  </strong>
                </header>

                <div className="pilot-economics">
                  <div><span>Ozon 页面售价</span><strong>{money(item.economics.listing_price, item.economics.currency)}</strong></div>
                  <div><span>1688 展示价</span><strong>{money(item.economics.observed_display_price, item.currency)}</strong></div>
                  <div><span>观察价差</span><strong>{money(item.economics.observed_spread, item.economics.currency)}</strong></div>
                  <div><span>基准筛选贡献</span><strong>{money(item.economics.screening_contribution_base, item.economics.currency)}</strong></div>
                  <div><span>下行筛选贡献</span><strong>{money(item.economics.screening_contribution_downside, item.economics.currency)}</strong></div>
                  <div><span>实际利润 / CM3</span><strong>{money(item.economics.actual_profit)} / {money(item.economics.scenario_cm3)}</strong></div>
                </div>

                <div className="pilot-gaps">
                  <div>
                    <span>规格状态 · {item.specification_match.status}</span>
                    {item.specification_match.matched.length ? (
                      <p>已匹配：{item.specification_match.matched.join("、")}</p>
                    ) : null}
                    {item.specification_match.missing.length ? (
                      <p>未证实：{item.specification_match.missing.join("、")}</p>
                    ) : null}
                    {item.specification_match.mismatched.map((gap) => (
                      <p key={gap.key}>不一致：{gap.key}（目标 {gap.required} / 页面 {gap.observed}）</p>
                    ))}
                  </div>
                  <div>
                    <span>阻断与下一动作</span>
                    {item.blockers.map((blocker) => (
                      <p key={blocker}>{blockerLabels[blocker] ?? blocker}</p>
                    ))}
                    <strong>{item.next_action}</strong>
                  </div>
                </div>

                <footer>
                  <span>Evidence {item.evidence_id}</span>
                  <span>公开展示价 · observed · 非 Offer · 非实际成本</span>
                  <a href={item.source_url} target="_blank" rel="noreferrer">
                    查看来源 <ExternalLink size={12} />
                  </a>
                </footer>
              </article>
            ))}
          </section>

          <section className="pilot-run-note">
            <ShieldAlert size={18} />
            <div>
              <strong>{pilot.next_action}</strong>
              <p>
                Run {pilot.run_id} · 实际利润可用：否 · 自动联系供应商：否 ·
                自动上架：否 · 外部写入：否
                {pilot.operating_task ? ` · 内部任务 ${pilot.operating_task.id}` : ""}
              </p>
            </div>
          </section>
        </>
      ) : (
        <section className="pilot-observation-grid">
          {observations.map((item) => (
            <article key={item.id}>
              <span>{item.supplier_ref}</span>
              <h3>{item.variant_key}</h3>
              <strong>{item.displayed_price} {item.currency}</strong>
              <p>{item.title}</p>
              <small>Evidence {item.evidence_id} · {item.price_kind}</small>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
