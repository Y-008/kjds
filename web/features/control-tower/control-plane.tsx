"use client";

import Link from "next/link";
import { useMemo } from "react";
import type {
  OperatingAnalyticsSnapshot,
  OperatingWorkbenchBriefing,
} from "../dashboard/contracts";
import {
  AppShell,
  ChartFrame,
  DataTable,
  MetricCard,
  ScopeBar,
  StatusBadge,
  type DataStatus,
} from "../ui2/ui2";
import { useBiProjection } from "../bi/use-bi-projection";
import styles from "./control-plane.module.css";

export type ControlPlaneSurface =
  | "capabilities"
  | "journey"
  | "sources"
  | "enterprise"
  | "product-value"
  | "scenarios"
  | "agent-control"
  | "reliability";

type CapabilityStatus =
  | "documented"
  | "designed"
  | "implemented"
  | "tested"
  | "replayed"
  | "pilot_ready"
  | "production_ready"
  | "blocked"
  | "deprecated";

type CapabilityAssertion = {
  id: string;
  domain: string;
  title: string;
  jtbd: string;
  status: CapabilityStatus;
  owner: string;
  gate: string;
  proof: string;
  productionReady: boolean;
};

const capabilityAssertions: CapabilityAssertion[] = [
  {
    id: "scope-first-bi",
    domain: "可信数据",
    title: "Session-first BI Scope",
    jtbd: "只读取当前身份授权的店铺和截止时点",
    status: "tested",
    owner: "web_platform",
    gate: "scope-contract",
    proof: "useBiProjection + bi-projection tests",
    productionReady: false,
  },
  {
    id: "truth-state-ui",
    domain: "可信数据",
    title: "Truth state expression",
    jtbd: "区分 no_data、partial、blocked、stale 和 conflicted",
    status: "tested",
    owner: "operating_product",
    gate: "ui2-contract",
    proof: "UI2 shared components + truth adapter",
    productionReady: false,
  },
  {
    id: "evidence-drilldown",
    domain: "Evidence",
    title: "Evidence metadata / verify / lineage",
    jtbd: "从当前 scoped 投影回看到证据边界",
    status: "tested",
    owner: "evidence_governance",
    gate: "evidence-readback",
    proof: "EvidenceDrawer contract and browser verification",
    productionReady: false,
  },
  {
    id: "journey-read-model",
    domain: "经营旅程",
    title: "Observation-to-cash read model",
    jtbd: "把现有服务端阶段和漏斗串成一条只读经营旅程",
    status: "implemented",
    owner: "operating_product",
    gate: "journey-replay",
    proof: "OperatingAnalyticsSnapshot stages / pipeline",
    productionReady: false,
  },
  {
    id: "decision-outcome-loop",
    domain: "决策闭环",
    title: "Decision / Action / Outcome",
    jtbd: "区分建议、审批、执行回执和业务结果",
    status: "designed",
    owner: "control_plane",
    gate: "action-safety-envelope",
    proof: "Contract planned; no external write granted",
    productionReady: false,
  },
  {
    id: "scenario-lab",
    domain: "经营分析",
    title: "Scenario Lab",
    jtbd: "在不污染实际账的前提下比较经营假设",
    status: "designed",
    owner: "profit_command",
    gate: "scenario-version",
    proof: "Read-only UI shell; projection not connected",
    productionReady: false,
  },
  {
    id: "enterprise-control",
    domain: "企业治理",
    title: "Authority / Commercial / Operational scopes",
    jtbd: "防止主体、店铺、套餐和 Agent 权限混用",
    status: "designed",
    owner: "enterprise_control",
    gate: "exact-scope-authority",
    proof: "Current session scope; commercial projection pending",
    productionReady: false,
  },
  {
    id: "product-value-telemetry",
    domain: "产品价值",
    title: "Evidence-backed decision telemetry",
    jtbd: "衡量 KJDS 是否减少决策时间和现金损失",
    status: "documented",
    owner: "product_analytics",
    gate: "outcome-telemetry",
    proof: "Metric contract pending server event projection",
    productionReady: false,
  },
];

