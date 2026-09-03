"use client";

import { useMemo, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import type {
  OperatingAnalyticsSnapshot,
  OperatingWorkbenchBriefing,
} from "../dashboard/contracts";
import {
  AppShell,
  BriefingFrame,
  DataTable,
  EvidenceDrawer,
  MetricCard,
  ScopeBar,
  StatusBadge,
  type DataStatus,
} from "../ui2/ui2";
import {
  projectionStatus,
  summaryMetricStatus,
  summaryMetricValue,
  type AnalyticsSummaryKey,
} from "./truth";
import { useBiProjection } from "./use-bi-projection";
import styles from "./briefing.module.css";

const metricDefinitions: Array<{
  key: AnalyticsSummaryKey;
  label: string;
  definition: string;
}> = [
  { key: "catalog_items", label: "目录商品", definition: "当前授权作用域内通过目录权威投影的商品数。" },
  { key: "bound_listings", label: "已绑定 Listing", definition: "与 Canonical Product 建立当前作用域绑定的 Listing。" },
  { key: "available_stock", label: "可用库存", definition: "作用域目录返回的库存合计，不等于可售承诺。" },
  { key: "gate_blockers", label: "Gate 阻断", definition: "readiness 权威投影报告的当前阻断数。" },
  { key: "growth_snapshot_skus", label: "增长快照 SKU", definition: "具有当前作用域增长真源的 SKU 数。" },
  { key: "ready_execution_plans", label: "可执行计划", definition: "通过服务端 readiness 的计划数，仍需独立审批与 Permit。" },
];

const pageLabels = ["结论与 Scope", "六项经营指标", "Top 3 异常", "缺口与 Evidence"] as const;

export function BiBriefing() {
  const { scope, snapshot, briefing, analytics, workbench, status, error, refresh } = useBiProjection();
  const [pageIndex, setPageIndex] = useState(0);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);

  const metrics = useMemo(() => metricDefinitions.map((definition) => ({
    ...definition,
    ...metricPresentation(snapshot, definition.key, analytics.status),
  })), [analytics.status, snapshot]);
  const topItems = useMemo(() => briefing?.work_items.slice(0, 3) ?? [], [briefing]);
  const gaps = useMemo(() => collectGaps(snapshot, briefing), [briefing, snapshot]);
  const excludedSources = useMemo(
    () => uniqueStrings(optionalStrings(snapshot, "excluded_sources"), optionalStrings(briefing, "excluded_sources")),
    [briefing, snapshot],
  );
  const admittedEvidenceIds = useMemo(
    () => collectAdmittedEvidenceIds(snapshot, briefing),
    [briefing, snapshot],
  );
  const asOf = snapshot?.source_as_of ?? optionalString(briefing, "as_of") ?? scope.requestAsOf;
  const snapshotHash = snapshot?.snapshot_sha256 ?? briefing?.snapshot_sha256 ?? null;
  const scopedHref = buildScopedHref(scope.storeRef, scope.requestAsOf ?? scope.asOf);

  const pages: ReactNode[] = [
    <ScopePage
      key="scope"
      status={status}
      storeRef={scope.storeRef}
      tenantRef={scope.tenantRef}
      queryAsOf={scope.asOf}
      requestAsOf={scope.requestAsOf}
      authorityStatus={scope.authorityStatus}
      authoritySha256={scope.authoritySha256}
      snapshot={snapshot}
      briefing={briefing}
      analyticsStatus={analytics.status}
      workbenchStatus={workbench.status}
    />,
    <MetricsPage key="metrics" metrics={metrics} asOf={asOf} />,
    <ExceptionsPage
      key="exceptions"
      items={topItems}
      status={workbench.status}
      onEvidence={setEvidenceId}
    />,
    <GovernancePage
      key="governance"
      status={status}
      gaps={gaps}
      excludedSources={excludedSources}
      evidenceIds={admittedEvidenceIds}
      analyticsHash={snapshot?.snapshot_sha256 ?? null}
      briefingHash={briefing?.snapshot_sha256 ?? null}
      onEvidence={setEvidenceId}
    />,
  ];

  return (
    <AppShell
      title="经营简报"
      eyebrow="BRIEFING / 手动翻页"
      description="结论优先，但每项结论继续绑定授权 Scope、服务端状态、数据缺口和 Evidence；不自动翻页、不生成替代经营数据。"
      status={status}
      asOf={asOf}
      snapshotHash={snapshotHash}
      scope={(
        <ScopeBar
          store={scope.storeRef || "no_data"}
          stores={scope.storeRefs}
          selectedStore={scope.storeRef}
          onStoreChange={scope.setStoreRef}
          disabled={scope.status === "loading"}
          tenant={scope.tenantRef}
          asOf={scope.requestAsOf}
          sourceAsOf={snapshot?.source_as_of ?? optionalString(briefing, "as_of")}
          scopeAuthorityHash={scope.authoritySha256}
          period="latest · 正在固定本轮 cutoff"
          currency="服务端原始口径"
          timezone="URL as_of 必须含时区"
        />
      )}
      actions={(
        <>
          <button type="button" onClick={() => void refresh()}>刷新快照</button>
          <button type="button" onClick={() => window.print()}>打印四页</button>
          <Link href={`/bi/overview${scopedHref}`}>返回总览</Link>
          <Link href={`/bi/wallboard${scopedHref}`}>打开大屏</Link>
        </>
      )}
    >
      {error ? <div className={styles.errorBanner} role="alert"><StatusBadge status={status} /><span>{error}</span></div> : null}

      <nav className={styles.pageControls} aria-label="简报翻页">
        <div className={styles.pageTabs} role="tablist" aria-label="简报页">
          {pageLabels.map((label, index) => (
            <button
              type="button"
              role="tab"
              id={`briefing-tab-${index + 1}`}
              aria-controls={`briefing-page-${index + 1}`}
              aria-selected={pageIndex === index}
              aria-current={pageIndex === index ? "page" : undefined}
              tabIndex={pageIndex === index ? 0 : -1}
              onClick={() => setPageIndex(index)}
              onKeyDown={(event) => handleTabKeyDown(event, index, pageLabels.length, setPageIndex)}
              key={label}
            >
              {index + 1}. {label}
            </button>
          ))}
        </div>
        <div className={styles.pageActions}>
          <button type="button" disabled={pageIndex === 0} onClick={() => setPageIndex((current) => Math.max(0, current - 1))}>上一页</button>
          <span className={styles.pagePosition} aria-live="polite">第 {pageIndex + 1} / {pages.length} 页</span>
          <button type="button" disabled={pageIndex === pages.length - 1} onClick={() => setPageIndex((current) => Math.min(pages.length - 1, current + 1))}>下一页</button>
        </div>
      </nav>

      <p className={styles.printScope}>店铺：{scope.storeRef || "no_data"} · Tenant：{scope.tenantRef ?? "no_data"} · 查询方式：{scope.asOf ?? "latest"} · 本轮截止：{scope.requestAsOf ?? "no_data"} · 生成方式：服务端只读投影</p>
      {pages.map((page, index) => (
        <div
          className={styles.briefingPage}
          id={`briefing-page-${index + 1}`}
          role="tabpanel"
          aria-labelledby={`briefing-tab-${index + 1}`}
          hidden={pageIndex !== index}
          key={pageLabels[index]}
        >
          {page}
        </div>
      ))}

      <EvidenceDrawer
        evidenceId={evidenceId}
        snapshotHash={snapshotHash}
        open={Boolean(evidenceId)}
        onClose={() => setEvidenceId(null)}
      />
    </AppShell>
  );
}

