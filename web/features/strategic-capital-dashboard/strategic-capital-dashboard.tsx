"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import type { WebSession } from "../dashboard/contracts";
import {
  isStrategicCapitalDashboardProjection,
  type SectionId,
  type StrategicCapitalDashboardProjection,
} from "./contract";
import styles from "./strategic-capital-dashboard.module.css";

type Surface = "strategy-center" | "portfolio-cockpit";

const STRATEGY_SECTIONS: readonly SectionId[] = [
  "primary_source_coverage",
  "strategic_benchmark",
  "strategic_gaps",
  "opportunity_portfolio",
];

const PORTFOLIO_SECTIONS: readonly SectionId[] = [
  "experiment_portfolio",
  "capital_proposals",
  "verified_outcomes",
  "invalidation_review",
];

const SECTION_LABELS: Record<SectionId, string> = {
  primary_source_coverage: "来源覆盖",
  strategic_benchmark: "战略基准",
  strategic_gaps: "差距图",
  opportunity_portfolio: "机会组合",
  experiment_portfolio: "实验组合",
  capital_proposals: "资本提案",
  verified_outcomes: "已验证结果",
  invalidation_review: "失效与复审",
};

export function StrategicCapitalDashboard({ surface }: { surface: Surface }) {
  const [dashboard, setDashboard] = useState<StrategicCapitalDashboardProjection | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const sessionResponse = await fetchJson<WebSession | { detail?: string }>(
        "/auth/session",
        { cache: "no-store", signal: controller.signal },
      );
      if (sessionResponse.status === 401) {
        window.location.assign("/login");
        return;
      }
      if (sessionResponse.status === 428) {
        window.location.assign("/mfa");
        return;
      }
      const sessionBody = await sessionResponse.json();
      if (!sessionResponse.ok || !("authenticated" in sessionBody)) {
        setState("error");
        return;
      }
      const session = sessionBody as WebSession;
      const storeRef = session.default_store_ref;
      if (
        !session.authenticated ||
        !storeRef ||
        !Array.isArray(session.store_refs) ||
        !session.store_refs.includes(storeRef)
      ) {
        setState("error");
        return;
      }
      const response = await fetchJson<unknown>(
        `/backend/v1/strategic-capital-dashboard?store_ref=${encodeURIComponent(storeRef)}`,
        { cache: "no-store", signal: controller.signal },
      );
      if (response.status === 401) {
        window.location.assign("/login");
        return;
      }
      if (response.status === 428) {
        window.location.assign("/mfa");
        return;
      }
      const payload = await response.json();
      if (!response.ok || !isStrategicCapitalDashboardProjection(payload, storeRef)) {
        setState("error");
        return;
      }
      setDashboard(payload);
      setState("ready");
    }
    void load();
    return () => controller.abort();
  }, []);

  const admittedSections =
    surface === "strategy-center" ? STRATEGY_SECTIONS : PORTFOLIO_SECTIONS;
  const title = surface === "strategy-center" ? "战略中心" : "资本组合驾驶舱";
  const subtitle =
    surface === "strategy-center"
      ? "来源覆盖 → 基准 → 差距 → 机会；仅渲染服务端当前投影。"
      : "资本约束 → 五方案 → 实验 → Outcome → 失效复审；不生成预算权限。";

  return (
    <main className={styles.shell}>
      <header className={styles.hero}>
        <div>
          <Link href="/">← KJDS Command Center</Link>
          <p>SERVER-OWNED · EXACT CURRENT AUTHORITY · READ ONLY</p>
          <h1>{title}</h1>
          <span>{subtitle}</span>
        </div>
        <strong data-state={state}>{state}</strong>
      </header>

      {state === "loading" && (
        <section className={styles.notice}>正在读取当前作用域驾驶舱…</section>
      )}
      {state === "error" && (
        <section className={styles.notice} data-tone="error">
          当前投影读取失败。页面未填充默认值，也未把缺失数据转换为 0。
        </section>
      )}

      {dashboard && state === "ready" && (
        <>
          <section className={styles.auditStrip}>
            <div><span>状态</span><strong>{dashboard.overall_state}</strong></div>
            <div><span>数据时点</span><strong>{dashboard.data_as_of}</strong></div>
            <div><span>授权复核</span><strong>{dashboard.authority_checked_at}</strong></div>
            <div><span>Store</span><strong>{dashboard.store_ref}</strong></div>
          </section>

          <section className={styles.grid}>
            {dashboard.sections.map((section) =>
              admittedSections.includes(section.section_id) ? (
                <article className={styles.card} key={section.section_id}>
                  <header>
                    <div>
                      <small>#{section.display_order} · {section.section_id}</small>
                      <h2>{SECTION_LABELS[section.section_id]}</h2>
                    </div>
                    <strong data-status={section.status}>{section.status}</strong>
                  </header>

                  {section.display_items.length === 0 ? (
                    <div className={styles.empty}>
                      <p>当前没有可展示的生产投影。</p>
                      <ul>
                        {section.reason_codes.map((reason) => <li key={reason}>{reason}</li>)}
                      </ul>
                    </div>
                  ) : (
                    <div className={styles.items}>
                      {section.display_items.map((item) => (
                        <div key={item.item_ref}>
                          <strong>{item.label}</strong>
                          <p>{item.display_text}</p>
                        </div>
                      ))}
                    </div>
                  )}

                  <footer>
                    <code>{section.source_contract_id}@{section.source_contract_version}</code>
                    <span>review {section.review_due_at || "not_connected"}</span>
                    {section.citations.map((citation) => (
                      <code key={citation.token}>citation {citation.summary_sha256}</code>
                    ))}
                    {section.invalidation_conditions.map((condition) => (
                      <span key={condition}>invalidate: {condition}</span>
                    ))}
                  </footer>
                </article>
              ) : null,
            )}
          </section>

          <footer className={styles.proof}>
            <code>dashboard {dashboard.dashboard_ref}</code>
            <code>observation {dashboard.observation_sha256}</code>
            <p>
              global_top1=false · production_admission=false · budget_authority=false ·
              POST=false · external_write=0
            </p>
          </footer>
        </>
      )}
    </main>
  );
}