const journeyPolicy = [
  "approved 不等于 permit_ready；审批、Permit 和执行权威保持分离。",
  "published 不等于 readback_verified；没有回读就不能进入扩量建议。",
  "settled 不等于 cash_received；结算和到账分别进入不同实际账。",
  "scenario_* 只表示模拟，不得写入 Actual accrual、Settled contribution 或 Actual Cash CM3。",
];

type ActionSafetyEnvelope = readonly string[];

const actionSafetyEnvelope: ActionSafetyEnvelope = [
  "默认 Observation-only；建议动作与真实动作使用不同对象和权限。",
  "Agent 不能创建 Fact、FinanceEntry、Approval、Permit 或 external_write。",
  "Reviewer 必须与提案作者分离；Readback 失败后不能继续扩量。",
];

const scenarioInputs = [
  ["scenario_price_delta", "价格变化", "待接入服务端情景合同"],
  ["scenario_ad_budget_delta", "广告预算变化", "待接入服务端情景合同"],
  ["scenario_inventory_delay_days", "库存晚到", "待接入服务端情景合同"],
  ["scenario_return_rate_delta", "退货率变化", "待接入服务端情景合同"],
  ["scenario_fx_rate", "汇率变化", "待接入服务端情景合同"],
  ["scenario_settlement_delay_days", "到账延迟", "待接入服务端情景合同"],
] as const;

const productValueMetrics = [
  ["evidence_backed_decisions_completed", "证据支持的已完成决策", "需要 Decision/Outcome 事件投影"],
  ["median_anomaly_to_root_cause_ms", "异常到根因中位时间", "需要调查生命周期事件"],
  ["unknown_closure_rate", "未知项关闭率", "需要 data-gap closure 事件"],
  ["decision_reversal_rate", "决策被推翻率", "需要复盘结果投影"],
  ["evidence_reuse_rate", "Evidence 重复利用率", "需要 lineage 消费事件"],
  ["recovery_time_ms", "失败恢复时间", "需要运行与恢复事件"],
] as const;

const reliabilityGaps = [
  ["api_health", "API 健康", "当前 UI 只知道投影响应，不等同于服务健康"],
  ["queue_lag", "队列延迟", "需要 acquisition / operations 运行投影"],
  ["backup_restore", "备份与恢复", "需要 Backup Manifest / Restore Receipt"],
  ["provider_failover", "Provider failover", "需要 provider health projection"],
  ["settlement_reconciliation", "结算对账缺口", "需要财务对账投影"],
] as const;

function projectionDataStatus(status: string): DataStatus {
  if (status === "ready" || status === "partial" || status === "blocked" || status === "no_data") return status;
  if (status === "forbidden" || status === "conflicted" || status === "error" || status === "loading") return status;
  return "no_data";
}

function capabilityDataStatus(status: CapabilityStatus): DataStatus {
  if (status === "blocked") return "blocked";
  if (status === "production_ready" || status === "replayed" || status === "tested") return "ready";
  if (status === "deprecated") return "stale";
  return "partial";
}

function formatCount(value: number | null | undefined, status: DataStatus) {
  return status === "ready" || status === "partial" ? String(value ?? 0) : "no_data";
}

function surfaceCopy(surface: ControlPlaneSurface) {
  const copy: Record<ControlPlaneSurface, { eyebrow: string; title: string; description: string }> = {
    capabilities: {
      eyebrow: "Capability control tower",
      title: "能力成熟度",
      description: "把需求、合同、实现、验证、回放和生产 Gate 分开呈现；页面数量不等于能力完成。",
    },
    journey: {
      eyebrow: "Operating journey",
      title: "经营旅程控制塔",
      description: "基于当前 scoped OperatingAnalyticsSnapshot，把真实阶段、来源和下一动作串成可回放时间线。",
    },
    sources: {
      eyebrow: "Evidence acquisition",
      title: "证据与来源",
      description: "展示当前作用域的来源缺口、排除来源和采集合同边界；没有调度投影时保持 no_data。",
    },
    enterprise: {
      eyebrow: "Enterprise control",
      title: "企业与作用域",
      description: "把 Authority Scope、Commercial Scope 和 Operational Scope 分开；未授权主体不做跨域汇总。",
    },
    "product-value": {
      eyebrow: "Product value",
      title: "产品价值与 ROI",
      description: "只显示已经接入的真实工作项和投影；尚未存在的 Decision/Outcome 遥测保持 no_data。",
    },
    scenarios: {
      eyebrow: "Scenario lab",
      title: "情景实验室",
      description: "先建立 scenario_* 输入和风险预算的产品语言，不把模拟结果写入实际账。",
    },
    "agent-control": {
      eyebrow: "Agent control",
      title: "Agent 与人类协作",
      description: "显示当前只读投影中的 Agent、guardrail 和人审边界；不授予新的工具或平台写权限。",
    },
    reliability: {
      eyebrow: "Reliability plane",
      title: "可靠性与降级",
      description: "将投影状态、数据可信度和运行可用性分开，避免系统在线被误读为业务事实可用。",
    },
  };
  return copy[surface];
}