function ScopePage({
  status,
  storeRef,
  tenantRef,
  queryAsOf,
  requestAsOf,
  authorityStatus,
  authoritySha256,
  snapshot,
  briefing,
  analyticsStatus,
  workbenchStatus,
}: {
  status: DataStatus;
  storeRef: string;
  tenantRef: string | null;
  queryAsOf: string | null;
  requestAsOf: string | null;
  authorityStatus: string | null;
  authoritySha256: string | null;
  snapshot: OperatingAnalyticsSnapshot | null;
  briefing: OperatingWorkbenchBriefing | null;
  analyticsStatus: DataStatus;
  workbenchStatus: DataStatus;
}) {
  return (
    <BriefingFrame title="01 · 当前结论与授权 Scope">
      <div className={styles.leadGrid}>
        <article className={styles.leadCard}>
          <StatusBadge status={status} />
          <h3>{conclusionTitle(status)}</h3>
          <p>{conclusionBody(status, snapshot, briefing)}</p>
        </article>
        <article className={styles.leadCard}>
          <h3>本页判断边界</h3>
          <p>只复述已经通过共享 scope validator 的服务端投影；建议动作不等于 Approval、Permit 或平台写入。</p>
          <dl className={styles.scopeFacts}>
            <div><dt>Tenant</dt><dd>{tenantRef ?? "no_data"}</dd></div>
            <div><dt>Store</dt><dd>{storeRef || "no_data"}</dd></div>
            <div><dt>查询方式</dt><dd>{queryAsOf ? `固定 ${formatDate(queryAsOf)}` : "latest"}</dd></div>
            <div><dt>本轮截止</dt><dd>{requestAsOf ? formatDate(requestAsOf) : "no_data"}</dd></div>
            <div><dt>Scope authority</dt><dd>{authorityStatus ?? "no_data"} · {authoritySha256 ?? "no_data"}</dd></div>
            <div><dt>Analytics</dt><dd>{snapshot ? projectionStatus(snapshot.status) : analyticsStatus}</dd></div>
            <div><dt>Briefing</dt><dd>{briefing ? projectionStatus(briefing.status) : workbenchStatus}</dd></div>
          </dl>
        </article>
      </div>
    </BriefingFrame>
  );
}

