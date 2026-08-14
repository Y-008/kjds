"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowUpRight,
  BadgeDollarSign,
  RefreshCw,
  ShieldCheck,
  Store,
} from "lucide-react";
import { fetchJson } from "../../lib/fetch-json";

type SellerStrategyPack = {
  label: string;
  commercial_plan: string;
  price_cny_month?: string;
  price_cny_year_from?: string;
  shops_max: number | null;
  active_sku_max: number | null;
  users_max: number | null;
  scan_batch_max: number;
  approval_layers: number;
  permit_ttl_minutes: number;
  single_sku_budget_cny: string;
  advertising_daily_cap_cny: string;
  facts_and_profit_kernel?: "shared";
  truth_degraded?: false;
};

type SellerStrategyPacks = {
  strategy_packs: Record<string, SellerStrategyPack>;
  portfolio_policy: Record<string, string>;
  facts_and_profit_kernel: string;
  truth_degradation_by_plan: false;
  authorized_scope: {
    tenant_ref: string;
    store_refs: string[];
  };
  strategy_pack_registry: {
    commercial_status: string;
    version: string;
  };
};

const tierOrder = [
  "novice",
  "solo",
  "small_team",
  "mid_market",
  "enterprise",
] as const;

const tierLabels: Record<(typeof tierOrder)[number], string> = {
  novice: "新手",
  solo: "个人 / 小微",
  small_team: "中小团队",
  mid_market: "中型企业",
  enterprise: "大卖 / 企业",
};

function formatCap(value: number | null, suffix: string) {
  return value === null ? "no_data" : `${value}${suffix}`;
}

function formatPrice(pack: SellerStrategyPack) {
  if (pack.price_cny_month) return `¥${pack.price_cny_month}/月`;
  if (pack.price_cny_year_from) return `¥${pack.price_cny_year_from}/年起`;
  return "internal preview";
}

export function SellerTierPanel() {
  const [payload, setPayload] = useState<SellerStrategyPacks | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("正在读取卖家分层包...");

  const load = useCallback(async () => {
    setLoading(true);
    setNotice("正在读取卖家分层包...");
    try {
      const response = await fetchJson<SellerStrategyPacks | { detail?: string }>(
        "/backend/v1/seller-os/strategy-packs",
        { cache: "no-store" },
      );
      const body = await response.json();
      if (!response.ok || !body || typeof body !== "object" || !("strategy_packs" in body)) {
        setPayload(null);
        setNotice(`卖家分层包读取失败（HTTP ${response.status || "offline"}）`);
        return;
      }
      const packs = body as SellerStrategyPacks;
      setPayload(packs);
      setNotice(`已读取 ${Object.keys(packs.strategy_packs).length} 个卖家策略包。`);
    } catch {
      setPayload(null);
      setNotice("卖家分层包读取失败，请重试。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const packEntries = tierOrder.flatMap((tierKey) => {
    const pack = payload?.strategy_packs[tierKey];
    return pack ? [{ tierKey, pack }] : [];
  });

  return (
    <section className="panel seller-tier-panel" aria-label="卖家分层商业包">
      <div className="panel-title seller-tier-panel-title">
        <div>
          <p className="eyebrow">COMMERCIAL PACKS</p>
          <h3>卖家分层商业包</h3>
        </div>
        <div className="seller-tier-panel-actions">
          <Link className="seller-tier-link" href="/seller-os">
            <Store size={14} />
            打开 Seller OS
          </Link>
          <Link className="seller-tier-link secondary" href="/strategy-center">
            <BadgeDollarSign size={14} />
            打开策略中心
          </Link>
          <button type="button" className="seller-tier-refresh" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={14} />
            {loading ? "读取中..." : "独立刷新"}
          </button>
        </div>
      </div>

      <div className="seller-tier-intro">
        <div>
          <strong>同一事实核，不同商业包络</strong>
          <p>
            这部分不是新的 truth kernel，而是把同一套利润、证据、审批和审计能力，
            按不同卖家规模包装成可售交付。
          </p>
        </div>
        <div className="seller-tier-summary">
          <article>
            <span>Kernel</span>
            <strong>{payload?.facts_and_profit_kernel ?? "shared"}</strong>
          </article>
          <article>
            <span>商业状态</span>
            <strong>{payload?.strategy_pack_registry.commercial_status ?? "no_data"}</strong>
          </article>
          <article>
            <span>授权店铺</span>
            <strong>{payload?.authorized_scope.store_refs.length ?? 0}</strong>
          </article>
          <article>
            <span>Truth Degradation</span>
            <strong>{payload?.truth_degradation_by_plan ? "true" : "false"}</strong>
          </article>
        </div>
      </div>

      <p className="seller-tier-notice">{notice}</p>

      {packEntries.length ? (
        <div className="seller-tier-grid">
          {packEntries.map(({ tierKey, pack }) => (
            <article className="seller-tier-card" key={tierKey} data-tier={tierKey}>
              <div className="seller-tier-card-head">
                <span>{tierLabels[tierKey]}</span>
                <strong>{formatPrice(pack)}</strong>
              </div>
              <h4>{pack.commercial_plan}</h4>
              <p>{pack.label}</p>
              <dl>
                <div><dt>店铺</dt><dd>{formatCap(pack.shops_max, "店")}</dd></div>
                <div><dt>SKU</dt><dd>{formatCap(pack.active_sku_max, "个")}</dd></div>
                <div><dt>用户</dt><dd>{formatCap(pack.users_max, "人")}</dd></div>
                <div><dt>扫描批次</dt><dd>{pack.scan_batch_max}</dd></div>
                <div><dt>审批层级</dt><dd>{pack.approval_layers} 层</dd></div>
                <div><dt>Permit TTL</dt><dd>{pack.permit_ttl_minutes}m</dd></div>
              </dl>
              <footer>
                <span>单 SKU 预算 ¥{pack.single_sku_budget_cny}</span>
                <span>广告日限 ¥{pack.advertising_daily_cap_cny}</span>
              </footer>
            </article>
          ))}
        </div>
      ) : (
        <div className="seller-tier-empty">
          <ShieldCheck size={20} />
          <div>
            <strong>卖家分层包暂不可用</strong>
            <p>
              当前只读包未返回可渲染数据时，页面保持 no_data，不会编造套餐、价格或容量。
            </p>
          </div>
          <ArrowUpRight size={16} />
        </div>
      )}
    </section>
  );
}