function ScopeFrame({
  surface,
  scope,
  snapshot,
  briefing,
  analyticsStatus,
  workbenchStatus,
  error,
  status,
  asOf,
  sourceAsOf,
  snapshotHash,
}: {
  surface: ControlPlaneSurface;
  scope: ReturnType<typeof useBiProjection>["scope"];
  snapshot: OperatingAnalyticsSnapshot | null;
  briefing: OperatingWorkbenchBriefing | null;
  analyticsStatus: string;
  workbenchStatus: string;
  error: string;
  status: DataStatus;
  asOf: string | null;
  sourceAsOf: string | null;
  snapshotHash: string | null;
}) {
  const copy = surfaceCopy(surface);
  const query = scope.storeRef
    ? `?store_ref=${encodeURIComponent(scope.storeRef)}${scope.requestAsOf ? `&as_of=${encodeURIComponent(scope.requestAsOf)}` : ""}`
    : "";
  return (
    <AppShell
      eyebrow={copy.eyebrow}
      title={copy.title}
      description={copy.description}
      status={status}
      asOf={asOf}
      snapshotHash={snapshotHash}
      scope={(
        <ScopeBar
          stores={scope.storeRefs}
          selectedStore={scope.storeRef}
          onStoreChange={scope.setStoreRef}
          disabled={scope.status === "loading"}
          tenant={scope.tenantRef}
          asOf={scope.requestAsOf}
          sourceAsOf={sourceAsOf}
          scopeAuthorityHash={scope.authoritySha256}
          currency="服务端原始口径"
          timezone="ISO-8601 / 含时区"
        />
      )}
      actions={(
        <>
          <Link href={`/bi/overview${query}`}>经营总览</Link>
          <Link href={`/bi/briefing${query}`}>经营简报</Link>
          <Link href={`/bi/sources${query}`}>证据与来源</Link>
        </>
      )}
    >
      <ControlPlaneSurfaceBody
        surface={surface}
        scope={scope}
        snapshot={snapshot}
        briefing={briefing}
        analyticsStatus={analyticsStatus}
        workbenchStatus={workbenchStatus}
        status={status}
        error={error}
        asOf={asOf}
        snapshotHash={snapshotHash}
      />
    </AppShell>
  );
}

function ControlPlaneSurfaceBody({
  surface,
  scope,
  snapshot,
  briefing,
  analyticsStatus,
  workbenchStatus,
  status,
  error,
  asOf,
  snapshotHash,
}: {
  surface: ControlPlaneSurface;
  scope: ReturnType<typeof useBiProjection>["scope"];
  snapshot: OperatingAnalyticsSnapshot | null;
  briefing: OperatingWorkbenchBriefing | null;
  analyticsStatus: string;
  workbenchStatus: string;
  status: DataStatus;
  error: string;
  asOf: string | null;
  snapshotHash: string | null;
}) {
  return (
    <>
      {error ? <div className={styles.callout} role="alert"><strong>{status.toUpperCase()}</strong> · {error}</div> : null}
      <div className={styles.controlMeta} aria-live="polite">
        <span>Analytics：{analyticsStatus}</span>
        <span>Briefing：{workbenchStatus}</span>
        <span>当前 Scope：{scope.storeRef || "no_data"}</span>
      </div>
      {surface === "capabilities" ? <CapabilitiesSurface /> : null}
      {surface === "journey" ? <JourneySurface snapshot={snapshot} status={status} /> : null}
      {surface === "sources" ? <SourceSurface snapshot={snapshot} briefing={briefing} status={status} /> : null}
      {surface === "enterprise" ? <EnterpriseSurface scope={scope} snapshot={snapshot} briefing={briefing} status={status} /> : null}
      {surface === "product-value" ? <ProductValueSurface snapshot={snapshot} briefing={briefing} status={status} /> : null}
      {surface === "scenarios" ? <ScenarioSurface snapshot={snapshot} status={status} asOf={asOf} /> : null}
      {surface === "agent-control" ? <AgentSurface briefing={briefing} status={status} /> : null}
      {surface === "reliability" ? <ReliabilitySurface analyticsStatus={analyticsStatus} workbenchStatus={workbenchStatus} status={status} snapshotHash={snapshotHash} /> : null}
    </>
  );
}