function MetricsPage({
  metrics,
  asOf,
}: {
  metrics: Array<(typeof metricDefinitions)[number] & { status: DataStatus; value: number | "no_data" | "blocked" | "forbidden" }>;
  asOf: string | null;
}) {
  return (
    <BriefingFrame title="02 · 六项经营指标">
      <div className={styles.metricLayout}>
        {metrics.map((metric) => (
          <MetricCard
            key={metric.key}
            label={metric.label}
            value={metric.value}
            status={metric.status}
            definition={metric.definition}
            asOf={asOf}
          />
        ))}
      </div>
      <div className={styles.boundaryNotice} role="note">
        <StatusBadge status="no_data" />
        <span>变化、同比、目标差与趋势没有服务端历史合同时统一保持 no_data；来源权威缺失时，服务端占位 0 不作为经营事实展示。</span>
      </div>
    </BriefingFrame>
  );
}

function ExceptionsPage({
  items,
  status,
  onEvidence,
}: {
  items: OperatingWorkbenchBriefing["work_items"];
  status: DataStatus;
  onEvidence: (evidenceId: string) => void;
}) {
  return (
    <BriefingFrame title="03 · Top 3 异常与下一动作">
      <p className={styles.sectionLead}>严格保留 OperatingWorkbench 的服务端顺序，不在浏览器重算严重度或优先级。</p>
      {items.length ? (
        <>
          <div className={styles.exceptionList}>
            {items.map((item, index) => (
              <article className={styles.exceptionCard} key={item.id}>
                <span className={styles.exceptionIndex} aria-label={`第 ${index + 1} 项`}>{index + 1}</span>
                <div>
                  <h3>{item.title}</h3>
                  <p>{item.next_action}</p>
                  {item.evidence_ids.length ? (
                    <div className={styles.evidenceActions} aria-label={`${item.title} 的 Evidence`}>
                      {item.evidence_ids.map((id) => <button type="button" onClick={() => onEvidence(id)} key={id}>Evidence {shortId(id)}</button>)}
                    </div>
                  ) : null}
                </div>
                <div className={styles.exceptionMeta}>
                  <span><b>Owner</b> {item.agent_name}</span>
                  <span><b>状态</b> {item.status}</span>
                  <span><b>风险</b> {item.risk}</span>
                  <span><b>人工复核</b> {item.human_required ? "required" : "no_data"}</span>
                </div>
              </article>
            ))}
          </div>
          <DataTable
            caption="Top 3 异常与工作项数据表"
            columns={[
              { key: "title", label: "事项" },
              { key: "owner", label: "Owner" },
              { key: "status", label: "状态" },
              { key: "risk", label: "风险" },
              { key: "next", label: "下一动作" },
            ]}
            rows={items.map((item) => ({ title: item.title, owner: item.agent_name, status: item.status, risk: item.risk, next: item.next_action }))}
          />
        </>
      ) : <EmptyState status={status} message="当前 scoped Briefing 没有可展示的异常或工作项；不从其他店铺或 legacy 全局队列补值。" />}
    </BriefingFrame>
  );
}

