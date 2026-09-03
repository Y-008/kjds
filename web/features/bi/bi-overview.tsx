"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, CircleAlert, FileCheck2, ListChecks, ScanSearch } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { OperatingAnalyticsSnapshot, OperatingWorkbenchBriefing } from "../dashboard/contracts";
import {
  AppShell,
  ChartFrame,
  DataTable,
  EvidenceDrawer,
  MetricCard,
  ScopeBar,
  StatusBadge,
  type DataStatus,
} from "../ui2/ui2";
import ui2 from "../ui2/ui2.module.css";
import {
  coverageStatus,
  hasAdmittedCatalog,
  pipelineStatus,
  projectionStatus,
  summaryMetricStatus,
  summaryMetricValue,
  type AnalyticsSummaryKey,
} from "./truth";
import { useBiProjection } from "./use-bi-projection";
import styles from "./bi.module.css";

const summaryMetricDefinitions: Array<{
  key: AnalyticsSummaryKey;
  label: string;
  definition: string;
}> = [
  { key: "catalog_items", label: "目录商品", definition: "当前授权作用域内通过目录权威投影的商品数量。" },
  { key: "bound_listings", label: "已绑定 Listing", definition: "已与 Canonical Product 建立当前作用域绑定的 Listing。" },
  { key: "available_stock", label: "可用库存", definition: "目录投影返回的库存合计，不等于可售承诺或已实现利润。" },
  { key: "gate_blockers", label: "Gate 阻断", definition: "服务端 readiness 权威投影报告的当前阻断数。" },
  { key: "growth_snapshot_skus", label: "增长快照 SKU", definition: "已有当前作用域增长 Evidence 的 SKU 数。" },
  { key: "ready_execution_plans", label: "可执行计划", definition: "服务端返回的受控计划数，仍需独立审批和一次性 Permit。" },
];

const queueDisplayLimit = 8;