function SourceSurface({ snapshot, briefing, status }: { snapshot: OperatingAnalyticsSnapshot | null; briefing: OperatingWorkbenchBriefing | null; status: DataStatus }) {
  const gaps = Array.from(new Set([...(snapshot?.data_gaps ?? []), ...(snapshot?.source_gaps ?? []), ...(briefing?.source_gaps ?? [])]));
  const excluded = Array.from(new Set([...(snapshot?.excluded_sources ?? []), ...(briefing?.excluded_sources ?? [])]));
  return (
    <>
      <div className={styles.controlGrid}>
        <MetricCard label="来源缺口" value={formatCount(gaps.length, status)} definition="只读投影返回的 data_gaps/source_gaps，不把缺口转换成 0。" status={gaps.length ? "partial" : status} />
        <MetricCard label="排除来源" value={formatCount(excluded.length, status)} definition="当前作用域被服务端排除的来源数量。" status={excluded.length ? "partial" : status} />
        <MetricCard label="定时采集计划" value="no_data" definition="SourceSchedule/AcquisitionRun 投影尚未接入本页。" status="no_data" />
      </div>
      <section className={styles.section} aria-labelledby="source-gap-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Source registry</p><h2 id="source-gap-title">来源缺口与排除项</h2></div><p>抓取、解析、权限、服务条款和作用域失败必须分别由服务端合同解释。</p></div>
        <DataTable caption="当前来源状态" rowHeaderKey="kind" columns={[{ key: "kind", label: "类别" }, { key: "status", label: "状态" }, { key: "items", label: "项目" }]} rows={[{ kind: "data/source gaps", status: <StatusBadge status={gaps.length ? "partial" : status} />, items: gaps.length ? gaps.join("、") : "no_data" }, { kind: "excluded sources", status: <StatusBadge status={excluded.length ? "partial" : status} />, items: excluded.length ? excluded.join("、") : "no_data" }]} />
      </section>
      <div className={styles.callout} role="note"><strong>采集边界：</strong>本页面不在浏览器中抓取网页、不使用 Cookie/localStorage、不绕过 CAPTCHA，也不把候选来源直接提升为经营事实。</div>
      <div className={styles.emptyBlock} role="status"><div><strong>SourceSchedule: no_data</strong><p>后续接入独立的计划—审核—运行投影后，才显示定时抓取队列、预算、重试和 Kill Switch。</p></div></div>
    </>
  );
}

export function ControlPlanePage({
  surface,
  journeyRef,
}: {
  surface: ControlPlaneSurface;
  journeyRef?: string;
}) {
  const projection = useBiProjection();
  const asOf = projection.snapshot?.source_as_of ?? projection.briefing?.as_of ?? null;
  const snapshotHash = projection.snapshot?.snapshot_sha256 ?? projection.briefing?.snapshot_sha256 ?? null;
  const status = projectionDataStatus(projection.status);
  return (
    <ScopeFrame
      surface={surface}
      scope={projection.scope}
      snapshot={projection.snapshot}
      briefing={projection.briefing}
      analyticsStatus={projection.analytics.status}
      workbenchStatus={projection.workbench.status}
      error={projection.error}
      status={status}
      asOf={asOf}
      sourceAsOf={asOf}
      snapshotHash={snapshotHash}
    />
  );
}