function GovernancePage({
  status,
  gaps,
  excludedSources,
  evidenceIds,
  analyticsHash,
  briefingHash,
  onEvidence,
}: {
  status: DataStatus;
  gaps: string[];
  excludedSources: string[];
  evidenceIds: string[];
  analyticsHash: string | null;
  briefingHash: string | null;
  onEvidence: (evidenceId: string) => void;
}) {
  return (
    <BriefingFrame title="04 · 数据缺口、Evidence 与权威边界">
      <div className={styles.governanceGrid}>
        <article className={styles.governanceCard}>
          <h3>数据缺口</h3>
          {gaps.length ? <ul className={styles.gapList}>{gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul> : (
            <EmptyState status={status === "ready" ? "ready" : "no_data"} message={status === "ready" ? "服务端未报告数据缺口。" : "缺口投影不可用，保持 no_data。"} />
          )}
        </article>
        <article className={styles.governanceCard}>
          <h3>权威与排除来源</h3>
          <dl className={styles.authorityFacts}>
            <div><dt>Analytics hash</dt><dd>{analyticsHash ?? "no_data"}</dd></div>
            <div><dt>Briefing hash</dt><dd>{briefingHash ?? "no_data"}</dd></div>
            <div><dt>外部写入</dt><dd>禁止</dd></div>
            <div><dt>自动模式切换</dt><dd>禁止</dd></div>
            <div><dt>排除来源</dt><dd>{excludedSources.length ? excludedSources.join("、") : "no_data"}</dd></div>
          </dl>
          <div className={styles.evidenceActions} aria-label="当前投影准入的 Evidence">
            {evidenceIds.map((id) => <button type="button" onClick={() => onEvidence(id)} key={id}>查看 Evidence {shortId(id)}</button>)}
            {!evidenceIds.length ? <span>Evidence：no_data</span> : null}
          </div>
          <p>这里只开放 focal listing 与 scoped priority/work items 明确返回的 Evidence ID；stage source ID 不自动当作 Evidence。</p>
        </article>
      </div>
    </BriefingFrame>
  );
}

function EmptyState({ status, message }: { status: DataStatus; message: string }) {
  return <div className={styles.emptyState} role="status"><div><StatusBadge status={status} /><p>{message}</p></div></div>;
}

function conclusionTitle(status: DataStatus) {
  if (status === "ready") return "当前作用域投影已可复核";
  if (status === "partial") return "部分真源可用，结论需带缺口阅读";
  if (status === "loading") return "正在固定本轮作用域与数据时点";
  if (status === "forbidden") return "当前身份无权读取该店铺";
  if (status === "blocked") return "服务端权威门阻断本轮判断";
  if (status === "conflicted") return "Scope 或响应合同发生冲突";
  if (status === "error") return "经营投影读取失败";
  return "当前没有足够的真实经营数据";
}

function conclusionBody(
  status: DataStatus,
  snapshot: OperatingAnalyticsSnapshot | null,
  briefing: OperatingWorkbenchBriefing | null,
) {
  if (status !== "ready" && status !== "partial") {
    return "本简报停止输出数字结论；请先处理页面报告的授权、合同或来源问题。";
  }
  if (!snapshot && !briefing) return "没有可复核的服务端投影，本页保持 no_data。";
  const itemSummary = briefing ? `${briefing.work_items.length} 个可见工作项` : "工作项投影 no_data";
  const gaps = collectGaps(snapshot, briefing);
  const gapSummary = snapshot || briefing ? `${gaps.length} 个已报告数据缺口` : "缺口投影 no_data";
  return `当前只读投影报告 ${itemSummary}、${gapSummary}。请先按服务端顺序处理异常，再回到原工作区核验证据与审批条件。`;
}

function collectGaps(
  snapshot: OperatingAnalyticsSnapshot | null,
  briefing: OperatingWorkbenchBriefing | null,
) {
  return uniqueStrings(
    snapshot?.data_gaps ?? [],
    optionalStrings(snapshot, "source_gaps"),
    optionalStrings(briefing, "source_gaps"),
  );
}

function collectAdmittedEvidenceIds(
  snapshot: OperatingAnalyticsSnapshot | null,
  briefing: OperatingWorkbenchBriefing | null,
) {
  return uniqueStrings(
    snapshot?.focal_listing?.source_evidence_id ? [snapshot.focal_listing.source_evidence_id] : [],
    ...(snapshot?.priority_items.map((item) => item.evidence_ids) ?? []),
    ...(briefing?.work_items.map((item) => item.evidence_ids) ?? []),
  );
}

function metricPresentation(
  snapshot: OperatingAnalyticsSnapshot | null,
  key: AnalyticsSummaryKey,
  fallback: DataStatus,
): { status: DataStatus; value: number | "no_data" | "blocked" | "forbidden" } {
  if (!snapshot) {
    if (fallback === "blocked") return { status: fallback, value: "blocked" };
    if (fallback === "forbidden") return { status: fallback, value: "forbidden" };
    return { status: fallback, value: "no_data" };
  }
  const metricStatus = summaryMetricStatus(snapshot, key, fallback);
  return { status: metricStatus, value: summaryMetricValue(snapshot, key, fallback) };
}

function handleTabKeyDown(
  event: ReactKeyboardEvent<HTMLButtonElement>,
  current: number,
  count: number,
  setPageIndex: (index: number) => void,
) {
  let next: number | null = null;
  if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (current + 1) % count;
  if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (current - 1 + count) % count;
  if (event.key === "Home") next = 0;
  if (event.key === "End") next = count - 1;
  if (next === null) return;
  event.preventDefault();
  setPageIndex(next);
  document.getElementById(`briefing-tab-${next + 1}`)?.focus();
}

function optionalStrings(value: unknown, key: string): string[] {
  if (!value || typeof value !== "object") return [];
  const candidate = (value as Record<string, unknown>)[key];
  return Array.isArray(candidate) ? candidate.filter((item): item is string => typeof item === "string") : [];
}

function optionalString(value: unknown, key: string): string | null {
  if (!value || typeof value !== "object") return null;
  const candidate = (value as Record<string, unknown>)[key];
  return typeof candidate === "string" ? candidate : null;
}

function uniqueStrings(...groups: string[][]) {
  return Array.from(new Set(groups.flat().filter(Boolean)));
}

function buildScopedHref(storeRef: string | null, asOf: string | null) {
  const query = new URLSearchParams();
  if (storeRef) query.set("store_ref", storeRef);
  if (asOf) query.set("as_of", asOf);
  const value = query.toString();
  return value ? `?${value}` : "";
}

function shortId(value: string) {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