export function BiOverview() {
  const {
    scope,
    snapshot,
    briefing,
    analytics,
    workbench,
    status,
    error,
    refresh,
  } = useBiProjection();
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [queueQuery, setQueueQuery] = useState("");
  const [queueRisk, setQueueRisk] = useState("all");
  const [queueStatus, setQueueStatus] = useState("all");

  const asOf = snapshot?.source_as_of ?? briefing?.as_of ?? null;
  const snapshotHash = snapshot?.snapshot_sha256 ?? briefing?.snapshot_sha256 ?? null;
  const scopedQuery = buildScopedQuery(scope.storeRef, scope.requestAsOf ?? scope.asOf);
  const metricRows = useMemo(
    () => summaryMetricDefinitions.map((definition) => ({
      ...definition,
      status: summaryMetricStatus(snapshot, definition.key, status),
      value: summaryMetricValue(snapshot, definition.key, status),
    })),
    [snapshot, status],
  );
  const coverageRows = useMemo(
    () => (snapshot?.coverage ?? []).map((item) => ({
      ...item,
      truthStatus: snapshot ? coverageStatus(snapshot, item.id) : "no_data" as DataStatus,
    })),
    [snapshot],
  );
  const pipelineRows = useMemo(
    () => (snapshot?.pipeline ?? []).map((item) => ({
      ...item,
      truthStatus: snapshot ? pipelineStatus(snapshot, item.id) : "no_data" as DataStatus,
    })),
    [snapshot],
  );
  const priorityItems = briefing?.work_items ?? snapshot?.priority_items ?? [];
  const queueRisks = useMemo(
    () => uniqueStrings(priorityItems.map((item) => item.risk)).sort(),
    [priorityItems],
  );
  const queueStatuses = useMemo(
    () => uniqueStrings(priorityItems.map((item) => item.status)).sort(),
    [priorityItems],
  );
  const filteredPriorityItems = useMemo(() => {
    const query = queueQuery.trim().toLowerCase();
    return priorityItems.filter((item) => {
      const matchesQuery = !query || [
        item.title,
        item.agent_name,
        item.next_action,
        item.source_id,
      ].some((value) => value.toLowerCase().includes(query));
      const matchesRisk = queueRisk === "all" || item.risk === queueRisk;
      const matchesStatus = queueStatus === "all" || item.status === queueStatus;
      return matchesQuery && matchesRisk && matchesStatus;
    });
  }, [priorityItems, queueQuery, queueRisk, queueStatus]);
  const queueFilterActive = Boolean(queueQuery.trim() || queueRisk !== "all" || queueStatus !== "all");
  const dataGaps = useMemo(
    () => uniqueStrings(
      snapshot?.data_gaps ?? [],
      snapshot?.source_gaps ?? [],
      briefing?.source_gaps ?? [],
    ),
    [briefing, snapshot],
  );
  const excludedSources = useMemo(
    () => uniqueStrings(snapshot?.excluded_sources ?? [], briefing?.excluded_sources ?? []),
    [briefing, snapshot],
  );
  const stageFrameStatus = snapshot ? projectionStatus(snapshot.status) : analytics.status;
  const coverageFrameStatus = collectionStatus(coverageRows.map((item) => item.truthStatus), analytics.status);
  const pipelineFrameStatus = collectionStatus(pipelineRows.map((item) => item.truthStatus), analytics.status);
  const briefingFrameStatus = briefing ? projectionStatus(briefing.status) : workbench.status;
  const coverageChartRows = coverageRows
    .filter((item) => item.truthStatus === "ready")
    .map((item) => ({ label: item.label, value: item.percent }));

  return (
    <AppShell
      title="BI Overview"
      eyebrow="经营分析 / 可信作用域"
      description="Analytics 与 Briefing 使用同一授权店铺和查询截止；每个数字都保留状态、时点、来源缺口和 Evidence 边界。"
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
          sourceAsOf={asOf}
          scopeAuthorityHash={scope.authoritySha256}
          period="latest · 本轮固定 cutoff"
          currency="服务端原始口径"
          timezone="ISO-8601 / 含时区"
        />
      )}
      actions={(
        <>
          <button type="button" onClick={refresh} disabled={status === "loading"}>刷新快照</button>
          <Link href={`/bi/wallboard${scopedQuery}`}>打开大屏</Link>
          <Link href={`/bi/briefing${scopedQuery}`}>经营简报</Link>
          <Link href="/profit-command">利润指挥</Link>
        </>
      )}
    >
      <div className={styles.projectionLive} role="status" aria-live="polite" aria-atomic="true">
        当前状态：{status} · 店铺：{scope.storeRef || "no_data"} · Analytics：{analytics.status} · Briefing：{workbench.status}
      </div>
      {error ? (
        <div className={styles.errorBanner} role="alert">
          <StatusBadge status={status === "loading" ? "loading" : status} />
          <span>{error}</span>
        </div>
      ) : null}
      {status === "no_data" || status === "blocked" || status === "forbidden" || status === "conflicted" ? (
        <div className={styles.truthBanner} role="note">
          <StatusBadge status={status} />
          <span>{stateExplanation(status)}</span>
        </div>
      ) : null}

      <DecisionSpine
        status={status}
        asOf={asOf}
        gapCount={dataGaps.length + excludedSources.length}
        snapshotHash={snapshotHash}
        item={priorityItems[0] ?? null}
        onEvidence={setEvidenceId}
      />

      <section aria-labelledby="summary-title" aria-busy={status === "loading"}>
        <div className={styles.sectionHeader}>
          <div><p className={ui2.eyebrow}>Summary</p><h2 id="summary-title">经营事实摘要</h2></div>
          <span className={styles.sectionHint}>来源权威缺失时，占位 0 显示为 no_data；当前合同未提供变化、目标差与历史趋势</span>
        </div>
        <div className={ui2.metricGrid}>
          {metricRows.map((metric) => (
            <MetricCard
              key={metric.key}
              label={metric.label}
              value={metric.value}
              status={metric.status}
              definition={metric.definition}
              asOf={metric.status === "ready" ? asOf : null}
            />
          ))}
        </div>
      </section>

      <div className={ui2.chartGrid}>
        <ChartFrame
          title="经营阶段"
          description="current / target / progress_percent 与每阶段状态均来自同一 scoped OperatingAnalyticsSnapshot。"
          status={stageFrameStatus}
          table={(
            <DataTable
              caption="经营阶段数据表"
              rowHeaderKey="label"
              columns={[
                { key: "label", label: "阶段" },
                { key: "status", label: "状态" },
                { key: "progress", label: "进度" },
                { key: "next", label: "下一动作" },
              ]}
              rows={(snapshot?.stages ?? []).map((stage) => ({
                label: stage.label,
                status: stage.status,
                progress: stage.status === "verified" || stage.status === "in_progress"
                  ? `${stage.current}/${stage.target} · ${stage.progress_percent}%`
                  : stage.status,
                next: stage.next_action,
              }))}
            />
          )}
        >
          <div className={styles.stageList}>
            {(snapshot?.stages ?? []).map((stage) => {
              const itemStatus = stageStatus(stage.status);
              const hasProgress = itemStatus === "ready" || itemStatus === "partial";
              return (
                <div className={styles.stageRow} key={stage.id}>
                  <div className={styles.stageHeading}><span>{stage.label}</span><StatusBadge status={itemStatus} /></div>
                  <div className={styles.stageTrack} aria-hidden="true">
                    <span style={{ width: hasProgress ? `${clampPercent(stage.progress_percent)}%` : "0%" }} />
                  </div>
                  <div className={styles.stageMeta}>
                    <strong>{hasProgress ? `${stage.current}/${stage.target}` : stage.status}</strong>
                    <span>{hasProgress ? `${stage.progress_percent}%` : "no_data"}</span>
                    <small>{stage.next_action}</small>
                  </div>
                </div>
              );
            })}
            {!snapshot?.stages.length ? <div className={styles.noData}>stages: no_data</div> : null}
          </div>
        </ChartFrame>

        <ChartFrame
          title="证据覆盖"
          description="覆盖率只有在对应 scoped 来源权威存在时才显示；否则不把服务端占位零解释为 0%。"
          status={coverageFrameStatus}
          table={(
            <DataTable
              caption="证据覆盖数据表"
              rowHeaderKey="label"
              columns={[
                { key: "label", label: "覆盖项" },
                { key: "status", label: "数据状态" },
                { key: "value", label: "当前/目标" },
                { key: "percent", label: "覆盖率" },
              ]}
              rows={coverageRows.map((item) => ({
                label: item.label,
                status: item.truthStatus,
                value: item.truthStatus === "ready" ? `${item.current}/${item.target} ${item.unit}` : "no_data",
                percent: item.truthStatus === "ready" ? `${item.percent}%` : "no_data",
              }))}
            />
          )}
        >
          {coverageChartRows.length ? (
            <div className={styles.coverageChart} role="img" aria-label="已通过领域权威的证据覆盖率横向图">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={coverageChartRows}
                  layout="vertical"
                  margin={{ top: 8, right: 34, left: 8, bottom: 8 }}
                  accessibilityLayer
                >
                  <CartesianGrid horizontal={false} stroke="var(--kjds-border-default)" strokeDasharray="3 3" />
                  <XAxis type="number" domain={[0, 100]} tickFormatter={(value) => `${value}%`} stroke="var(--kjds-text-muted)" fontSize={10} />
                  <YAxis type="category" dataKey="label" width={78} stroke="var(--kjds-text-secondary)" fontSize={11} />
                  <Tooltip formatter={(value) => [`${value}%`, "覆盖率"]} />
                  <Bar dataKey="value" fill="var(--kjds-color-accent-600)" radius={[0, 6, 6, 0]}>
                    <LabelList dataKey="value" position="right" formatter={(value) => `${value}%`} fill="var(--kjds-text-primary)" fontSize={11} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <p>仅绘制已通过当前作用域领域权威的数据；未准入项继续在下方标记为 no_data。</p>
            </div>
          ) : null}
          <div className={styles.coverageList}>
            {coverageRows.map((item) => (
              <div className={styles.coverageRow} key={item.id}>
                <div>
                  <span>{item.label}</span>
                  <StatusBadge status={item.truthStatus} />
                  <strong>{item.truthStatus === "ready" ? `${item.percent}%` : "no_data"}</strong>
                </div>
                <div className={styles.coverageTrack} aria-hidden="true">
                  <span style={{ width: item.truthStatus === "ready" ? `${clampPercent(item.percent)}%` : "0%" }} />
                </div>
                <small>{item.truthStatus === "ready" ? `${item.current}/${item.target} ${item.unit}` : "来源权威尚未接入当前 Scope"}</small>
              </div>
            ))}
            {!coverageRows.length ? <div className={styles.noData}>coverage: no_data</div> : null}
          </div>
        </ChartFrame>
      </div>

      <div className={ui2.chartGrid}>
        <ChartFrame
          title="经营漏斗"
          description="每个节点独立检查来源权威；不同阶段不会被拼成虚假转化率。"
          status={pipelineFrameStatus}
          table={(
            <DataTable
              caption="经营漏斗数据表"
              rowHeaderKey="label"
              columns={[
                { key: "label", label: "节点" },
                { key: "status", label: "数据状态" },
                { key: "value", label: "数量" },
                { key: "unit", label: "单位" },
              ]}
              rows={pipelineRows.map((item) => ({
                label: item.label,
                status: item.truthStatus,
                value: item.truthStatus === "ready" ? item.value : "no_data",
                unit: item.truthStatus === "ready" ? item.unit : "—",
              }))}
            />
          )}
        >
          <div className={styles.funnelList}>
            {pipelineRows.map((item) => (
              <div className={styles.funnelItem} key={item.id}>
                <span>{item.label}</span>
                <StatusBadge status={item.truthStatus} />
                <strong>{item.truthStatus === "ready" ? item.value : "no_data"}</strong>
                <small>{item.truthStatus === "ready" ? item.unit : "来源未接入"}</small>
              </div>
            ))}
            {!pipelineRows.length ? <div className={styles.noData}>pipeline: no_data</div> : null}
          </div>
        </ChartFrame>

        <ChartFrame
          title="当前建议剧本"
          description="只读建议，不自动切换模式，也不获得平台写权限。"
          status={stageFrameStatus}
        >
          {snapshot?.recommended_playbook ? (
            <div className={styles.playbook}>
              <StatusBadge status={stageFrameStatus} />
              <h3>{snapshot.recommended_playbook.label}</h3>
              <ul>{snapshot.recommended_playbook.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
              <span>advisory_only=true · automatic_mode_switch=false</span>
            </div>
          ) : <div className={styles.noData}>recommended_playbook: no_data</div>}
        </ChartFrame>
      </div>

      <section className={styles.prioritySection} aria-labelledby="priority-title">
        <div className={styles.sectionHeader}>
          <div><p className={ui2.eyebrow}>Decision queue</p><h2 id="priority-title">优先工作项</h2></div>
          <span className={styles.sectionHint}>保持服务端顺序、Owner、风险、下一动作和当前投影返回的 Evidence</span>
        </div>
        <div className={styles.queueToolbar} role="search" aria-label="优先工作项筛选">
          <label>
            <span>搜索事项</span>
            <input
              type="search"
              value={queueQuery}
              onChange={(event) => setQueueQuery(event.target.value)}
              placeholder="标题、Owner、下一动作…"
              aria-label="搜索优先工作项"
            />
          </label>
          <label>
            <span>风险</span>
            <select value={queueRisk} onChange={(event) => setQueueRisk(event.target.value)} aria-label="按风险筛选">
              <option value="all">全部风险</option>
              {queueRisks.map((risk) => <option value={risk} key={risk}>{risk}</option>)}
            </select>
          </label>
          <label>
            <span>状态</span>
            <select value={queueStatus} onChange={(event) => setQueueStatus(event.target.value)} aria-label="按状态筛选">
              <option value="all">全部状态</option>
              {queueStatuses.map((itemStatus) => <option value={itemStatus} key={itemStatus}>{itemStatus}</option>)}
            </select>
          </label>
          <button
            type="button"
            className={styles.clearQueueFilters}
            onClick={() => { setQueueQuery(""); setQueueRisk("all"); setQueueStatus("all"); }}
            disabled={!queueFilterActive}
          >
            清除筛选
          </button>
        </div>
        <p className={styles.queueSummary} role="status" aria-live="polite" aria-atomic="true">
          {queueFilterActive
            ? `本地筛选匹配 ${filteredPriorityItems.length} 项 · 表格展示 ${Math.min(filteredPriorityItems.length, queueDisplayLimit)} 项`
            : `当前作用域返回 ${priorityItems.length} 项 · 表格展示前 ${Math.min(priorityItems.length, queueDisplayLimit)} 项`}
          <span> · 不改变服务端优先级或数据口径</span>
        </p>
        <DataTable
          caption="优先工作项数据表"
          rowHeaderKey="title"
          columns={[
            { key: "title", label: "事项" },
            { key: "status", label: "状态" },
            { key: "owner", label: "责任 Agent" },
            { key: "risk", label: "风险" },
            { key: "next", label: "下一动作" },
            { key: "evidence", label: "Evidence" },
          ]}
          rows={filteredPriorityItems.slice(0, queueDisplayLimit).map((item) => ({
            title: item.title,
            status: item.status,
            owner: item.agent_name,
            risk: item.risk,
            next: item.next_action,
            evidence: item.evidence_ids.length
              ? <EvidenceButtons ids={item.evidence_ids} onOpen={setEvidenceId} />
              : "no_data",
          }))}
        />
        {!priorityItems.length ? <p className={styles.queueEmpty}><StatusBadge status={briefingFrameStatus} /> 当前作用域没有可展示工作项，不从 legacy 全局队列补值。</p> : null}
        {priorityItems.length > 0 && !filteredPriorityItems.length ? <p className={styles.queueEmpty}><StatusBadge status="no_data" /> 当前筛选没有匹配项；清除筛选后恢复服务端原始顺序。</p> : null}
      </section>

      {dataGaps.length || excludedSources.length ? (
        <section className={styles.dataGapPanel} aria-labelledby="gap-title">
          <h2 id="gap-title">数据缺口与排除来源</h2>
          <p>这些边界会影响分析结论；没有真实历史序列时不绘制趋势、不计算同比。</p>
          {dataGaps.length ? <ul>{dataGaps.map((gap) => <li key={gap}>{gap}</li>)}</ul> : null}
          {excludedSources.length ? <p className={styles.excludedSources}>明确排除：{excludedSources.join(" · ")}</p> : null}
        </section>
      ) : null}

      {snapshot?.focal_listing && hasAdmittedCatalog(snapshot) ? (
        <section className={styles.focalCard} aria-labelledby="focal-title">
          <div>
            <p className={ui2.eyebrow}>Focal listing</p>
            <h2 id="focal-title">{snapshot.focal_listing.name}</h2>
            <p>{snapshot.focal_listing.offer_id} · {snapshot.focal_listing.status_name ?? snapshot.focal_listing.status ?? "no_data"}</p>
          </div>
          <div className={styles.focalMetrics}>
            <span><b>库存</b>{snapshot.focal_listing.available_stock ?? "no_data"}</span>
            <span><b>媒体权利</b>{snapshot.focal_listing.media_rights_status}</span>
            <span><b>完整利润场景</b>{snapshot.focal_listing.complete_profit_scenario_count}</span>
          </div>
          <button type="button" onClick={() => setEvidenceId(snapshot.focal_listing?.source_evidence_id ?? null)}>
            回看原始 Evidence
          </button>
        </section>
      ) : null}

      <EvidenceDrawer
        evidenceId={evidenceId}
        snapshotHash={snapshotHash}
        open={Boolean(evidenceId)}
        onClose={() => setEvidenceId(null)}
      />
    </AppShell>
  );
}