function CapabilitiesSurface() {
  const testedCount = capabilityAssertions.filter((item) => item.status === "tested" || item.status === "replayed").length;
  const implementedCount = capabilityAssertions.filter((item) => ["implemented", "tested", "replayed", "pilot_ready", "production_ready"].includes(item.status)).length;
  const productionReadyCount = capabilityAssertions.filter((item) => item.productionReady).length;
  return (
    <>
      <div className={styles.controlGrid}>
        <MetricCard label="能力项总数" value={capabilityAssertions.length} definition="这是本轮控制塔目录项数量，不是业务数据量。" status="ready" />
        <MetricCard label="已实现或验证" value={`${implementedCount}/${capabilityAssertions.length}`} definition="implemented / tested / replayed 等工程状态的聚合。" status="partial" />
        <MetricCard label="可真实生产" value={productionReadyCount} definition="没有独立生产 Gate 证据时不显示 ready。" status={productionReadyCount ? "ready" : "no_data"} />
      </div>
      <div className={styles.callout} role="note"><strong>成熟度规则：</strong>已实现不等于已回放，已回放不等于生产可用；当前 {testedCount} 项有测试级证据，其余状态仍需独立 Gate。</div>
      <section className={styles.section} aria-labelledby="capability-table-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">CapabilityAssertion</p><h2 id="capability-table-title">能力证据矩阵</h2></div><p>每项能力必须能指向合同、测试、回放或生产 Gate；禁止用页面数量替代能力证明。</p></div>
        <DataTable
          caption="KJDS 能力成熟度矩阵"
          rowHeaderKey="title"
          columns={[{ key: "title", label: "能力" }, { key: "domain", label: "领域" }, { key: "status", label: "状态" }, { key: "owner", label: "Owner" }, { key: "gate", label: "Gate" }, { key: "proof", label: "证明" }]}
          rows={capabilityAssertions.map((item) => ({
            title: item.title,
            domain: item.domain,
            status: <StatusBadge status={capabilityDataStatus(item.status)} />,
            owner: item.owner,
            gate: item.gate,
            proof: item.proof,
          }))}
        />
      </section>
    </>
  );
}

function JourneySurface({ snapshot, status }: { snapshot: OperatingAnalyticsSnapshot | null; status: DataStatus }) {
  const stages = snapshot?.stages ?? [];
  return (
    <>
      <div className={styles.controlGrid}>
        <MetricCard label="经营阶段" value={formatCount(stages.length, status)} definition="来自当前 scoped OperatingAnalyticsSnapshot，不补齐缺失阶段。" status={status} />
        <MetricCard label="漏斗节点" value={formatCount(snapshot?.pipeline.length, status)} definition="服务端返回的 pipeline 节点数量。" status={status} />
        <MetricCard label="回放状态" value={snapshot ? "只读投影" : "no_data"} definition="当前页面不授予 Permit、执行或扩量权限。" status={snapshot ? "partial" : "no_data"} />
      </div>
      <section className={styles.section} aria-labelledby="journey-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Journey nodes</p><h2 id="journey-title">服务端经营阶段</h2></div><p>阶段状态、事实和 source IDs 完全来自快照；缺失阶段保持 no_data。</p></div>
        {stages.length ? (
          <div className={styles.journeyList}>
            {stages.map((stage) => {
              const stageStatus = stage.status === "verified" ? "ready" : stage.status === "in_progress" ? "partial" : stage.status;
              return (
                <article className={styles.journeyCard} key={stage.id}>
                  <div className={styles.journeyHeader}><strong>{stage.label}</strong><StatusBadge status={stageStatus as DataStatus} /></div>
                  <p>{stage.next_action}</p>
                  <dl className={styles.journeyFacts}>
                    <div><dt>Workspace</dt><dd>{stage.workspace}</dd></div>
                    <div><dt>进度</dt><dd>{stage.status === "verified" || stage.status === "in_progress" ? `${stage.current}/${stage.target} · ${stage.progress_percent}%` : stage.status}</dd></div>
                    <div><dt>Evidence / source</dt><dd>{stage.source_ids.length ? stage.source_ids.length : "no_data"}</dd></div>
                  </dl>
                </article>
              );
            })}
          </div>
        ) : <EmptyBlock title="journey: no_data" description="当前作用域没有可回放的真实经营阶段，未生成替代节点。" />}
      </section>
      <section className={styles.section} aria-labelledby="pipeline-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Pipeline</p><h2 id="pipeline-title">漏斗数据表</h2></div><p>漏斗节点不自动计算转化率，不把不同 authority 拼成一个结论。</p></div>
        <DataTable caption="经营旅程漏斗" rowHeaderKey="label" columns={[{ key: "label", label: "节点" }, { key: "value", label: "值" }, { key: "unit", label: "单位" }]} rows={(snapshot?.pipeline ?? []).map((item) => ({ label: item.label, value: item.value, unit: item.unit }))} />
      </section>
      <section className={styles.section} aria-labelledby="journey-policy-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Safety semantics</p><h2 id="journey-policy-title">状态边界</h2></div></div>
        <div className={styles.controlPanel}><ul className={styles.policyList}>{journeyPolicy.map((item) => <li key={item}>{item}</li>)}</ul></div>
      </section>
    </>
  );
}

