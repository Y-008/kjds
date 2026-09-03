"use client";

import { useEffect, useMemo, useState } from "react";
import type { OperatingAnalyticsSnapshot } from "../dashboard/contracts";
import {
  ChartFrame,
  DataTable,
  EvidenceDrawer,
  MetricCard,
  ScopeBar,
  StatusBadge,
  WallboardFrame,
  type DataStatus,
} from "../ui2/ui2";
import ui2 from "../ui2/ui2.module.css";
import {
  projectionStatus,
  summaryMetricStatus,
  summaryMetricValue,
  type AnalyticsSummaryKey,
} from "./truth";
import { useBiProjection } from "./use-bi-projection";
import styles from "./wallboard.module.css";

type Scene = "summary" | "flow" | "exceptions";

const scenes: Scene[] = ["summary", "flow", "exceptions"];
const wallboardMetrics: Array<{ key: AnalyticsSummaryKey; label: string }> = [
  { key: "catalog_items", label: "目录商品" },
  { key: "bound_listings", label: "已绑定 Listing" },
  { key: "available_stock", label: "可用库存" },
  { key: "gate_blockers", label: "Gate 阻断" },
];

export function BiWallboard() {
  const {
    scope,
    snapshot,
    briefing,
    analytics,
    workbench,
    status,
    error,
    refresh,
  } = useBiProjection({ allowedUrlParams: ["scene"] });
  const [scene, setScene] = useState<Scene>("summary");
  const [sceneNotice, setSceneNotice] = useState("");
  const [paused, setPaused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);

  useEffect(() => {
    const syncScene = () => {
      const value = new URLSearchParams(window.location.search).get("scene");
      if (!value) {
        setScene("summary");
        setSceneNotice("");
        return;
      }
      if (isScene(value)) {
        setScene(value);
        setSceneNotice("");
        return;
      }
      setScene("summary");
      setSceneNotice(`未知大屏场景 ${value}；已保持经营摘要，不执行自动猜测。`);
    };
    syncScene();
    window.addEventListener("popstate", syncScene);
    return () => window.removeEventListener("popstate", syncScene);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const syncPreference = () => setReducedMotion(media.matches);
    syncPreference();
    media.addEventListener("change", syncPreference);
    return () => media.removeEventListener("change", syncPreference);
  }, []);

  useEffect(() => {
    if (paused || reducedMotion || status === "loading") return;
    const timer = window.setInterval(() => {
      setScene((current) => {
        const next = scenes[(scenes.indexOf(current) + 1) % scenes.length];
        writeSceneToUrl(next);
        return next;
      });
    }, 12_000);
    return () => window.clearInterval(timer);
  }, [paused, reducedMotion, status]);

  const changeScene = (next: Scene) => {
    setScene(next);
    setSceneNotice("");
    writeSceneToUrl(next);
  };
  const asOf = snapshot?.source_as_of ?? briefing?.as_of ?? null;
  const snapshotHash = snapshot?.snapshot_sha256 ?? briefing?.snapshot_sha256 ?? null;
  const priorityItems = briefing?.work_items ?? snapshot?.priority_items ?? [];
  const effectiveStatus = status;
  const flowStatus = snapshot ? projectionStatus(snapshot.status) : analytics.status;
  const exceptionStatus = briefing ? projectionStatus(briefing.status) : workbench.status;
  const metrics = useMemo(
    () => wallboardMetrics.map((definition) => ({
      ...definition,
      status: summaryMetricStatus(snapshot, definition.key, status),
      value: summaryMetricValue(snapshot, definition.key, status),
    })),
    [snapshot, status],
  );

  return (
    <WallboardFrame title="经营流转大屏" asOf={asOf} snapshotHash={snapshotHash} status={effectiveStatus}>
      <div className={styles.scopePanel}>
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
      </div>
      <div className={styles.sceneControls} role="group" aria-label="大屏场景切换">
        {scenes.map((value) => (
          <button type="button" key={value} aria-pressed={scene === value} onClick={() => changeScene(value)}>
            {sceneLabel(value)}
          </button>
        ))}
        <button type="button" onClick={() => setPaused((current) => !current)} disabled={reducedMotion}>
          {reducedMotion ? "系统已关闭轮播" : paused ? "恢复轮播" : "暂停轮播"}
        </button>
        <button type="button" onClick={refresh} disabled={status === "loading"}>刷新</button>
      </div>
      <div className={styles.sceneLive} role="status" aria-live="polite" aria-atomic="true">
        当前场景：{sceneLabel(scene)} · {reducedMotion
          ? "系统减少动态效果，自动轮播已关闭"
          : paused
            ? "手动控制"
            : "每 12 秒轮换"} · 店铺 {scope.storeRef || "no_data"} · 只读
      </div>
      {error || sceneNotice ? (
        <div className={styles.wallboardAlert} role="alert">{[error, sceneNotice].filter(Boolean).join("；")}</div>
      ) : null}

      {scene === "summary" ? (
        <section aria-labelledby="wallboard-summary-title" aria-busy={status === "loading"}>
          <h2 id="wallboard-summary-title" className={styles.visuallyHidden}>经营摘要</h2>
          <div className={ui2.metricGrid}>
            {metrics.map((metric) => (
              <MetricCard
                key={metric.key}
                label={metric.label}
                value={metric.value}
                status={metric.status}
                asOf={metric.status === "ready" ? asOf : null}
                definition="服务端 scoped OperatingAnalyticsSnapshot 汇总；来源缺失或无历史时保持 no_data。"
              />
            ))}
          </div>
        </section>
      ) : null}

      {scene === "flow" ? (
        <ChartFrame
          title="阶段与覆盖"
          description="固定时点展示当前/目标和服务端阶段状态，不生成趋势假值。"
          status={flowStatus}
          table={(
            <DataTable
              caption="大屏阶段数据表"
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
          <div className={styles.flowGrid}>
            {(snapshot?.stages ?? []).map((stage) => (
              <div key={stage.id} className={styles.flowCard}>
                <div><span>{stage.label}</span><StatusBadge status={wallboardStageStatus(stage.status)} /></div>
                <strong>{stage.status === "verified" || stage.status === "in_progress" ? `${stage.current}/${stage.target}` : stage.status}</strong>
                <small>{stage.next_action}</small>
              </div>
            ))}
            {!snapshot?.stages.length ? <div className={styles.wallboardNoData}>stages: no_data</div> : null}
          </div>
        </ChartFrame>
      ) : null}

      {scene === "exceptions" ? (
        <ChartFrame
          title="异常优先级"
          description="保持服务端 Briefing 顺序；异常置顶只改变展示，不关闭事故、释放 Gate 或执行动作。"
          status={exceptionStatus}
          table={(
            <DataTable
              caption="异常工作项数据表"
              rowHeaderKey="title"
              columns={[
                { key: "title", label: "事项" },
                { key: "owner", label: "Owner" },
                { key: "risk", label: "风险" },
                { key: "next", label: "下一动作" },
                { key: "evidence", label: "Evidence" },
              ]}
              rows={priorityItems.slice(0, 10).map((item) => ({
                title: item.title,
                owner: item.agent_name,
                risk: item.risk,
                next: item.next_action,
                evidence: item.evidence_ids.length ? (
                  <EvidenceAction evidenceId={item.evidence_ids[0]} onOpen={setEvidenceId} />
                ) : "no_data",
              }))}
            />
          )}
        >
          <div className={styles.exceptionList}>
            {priorityItems.slice(0, 6).map((item) => (
              <article key={item.id}>
                <div>
                  <StatusBadge status={item.priority === "critical" || item.risk === "high" ? "blocked" : "partial"} />
                  <h3>{item.title}</h3>
                </div>
                <p>{item.next_action}</p>
                <small>{item.agent_name} · {item.evidence_ids.length ? <EvidenceAction evidenceId={item.evidence_ids[0]} onOpen={setEvidenceId} /> : "Evidence: no_data"}</small>
              </article>
            ))}
            {!priorityItems.length ? <div className={styles.wallboardNoData}>priority_items: no_data</div> : null}
          </div>
        </ChartFrame>
      ) : null}

      <EvidenceDrawer
        evidenceId={evidenceId}
        snapshotHash={snapshotHash}
        open={Boolean(evidenceId)}
        onClose={() => setEvidenceId(null)}
      />
    </WallboardFrame>
  );
}

function sceneLabel(scene: Scene) {
  return scene === "summary" ? "经营摘要" : scene === "flow" ? "阶段覆盖" : "异常优先";
}

function isScene(value: string): value is Scene {
  return scenes.includes(value as Scene);
}

function writeSceneToUrl(scene: Scene) {
  const params = new URLSearchParams(window.location.search);
  params.set("scene", scene);
  window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
}

function wallboardStageStatus(value: OperatingAnalyticsSnapshot["stages"][number]["status"]): DataStatus {
  if (value === "verified") return "ready";
  if (value === "in_progress") return "partial";
  return value;
}

function EvidenceAction({ evidenceId, onOpen }: { evidenceId: string; onOpen: (id: string) => void }) {
  return (
    <button className={styles.evidenceAction} type="button" onClick={() => onOpen(evidenceId)}>
      查看 Evidence {shortEvidenceId(evidenceId)}
    </button>
  );
}

function shortEvidenceId(value: string) {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}