type DecisionItem = OperatingWorkbenchBriefing["work_items"][number];

function DecisionSpine({
  status,
  asOf,
  gapCount,
  snapshotHash,
  item,
  onEvidence,
}: {
  status: DataStatus;
  asOf: string | null;
  gapCount: number;
  snapshotHash: string | null;
  item: DecisionItem | null;
  onEvidence: (evidenceId: string) => void;
}) {
  const conclusion = decisionConclusion(status);
  const evidenceId = item?.evidence_ids[0] ?? null;
  return (
    <section className={styles.decisionSpine} aria-labelledby="decision-spine-title">
      <header className={styles.decisionSpineHeader}>
        <div>
          <p className={ui2.eyebrow}>Decision spine</p>
          <h2 id="decision-spine-title">从结论到动作</h2>
          <p>把当前作用域的判断、证据边界和第一责任动作放在同一条阅读路径里。</p>
        </div>
        <StatusBadge status={status} />
      </header>
      <ol className={styles.decisionSteps}>
        <li className={styles.decisionStep}>
          <span className={styles.decisionIcon} aria-hidden="true"><ScanSearch size={17} /></span>
          <div><small>01 · 结论</small><strong>{conclusion}</strong><span>{asOf ? `数据截止 ${formatDateValue(asOf)}` : "数据时点 no_data"}</span></div>
        </li>
        <li className={styles.decisionStep}>
          <span className={styles.decisionIcon} aria-hidden="true"><FileCheck2 size={17} /></span>
          <div><small>02 · 证据边界</small><strong>{gapCount ? `${gapCount} 项需要补证` : "当前未报告缺口"}</strong><span>snapshot {shortId(snapshotHash)}</span></div>
        </li>
        <li className={styles.decisionStep}>
          <span className={styles.decisionIcon} aria-hidden="true"><ListChecks size={17} /></span>
          <div><small>03 · 下一动作</small><strong>{item?.next_action ?? "没有可执行的 scoped 工作项"}</strong><span>{item ? `服务端优先级 ${item.priority}` : "不从 legacy 队列补值"}</span></div>
        </li>
        <li className={styles.decisionStep}>
          <span className={styles.decisionIcon} aria-hidden="true"><CircleAlert size={17} /></span>
          <div><small>04 · 责任与复核</small><strong>{item?.agent_name ?? "需要人工确认责任人"}</strong><span>{item?.human_required ? "human review required" : "责任与 Evidence no_data"}</span>{evidenceId ? <button type="button" className={styles.decisionEvidence} onClick={() => onEvidence(evidenceId)}>回看首项 Evidence <ArrowRight size={13} aria-hidden="true" /></button> : null}</div>
        </li>
      </ol>
    </section>
  );
}