function EnterpriseSurface({
  scope,
  snapshot,
  briefing,
  status,
}: {
  scope: ReturnType<typeof useBiProjection>["scope"];
  snapshot: OperatingAnalyticsSnapshot | null;
  briefing: OperatingWorkbenchBriefing | null;
  status: DataStatus;
}) {
  const operationalItems = briefing?.work_items.length ?? snapshot?.priority_items.length ?? null;
  const guardrailCount = snapshot ? Object.values(snapshot.guardrails).filter((value) => value === false).length : null;
  return (
    <>
      <div className={styles.controlGrid}>
        <MetricCard label="Authority Scope" value={scope.tenantRef && scope.storeRef ? "scoped" : "no_data"} definition="来自 /auth/session 和 scoped projection 的租户/店铺授权。" status={scope.tenantRef && scope.storeRef ? "ready" : status} />
        <MetricCard label="Commercial Scope" value="no_data" definition="套餐、Entitlement、Usage 和 Billing 尚未接入本只读投影。" status="no_data" />
        <MetricCard label="Operational Scope" value={formatCount(operationalItems, status)} definition="当前 briefing/snapshot 的工作项数量，不等于业务动作已执行。" status={status} />
      </div>
      <section className={styles.section} aria-labelledby="authority-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Authority Scope</p><h2 id="authority-title">当前授权边界</h2></div><p>URL 不扩大权限；缺省店铺来自 session default_store_ref；未授权店铺不发送经营请求。</p></div>
        <div className={styles.controlGrid}>
          <ControlCard title="Tenant" value={scope.tenantRef || "no_data"} status={scope.tenantRef ? "ready" : "no_data"} detail="身份会话提供的租户引用。" />
          <ControlCard title="当前店铺" value={scope.storeRef || "no_data"} status={scope.storeRef ? "ready" : "no_data"} detail="当前投影请求使用的 store_ref。" />
          <ControlCard title="授权店铺数" value={scope.storeRefs.length ? String(scope.storeRefs.length) : "no_data"} status={scope.storeRefs.length ? "ready" : "no_data"} detail="只显示当前身份已授权的 raw store_ref。" />
        </div>
      </section>
      <section className={styles.section} aria-labelledby="operational-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Operational Scope</p><h2 id="operational-title">运行边界与 guardrails</h2></div><p>本页只观察运行状态；不把 Agent、套餐或页面权限升级为业务事实权限。</p></div>
        <div className={styles.controlGrid}>
          <ControlCard title="当前工作项" value={formatCount(operationalItems, status)} status={status} detail="来自 scoped briefing / analytics priority items。" />
          <ControlCard title="禁止外部写入" value={snapshot ? "enforced" : "no_data"} status={snapshot ? "ready" : "no_data"} detail="服务端 guardrail：platform_write_allowed=false。" />
          <ControlCard title="禁用自动事实晋级" value={snapshot ? "enforced" : "no_data"} status={snapshot ? "ready" : "no_data"} detail={`当前读模型返回 ${guardrailCount ?? "no_data"} 个 false guardrail。`} />
        </div>
      </section>
    </>
  );
}

