"use client";

import {
  AlertTriangle,
  ArrowLeft,
  BadgeCheck,
  BarChart3,
  Boxes,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Database,
  FileCheck2,
  Fingerprint,
  Image as ImageIcon,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  UserRound,
  Video,
  WalletCards,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { WebSession } from "../dashboard/contracts";
import { fetchJson, settleJsonRequests } from "../../lib/fetch-json";
import type {
  LedgerRow,
  MediaSnapshot,
  MetricRegistry,
  OperatingTask,
  ProfitErosion,
  ProfitLedger,
  TaskEvent,
} from "./contracts";
import styles from "./operating-intelligence.module.css";

const statusLabels: Record<string, string> = {
  no_data: "NO DATA",
  blocked: "BLOCKED",
  partial: "PARTIAL",
  reconciled: "RECONCILED",
  ready: "READY",
  open: "OPEN",
  acknowledged: "ACKNOWLEDGED",
  in_progress: "IN PROGRESS",
  resolved: "RESOLVED",
  dismissed: "DISMISSED",
  failed: "FAILED",
  generated: "GENERATED",
  approved: "APPROVED",
  queued: "QUEUED",
  claimed: "CLAIMED",
};

const erosionLabels: Record<string, string> = {
  purchase: "采购",
  logistics: "物流",
  warehousing: "仓储 / 库龄",
  commission: "佣金",
  advertising: "广告",
  returns: "退货退款",
  discount: "折扣",
  tax: "税费",
  fx: "FX",
  loss: "损耗",
  unallocated: "未分摊",
};

function money(value: string | null | undefined, currency = "CNY") {
  if (value === null || value === undefined) return "证据不足";
  const number = Number(value);
  return Number.isFinite(number)
    ? `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(number)} ${currency}`
    : `${value} ${currency}`;
}

function shortHash(value?: string | null) {
  return value ? `${value.slice(0, 8)}…${value.slice(-8)}` : "—";
}

function Status({ value }: { value: string }) {
  return <span className={`${styles.status} ${styles[value] ?? ""}`}>{statusLabels[value] ?? value}</span>;
}

function EmptyTruth({ title, detail }: { title: string; detail: string }) {
  return (
    <div className={styles.empty}>
      <CircleDashed size={24} />
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

function Trend({ rows }: { rows: LedgerRow[] }) {
  const points = useMemo(() => {
    const values = rows.map((row) => Number(row.actual_profit ?? row.accrual_contribution));
    if (!values.length || values.some((value) => !Number.isFinite(value))) return [];
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    return values.map((value, index) => ({
      x: rows.length === 1 ? 50 : 5 + (index / (rows.length - 1)) * 90,
      y: 86 - ((value - min) / range) * 68,
      value,
      label: rows[index].accounting_date,
    }));
  }, [rows]);

  if (!points.length) {
    return <EmptyTruth title="没有可绘制利润趋势" detail="服务端没有返回具备明确订单绑定的贡献数据。" />;
  }
  return (
    <div className={styles.trend}>
      <svg viewBox="0 0 100 100" role="img" aria-label="服务端实际利润趋势">
        <line x1="5" y1="86" x2="95" y2="86" />
        <line x1="5" y1="18" x2="5" y2="86" />
        {points.length > 1 ? (
          <polyline points={points.map((point) => `${point.x},${point.y}`).join(" ")} />
        ) : null}
        {points.map((point) => <circle key={`${point.label}-${point.x}`} cx={point.x} cy={point.y} r="2.4" />)}
      </svg>
      <footer>
        <span>{points[0].label}</span>
        <b>{money(String(points[points.length - 1]?.value ?? 0))}</b>
        <span>{points[points.length - 1]?.label}</span>
      </footer>
    </div>
  );
}

export function OperatingIntelligence() {
  const [session, setSession] = useState<WebSession | null>(null);
  const [ledger, setLedger] = useState<ProfitLedger | null>(null);
  const [erosion, setErosion] = useState<ProfitErosion | null>(null);
  const [registry, setRegistry] = useState<MetricRegistry | null>(null);
  const [tasks, setTasks] = useState<OperatingTask[]>([]);
  const [media, setMedia] = useState<MediaSnapshot | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [selectedTask, setSelectedTask] = useState("");
  const [busy, setBusy] = useState(true);
  const [actionBusy, setActionBusy] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [taskReason, setTaskReason] = useState("");
  const [taskEvidence, setTaskEvidence] = useState("");
  const [error, setError] = useState("");

  const loadEvents = useCallback(async (taskId: string, signal?: AbortSignal) => {
    setSelectedTask(taskId);
    if (!taskId) return setEvents([]);
    const response = await fetchJson<TaskEvent[]>(`/backend/v1/operating-tasks/${encodeURIComponent(taskId)}/events`, {
      cache: "no-store",
      signal,
    });
    setEvents(response.ok ? await response.json() : []);
  }, []);

  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy(true);
    setError("");
    const sessionResponse = await fetchJson<WebSession | { detail?: string }>("/auth/session", {
      cache: "no-store",
      signal,
    });
    if (sessionResponse.status === 401) return window.location.assign("/login");
    if (sessionResponse.status === 428) return window.location.assign("/mfa");
    const sessionBody = await sessionResponse.json();
    if (!sessionResponse.ok) {
      setError("身份服务不可用，未读取任何经营数据");
      return setBusy(false);
    }
    setSession(sessionBody as WebSession);

    const responses = await settleJsonRequests([
      fetchJson<ProfitLedger>("/backend/v1/profit-ledger?store_ref=ozon-primary&grain=order", { cache: "no-store", signal }),
      fetchJson<ProfitErosion>("/backend/v1/profit-ledger/erosion?store_ref=ozon-primary&grain=order", { cache: "no-store", signal }),
      fetchJson<MetricRegistry>("/backend/v1/operating-intelligence/metrics", { cache: "no-store", signal }),
      fetchJson<OperatingTask[]>("/backend/v1/operating-tasks?limit=100", { cache: "no-store", signal }),
      fetchJson<MediaSnapshot>("/backend/v1/media/workbench", { cache: "no-store", signal }),
    ]);
    const bodies = await Promise.all(responses.map((response) => response.json()));
    setLedger(responses[0].ok ? bodies[0] as ProfitLedger : null);
    setErosion(responses[1].ok ? bodies[1] as ProfitErosion : null);
    setRegistry(responses[2].ok ? bodies[2] as MetricRegistry : null);
    const nextTasks = responses[3].ok ? bodies[3] as OperatingTask[] : [];
    setTasks(nextTasks);
    setMedia(responses[4].ok ? bodies[4] as MediaSnapshot : null);
    const failures = responses.filter((response) => !response.ok).length;
    if (failures) setError(`${failures} 个服务端快照不可用；对应区域保持 blocked，不生成替代数据。`);
    const taskId = nextTasks[0]?.id ?? "";
    await loadEvents(taskId, signal);
    setBusy(false);
  }, [loadEvents]);

  const runScan = useCallback(async () => {
    setActionBusy("scan");
    setActionNotice("");
    try {
      const response = await fetchJson("/backend/v1/operating-intelligence/anomaly-scans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ store_ref: "ozon-primary" }),
      });
      const body = await response.json();
      setActionNotice(response.ok
        ? `扫描 ${body.results?.length ?? 0} 项指标；未触发任何平台动作。`
        : body.detail ?? "异常扫描失败");
      if (response.ok) await load();
    } finally {
      setActionBusy("");
    }
  }, [load]);

  const transitionTask = useCallback(async (eventType: "acknowledge" | "start" | "resolve" | "dismiss") => {
    if (!selectedTask || !taskReason.trim()) {
      setActionNotice("任务事件必须填写处理理由。");
      return;
    }
    const evidenceIds = taskEvidence.split(",").map((item) => item.trim()).filter(Boolean);
    if ((eventType === "resolve" || eventType === "dismiss") && !evidenceIds.length) {
      setActionNotice("完成或驳回任务必须绑定至少一条不可变 Evidence。");
      return;
    }
    setActionBusy(`task:${selectedTask}`);
    try {
      const response = await fetchJson(`/backend/v1/operating-tasks/${encodeURIComponent(selectedTask)}/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_type: eventType, reason: taskReason.trim(), evidence_ids: evidenceIds }),
      });
      const body = await response.json();
      setActionNotice(response.ok ? `已追加 ${eventType} 不可变事件。` : body.detail ?? "任务事件提交失败");
      if (response.ok) {
        setTaskReason("");
        setTaskEvidence("");
        await load();
      }
    } finally {
      setActionBusy("");
    }
  }, [load, selectedTask, taskEvidence, taskReason]);

  const queueMedia = useCallback(async (assetId: string) => {
    const latest = media?.executions.find((item) => item.asset_id === assetId);
    const retry = latest?.status === "failed" || latest?.status === "blocked";
    setActionBusy(`media:${assetId}`);
    try {
      const response = await fetchJson(`/backend/v1/content/assets/${encodeURIComponent(assetId)}/execution`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idempotency_key: `operating-intelligence:${assetId}:${Date.now()}`,
          retry,
        }),
      });
      const body = await response.json();
      setActionNotice(response.ok ? `媒体执行已进入 ${body.status}。` : body.detail ?? "媒体执行排队失败");
      if (response.ok) await load();
    } finally {
      setActionBusy("");
    }
  }, [load, media?.executions]);

  const syncMedia = useCallback(async (assetId: string) => {
    setActionBusy(`media:${assetId}`);
    try {
      const response = await fetchJson(`/backend/v1/content/assets/${encodeURIComponent(assetId)}/execution/sync`, {
        method: "POST",
      });
      const body = await response.json();
      setActionNotice(response.ok ? `媒体执行状态已同步为 ${body.status}。` : body.detail ?? "媒体状态同步失败");
      if (response.ok) await load();
    } finally {
      setActionBusy("");
    }
  }, [load]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch(() => {
      if (!controller.signal.aborted) {
        setError("无法连接经营控制平面；页面未生成任何演示数据。");
        setBusy(false);
      }
    });
    return () => controller.abort("operating intelligence unmounted");
  }, [load]);

  const maxErosion = Math.max(0, ...(erosion?.items.map((item) => Number(item.amount)) ?? []));
  const selected = tasks.find((task) => task.id === selectedTask) ?? null;

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/capability-atlas"><ArrowLeft size={15} />能力图谱</Link>
        <div className={styles.identity}>
          <span>{session?.email?.slice(0, 1).toUpperCase() ?? "K"}</span>
          <div><strong>{session?.email ?? "身份校验中"}</strong><small>{session?.roles?.join(" / ") ?? "server-owned identity"}</small></div>
        </div>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}><Sparkles size={14} />OPERATING INTELLIGENCE · READ ONLY BY DEFAULT</span>
          <h1>真实利润、异常任务与媒体产能</h1>
          <p>只呈现服务端明确绑定的订单、会计日期、币种、Evidence 与执行账。缺数据保持 no_data，未分摊保持 blocked。</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={busy}><RefreshCw size={15} />刷新真实快照</button>
        <nav>
          <a href="#profit">利润账</a>
          <a href="#anomalies">异常中心</a>
          <a href="#media">媒体工作台</a>
        </nav>
      </section>

      {error ? <div className={styles.notice}><AlertTriangle size={16} /><span>{error}</span></div> : null}
      {busy ? <div className={styles.loading}><RefreshCw size={22} />读取服务端事实、Evidence 与不可变事件…</div> : null}

      <section className={styles.workspace} id="profit">
        <header className={styles.sectionHead}>
          <div><span>01 · SKU / ORDER / ACCOUNTING DATE</span><h2>实际利润驾驶舱</h2><p>场景 CM3、应计贡献、结算贡献、到账贡献严格分层。</p></div>
          <Status value={ledger?.status ?? "no_data"} />
        </header>
        <div className={styles.kpis}>
          <article><span>利润覆盖率</span><strong>{ledger ? `${(Number(ledger.coverage_ratio) * 100).toFixed(1)}%` : "—"}</strong><small>完整证据腿 / 所需证据腿</small></article>
          <article><span>可对账订单</span><strong>{ledger?.rows.length ?? 0}</strong><small>仅明确自然键 / 绑定</small></article>
          <article><span>未分摊条目</span><strong>{ledger?.unallocated.length ?? 0}</strong><small>禁止按销售额猜分摊</small></article>
          <article><span>侵蚀守恒</span><strong>{erosion?.conserved ? "YES" : "—"}</strong><small>Δ {erosion?.conservation_delta ?? "—"}</small></article>
        </div>
        <div className={styles.profitGrid}>
          <article className={styles.panel}>
            <header><div><TrendingDown size={17} /><strong>贡献趋势</strong></div><small>ACTUAL / ACCRUAL · SERVER DATA</small></header>
            <Trend rows={ledger?.rows ?? []} />
          </article>
          <article className={styles.panel}>
            <header><div><BarChart3 size={17} /><strong>利润侵蚀桥</strong></div><small>{erosion?.conserved ? "STRICTLY CONSERVED" : "NOT RECONCILED"}</small></header>
            {erosion?.items.length ? <div className={styles.erosion}>
              {erosion.items.map((item) => <div key={item.category}>
                <span>{erosionLabels[item.category] ?? item.category}</span>
                <i><b style={{ width: `${maxErosion ? Math.max(2, Number(item.amount) / maxErosion * 100) : 0}%` }} /></i>
                <strong>{money(item.amount)}</strong>
              </div>)}
            </div> : <EmptyTruth title="没有侵蚀桥" detail="没有完整、显式归集的订单费用腿。" />}
          </article>
        </div>
        <article className={styles.tablePanel}>
          <header><div><Database size={17} /><strong>订单利润账</strong></div><code>{shortHash(ledger?.snapshot_sha256)}</code></header>
          {ledger?.rows.length ? <div className={styles.tableWrap}><table>
            <thead><tr><th>SKU / 订单</th><th>会计日期</th><th>场景 CM3</th><th>应计</th><th>结算</th><th>到账</th><th>实际利润</th><th>Evidence</th></tr></thead>
            <tbody>{ledger.rows.map((row) => <tr key={row.order_id}>
              <td><strong>{row.sku ?? "UNMAPPED"}</strong><small>{row.order_id}</small></td>
              <td>{row.accounting_date}</td><td>{money(row.scenario_cm3, row.currency)}</td>
              <td>{money(row.accrual_contribution, row.currency)}</td><td>{money(row.settlement_contribution, row.currency)}</td>
              <td>{money(row.cash_contribution, row.currency)}</td><td><b>{money(row.actual_profit, row.currency)}</b></td>
              <td><span className={styles.evidence}>{row.evidence_ids.length} refs</span>{row.blockers.map((item) => <small className={styles.blocker} key={item}>{item}</small>)}</td>
            </tr>)}</tbody>
          </table></div> : <EmptyTruth title="实际利润不可显示" detail="尚无完整 Evidence 或明确 SKU / 订单绑定；系统不会把估算包装成实际利润。" />}
          {ledger?.unallocated.length ? <div className={styles.unallocated}><AlertTriangle size={16} /><div><strong>UNALLOCATED / BLOCKED</strong>{ledger.unallocated.map((item) => <p key={`${item.source_ref}-${item.amount}`}>{item.source_ref} · {money(item.amount, item.currency)} · {item.reason}</p>)}</div></div> : null}
        </article>
      </section>

      <section className={styles.workspace} id="anomalies">
        <header className={styles.sectionHead}>
          <div><span>02 · METRIC → ANOMALY → OPERATING TASK</span><h2>数据异常中心</h2><p>固定基线、最小样本、严重度、Owner、冷却期与稳定指纹。</p></div>
          <div className={styles.sectionActions}>
            <span className={styles.registry}>{registry?.registry_version ?? "registry unavailable"}</span>
            <button type="button" onClick={() => void runScan()} disabled={actionBusy === "scan"}>运行只读扫描</button>
          </div>
        </header>
        <div className={styles.metricGrid}>
          {registry?.metrics.map((metric) => <article key={metric.id} className={metric.data_status === "no_data" ? styles.mutedCard : ""}>
            <header><Status value={metric.data_status} /><span className={styles[metric.severity]}>{metric.severity}</span></header>
            <strong>{metric.label}</strong>
            <b>{metric.data_status === "ready" ? `${metric.observation.value} ${metric.unit}` : "样本不足"}</b>
            <dl><div><dt>基线</dt><dd>{metric.baseline}</dd></div><div><dt>阈值</dt><dd>{metric.operator} {metric.threshold}</dd></div><div><dt>样本</dt><dd>{metric.observation.sample_size} / {metric.minimum_sample}</dd></div><div><dt>Owner</dt><dd>{metric.owner}</dd></div></dl>
            <footer><Clock3 size={12} />冷却 {metric.cooldown_minutes}m <FileCheck2 size={12} />{metric.evidence_required ? "Evidence required" : "internal fact"}</footer>
          </article>) ?? <EmptyTruth title="指标注册表不可用" detail="客户端不会自定义阈值或伪造异常。" />}
        </div>
        <div className={styles.taskGrid}>
          <article className={styles.taskList}>
            <header><div><Boxes size={17} /><strong>Operating Tasks</strong></div><span>{tasks.length}</span></header>
            {tasks.length ? tasks.map((task) => <button type="button" key={task.id} className={selectedTask === task.id ? styles.selected : ""} onClick={() => void loadEvents(task.id)}>
              <span className={styles[task.severity]}>{task.severity}</span><div><strong>{task.title}</strong><small>{task.metric_id} · {task.owner}</small></div><Status value={task.status} />
            </button>) : <EmptyTruth title="没有内部运营任务" detail="异常扫描未产生满足最小样本的异常，或尚未运行扫描。" />}
          </article>
          <article className={styles.timeline}>
            <header><div><Fingerprint size={17} /><strong>不可变处理记录</strong></div><code>{selected ? shortHash(selected.id) : "—"}</code></header>
            {selected ? <div className={styles.taskMeta}><span><UserRound size={13} />{selected.owner}</span><span><Clock3 size={13} />cooldown {new Date(selected.cooldown_until).toLocaleString("zh-CN")}</span><span><ShieldCheck size={13} />零平台副作用</span></div> : null}
            {selected && !["resolved", "dismissed"].includes(selected.status) ? <div className={styles.taskAction}>
              <input value={taskReason} onChange={(event) => setTaskReason(event.target.value)} placeholder="处理理由（必填）" />
              <input value={taskEvidence} onChange={(event) => setTaskEvidence(event.target.value)} placeholder="Evidence IDs，逗号分隔（终态必填）" />
              <div>
                {selected.status === "open" ? <button type="button" onClick={() => void transitionTask("acknowledge")} disabled={actionBusy.startsWith("task:")}>确认</button> : null}
                {selected.status === "acknowledged" ? <button type="button" onClick={() => void transitionTask("start")} disabled={actionBusy.startsWith("task:")}>开始处理</button> : null}
                {selected.status === "in_progress" ? <>
                  <button type="button" onClick={() => void transitionTask("resolve")} disabled={actionBusy.startsWith("task:")}>Evidence 结案</button>
                  <button type="button" onClick={() => void transitionTask("dismiss")} disabled={actionBusy.startsWith("task:")}>Evidence 驳回</button>
                </> : null}
              </div>
            </div> : null}
            {events.length ? <ol>{events.map((event) => <li key={event.id}><i>{event.sequence}</i><div><strong>{event.event_type} · {event.from_status} → {event.to_status}</strong><p>{event.reason}</p><small>{event.actor_id} · {new Date(event.occurred_at).toLocaleString("zh-CN")} · Evidence {event.evidence_ids.length}</small></div></li>)}</ol> : <EmptyTruth title="尚无处理事件" detail="选择任务后读取不可变事件时间线。" />}
          </article>
        </div>
      </section>

      {actionNotice ? <div className={styles.actionNotice}>{actionNotice}</div> : null}
      <section className={styles.workspace} id="media">
        <header className={styles.sectionHead}>
          <div><span>03 · CONTROLLED IMAGE / FIXED FFMPEG VIDEO</span><h2>媒体运营工作台</h2><p>受控模板、权利 Evidence、批量部分失败、租约恢复、QA、成本与 Manifest。</p></div>
          <Status value={media?.status ?? "no_data"} />
        </header>
        <div className={styles.mediaSummary}>
          <article><ImageIcon size={18} /><div><span>资产 / 执行</span><strong>{media?.summary.asset_count ?? 0} / {media?.summary.execution_count ?? 0}</strong></div></article>
          <article><AlertTriangle size={18} /><div><span>失败 / 阻断</span><strong>{media?.summary.failed_count ?? 0} / {media?.summary.blocked_count ?? 0}</strong></div></article>
          <article><FileCheck2 size={18} /><div><span>Delivery Manifest</span><strong>{media?.summary.manifest_count ?? 0}</strong></div></article>
          <article><LockKeyhole size={18} /><div><span>外部视频 Provider</span><strong>OFF</strong></div></article>
        </div>
        <div className={styles.mediaGrid}>
          <article className={styles.templatePanel}>
            <header><div><Sparkles size={17} /><strong>受控模板目录</strong></div><small>FIXED VERSION</small></header>
            {media?.templates.map((template) => <div key={template.id}>
              {template.kind === "video" ? <Video size={17} /> : <ImageIcon size={17} />}
              <span><strong>{template.id}</strong><small>{template.executor} · v{template.version}</small></span>
              <Status value={template.status} />
            </div>)}
          </article>
          <article className={styles.executionPanel}>
            <header><div><WalletCards size={17} /><strong>批量 / 执行账</strong></div><small>POSTGRES LEASE</small></header>
            {media?.executions.length ? media.executions.map((execution) => <div key={execution.id}>
              <span className={styles.mediaIcon}>{execution.media_kind === "video" ? <Video size={16} /> : <ImageIcon size={16} />}</span>
              <div><strong>{execution.asset_id}</strong><small>{execution.template_id} · attempt {execution.attempt}</small><code>input {shortHash(execution.input_sha256)}</code></div>
              <div className={styles.executionFacts}><Status value={execution.status} /><b>{money(execution.cost.amount, execution.cost.currency)}</b><small>{execution.latency_ms === null ? "latency pending" : `${execution.latency_ms} ms`}</small></div>
            </div>) : <EmptyTruth title="没有媒体执行账" detail="工作台没有排队、失败或完成的真实执行。" />}
          </article>
        </div>
        <div className={styles.deliveryGrid}>
          <article><header><div><BadgeCheck size={17} /><strong>QA 与 Listing 资格</strong></div></header>
            {media?.assets.length ? media.assets.map((asset) => {
              const latest = media.executions.find((item) => item.asset_id === asset.id);
              return <div key={asset.id}><span><strong>{asset.id}</strong><small>{asset.content_type} · QA {asset.qa_results.length}</small></span><Status value={asset.status} />
                <span className={styles.assetActions}>
                  <button type="button" onClick={() => void queueMedia(asset.id)} disabled={actionBusy === `media:${asset.id}`}>{latest && ["failed", "blocked"].includes(latest.status) ? "重试" : "执行"}</button>
                  {latest ? <button type="button" onClick={() => void syncMedia(asset.id)} disabled={actionBusy === `media:${asset.id}`}>同步</button> : null}
                </span>
              </div>;
            }) : <EmptyTruth title="没有媒体资产" detail="尚无真实 ContentAsset；工作台不会生成演示素材。" />}
          </article>
          <article><header><div><FileCheck2 size={17} /><strong>交付 Manifest</strong></div></header>
            {media?.manifests.length ? media.manifests.map((manifest, index) => <div key={String(manifest.manifest_id ?? index)}><CheckCircle2 size={16} /><span><strong>{String(manifest.asset_id ?? "asset")}</strong><small>{String(manifest.template_id ?? "template")} · {shortHash(String(manifest.manifest_sha256 ?? ""))}</small></span></div>) : <EmptyTruth title="尚无可交付 Manifest" detail="只有全部 QA 通过的产物才能被 Listing 草稿引用。" />}
          </article>
        </div>
        <footer className={styles.controlFooter}><ShieldCheck size={16} /><span>ComfyUI 仅固定准入工作流；视频仅批准商品图 + 人工确认俄语脚本 / 字幕 + 有权利音频 + 固定 FFmpeg 链。</span><b>OZON WRITE: DENIED</b></footer>
      </section>
    </main>
  );
}