function EvidenceButtons({ ids, onOpen }: { ids: string[]; onOpen: (id: string) => void }) {
  return (
    <span className={styles.evidenceButtons}>
      {ids.slice(0, 3).map((id) => (
        <button type="button" onClick={() => onOpen(id)} key={id}>查看 {shortId(id)}</button>
      ))}
      {ids.length > 3 ? <small>另 {ids.length - 3} 项</small> : null}
    </span>
  );
}

function collectionStatus(statuses: DataStatus[], fallback: DataStatus): DataStatus {
  if (!statuses.length) return fallback;
  const admitted = statuses.filter((item) => item === "ready").length;
  if (admitted === statuses.length) return "ready";
  if (admitted > 0) return "partial";
  if (statuses.includes("blocked")) return "blocked";
  if (statuses.includes("forbidden")) return "forbidden";
  return "no_data";
}

function stageStatus(value: OperatingAnalyticsSnapshot["stages"][number]["status"]): DataStatus {
  if (value === "verified") return "ready";
  if (value === "in_progress") return "partial";
  return value;
}

function stateExplanation(status: DataStatus) {
  if (status === "forbidden") return "当前 URL 请求的店铺不在身份授权集合内；页面没有发送经营数据请求。";
  if (status === "conflicted") return "响应合同或 tenant/store Scope 与当前会话不一致；数字已经失败关闭。";
  if (status === "blocked") return "查询参数或服务端权威门阻断本轮分析；不会回退到当前或全局快照。";
  return "当前作用域没有足够的真实经营数据；服务端占位零不会被解释为业务零值。";
}

function decisionConclusion(status: DataStatus) {
  if (status === "ready") return "作用域投影可复核";
  if (status === "partial") return "部分真源可用";
  if (status === "loading") return "正在固定本轮 Scope";
  if (status === "forbidden") return "身份无权读取该店铺";
  if (status === "blocked") return "服务端权威门阻断";
  if (status === "conflicted") return "响应合同发生冲突";
  if (status === "error") return "经营投影读取失败";
  return "真实数据不足，保持 no_data";
}

function buildScopedQuery(storeRef: string, asOf: string | null) {
  const params = new URLSearchParams();
  if (storeRef) params.set("store_ref", storeRef);
  if (asOf) params.set("as_of", asOf);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function uniqueStrings(...groups: string[][]) {
  return Array.from(new Set(groups.flat().filter(Boolean)));
}

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

function shortId(value: string | null) {
  if (!value) return "no_data";
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function formatDateValue(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