function ProductValueSurface({ snapshot, briefing, status }: { snapshot: OperatingAnalyticsSnapshot | null; briefing: OperatingWorkbenchBriefing | null; status: DataStatus }) {
  const workItems = briefing?.work_items ?? snapshot?.priority_items ?? [];
  const evidenceBound = workItems.filter((item) => item.evidence_ids.length > 0).length;
  const attentionItems = workItems.filter((item) => item.risk || item.overdue).length;
  return (
    <>
      <div className={styles.controlGrid}>
        <MetricCard label="当前工作项" value={formatCount(workItems.length, status)} definition="真实投影中的待处理项；不是产品价值完成数。" status={status} />
        <MetricCard label="Evidence 绑定工作项" value={formatCount(evidenceBound, status)} definition="有至少一个服务端 evidence_id 的工作项数量。" status={status} />
        <MetricCard label="风险或逾期项" value={formatCount(attentionItems, status)} definition="仅从当前 briefing 字段读取，不推断财务影响。" status={status} />
      </div>
      <div className={styles.callout} role="note"><strong>产品价值边界：</strong>Decision/Outcome 事件尚未进入当前读模型；因此“证据支持的已完成决策”保持 no_data，而不使用工作项数量冒充 ROI。</div>
      <section className={styles.section} aria-labelledby="value-contract-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Outcome telemetry</p><h2 id="value-contract-title">产品价值指标合同</h2></div><p>先把指标定义和缺口公开，再接入真实事件；不使用页面访问量作为成功指标。</p></div>
        <DataTable caption="产品价值遥测合同" rowHeaderKey="id" columns={[{ key: "id", label: "Metric ID" }, { key: "label", label: "指标" }, { key: "status", label: "状态" }, { key: "reason", label: "接入条件" }]} rows={productValueMetrics.map(([id, label, reason]) => ({ id, label, status: <StatusBadge status="no_data" />, reason }))} />
      </section>
      <section className={styles.section} aria-labelledby="anti-metric-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Guardrails</p><h2 id="anti-metric-title">反指标</h2></div></div>
        <div className={styles.controlPanel}><ul className={styles.policyList}><li>看板访问量高但没有 Decision/Action/Outcome 记录，不计产品成功。</li><li>AI 输出没有 evidence 引用，不计智能化收益。</li><li>自动化执行成功但业务结果未 reconciliation，不计经营收益。</li></ul></div>
      </section>
    </>
  );
}

function ScenarioSurface({ snapshot, status, asOf }: { snapshot: OperatingAnalyticsSnapshot | null; status: DataStatus; asOf: string | null }) {
  return (
    <>
      <div className={styles.controlGrid}>
        <MetricCard label="情景基线" value={snapshot ? "snapshot" : "no_data"} definition="情景必须绑定当前 scoped snapshot 和 as_of。" status={snapshot ? "partial" : "no_data"} asOf={asOf} />
        <MetricCard label="模拟结果" value="no_data" definition="服务端 scenario projection 尚未接入，不生成预测数字。" status="no_data" />
        <MetricCard label="实际账污染" value="0 · guardrail" definition="本页面没有写入 Actual accrual、Settled contribution 或 Actual Cash CM3 的权限。" status="ready" />
      </div>
      <section className={styles.section} aria-labelledby="scenario-input-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Scenario inputs</p><h2 id="scenario-input-title">受控模拟变量</h2></div><p>变量名显式使用 scenario_*；当前只展示合同，不接受前端计算或写入。</p></div>
        <DataTable caption="情景输入合同" rowHeaderKey="id" columns={[{ key: "id", label: "变量" }, { key: "label", label: "业务含义" }, { key: "status", label: "状态" }]} rows={scenarioInputs.map(([id, label, reason]) => ({ id, label, status: <span className={styles.muted}>{reason}</span> }))} />
      </section>
      <div className={styles.emptyBlock} role="status"><div><strong>scenario result: no_data</strong><p>没有真实的服务端情景投影，页面不生成价格、广告、库存、汇率或现金预测。</p></div></div>
    </>
  );
}

function AgentSurface({ briefing, status }: { briefing: OperatingWorkbenchBriefing | null; status: DataStatus }) {
  const agents = briefing?.agents ?? [];
  return (
    <>
      <div className={styles.controlGrid}>
        <MetricCard label="Agent Sessions" value={formatCount(agents.length, status)} definition="来自当前 scoped briefing 的 Agent 摘要。" status={status} />
        <MetricCard label="外部写入" value="disabled" definition="本页面不创建 Permit，不执行平台动作。" status="ready" />
        <MetricCard label="人审边界" value={briefing ? "required" : "no_data"} definition="当前 briefing 的 human_required / advisory_only 合同。" status={briefing ? "ready" : "no_data"} />
      </div>
      <section className={styles.section} aria-labelledby="agent-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Agent sessions</p><h2 id="agent-title">当前 Agent 观察</h2></div><p>只显示服务端已返回的 Agent 状态；不从页面推断工具权限或运行结果。</p></div>
        {agents.length ? <div className={styles.statusList}>{agents.map((agent) => <li key={agent.agent_id}><div><strong>{agent.name}</strong><small>{agent.current_focus} · {agent.work_item_count} 个工作项</small></div><StatusBadge status={agent.status === "needs_attention" ? "partial" : "blocked"} /></li>)}</div> : <EmptyBlock title="agent session: no_data" description="当前作用域没有 Agent 摘要，未生成运行中或完成中的虚假状态。" />}
      </section>
      <section className={styles.section} aria-labelledby="agent-policy-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Safety envelope</p><h2 id="agent-policy-title">Agent 权限边界</h2></div></div>
        <div className={styles.controlPanel}><ul className={styles.policyList}>{actionSafetyEnvelope.map((item) => <li key={item}>{item}</li>)}</ul></div>
      </section>
    </>
  );
}

function ReliabilitySurface({ analyticsStatus, workbenchStatus, status, snapshotHash }: { analyticsStatus: string; workbenchStatus: string; status: DataStatus; snapshotHash: string | null }) {
  const projectionRows = useMemo(() => [
    { id: "scope", label: "Scope / session", status: status, value: status === "ready" || status === "partial" ? "可读取" : "不可用" },
    { id: "analytics", label: "Analytics projection", status: projectionDataStatus(analyticsStatus), value: analyticsStatus },
    { id: "briefing", label: "Briefing projection", status: projectionDataStatus(workbenchStatus), value: workbenchStatus },
  ], [analyticsStatus, status, workbenchStatus]);
  return (
    <>
      <div className={styles.controlGrid}>
        <MetricCard label="当前投影状态" value={status} definition="投影状态不等于 API/Worker/Provider 健康。" status={status} />
        <MetricCard label="快照锚点" value={snapshotHash ? snapshotHash.slice(0, 12) : "no_data"} definition="只显示服务端返回的 snapshot hash 摘要。" status={snapshotHash ? "ready" : "no_data"} />
        <MetricCard label="自动降级" value="fail-closed" definition="权限、证据和事实缺口默认阻断或 no_data。" status="ready" />
      </div>
      <section className={styles.section} aria-labelledby="projection-health-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Read model health</p><h2 id="projection-health-title">当前可观测投影</h2></div><p>当前前端只拥有投影级证据，不把“页面能加载”解释为完整运行健康。</p></div>
        <DataTable caption="投影健康状态" rowHeaderKey="label" columns={[{ key: "label", label: "投影" }, { key: "status", label: "状态" }, { key: "value", label: "返回" }]} rows={projectionRows.map((row) => ({ label: row.label, status: <StatusBadge status={row.status} />, value: row.value }))} />
      </section>
      <section className={styles.section} aria-labelledby="reliability-gap-title">
        <div className={styles.sectionHeader}><div><p className="eyebrow">Reliability gaps</p><h2 id="reliability-gap-title">尚未接入的运行信号</h2></div><p>缺少服务端合同时保持 no_data，不用绿色状态掩盖证据缺口。</p></div>
        <DataTable caption="可靠性信号接入缺口" rowHeaderKey="id" columns={[{ key: "id", label: "信号" }, { key: "label", label: "显示名" }, { key: "reason", label: "边界" }]} rows={reliabilityGaps.map(([id, label, reason]) => ({ id, label, reason: <span className={styles.muted}>no_data · {reason}</span> }))} />
      </section>
    </>
  );
}

function ControlCard({ title, value, status, detail }: { title: string; value: string; status: DataStatus; detail: string }) {
  return <article className={styles.controlCard}><div className={styles.controlCardHeader}><strong>{title}</strong><StatusBadge status={status} /></div><div className={status === "no_data" ? styles.controlValueMuted : styles.controlValue}>{value}</div><p>{detail}</p></article>;
}

function EmptyBlock({ title, description }: { title: string; description: string }) {
  return <div className={styles.emptyBlock} role="status"><div><strong>{title}</strong><p>{description}</p></div></div>;
}
