"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";
import styles from "./ui2.module.css";

export type DataStatus =
  | "ready"
  | "no_data"
  | "blocked"
  | "partial"
  | "stale"
  | "conflicted"
  | "forbidden"
  | "loading"
  | "error";

const statusLabels: Record<DataStatus, string> = {
  ready: "READY",
  no_data: "NO DATA",
  blocked: "BLOCKED",
  partial: "PARTIAL",
  stale: "STALE",
  conflicted: "CONFLICTED",
  forbidden: "FORBIDDEN",
  loading: "LOADING",
  error: "ERROR",
};

const statusDescriptions: Record<DataStatus, string> = {
  ready: "服务端快照已返回",
  no_data: "没有足够的真实数据",
  blocked: "被服务端门禁阻断",
  partial: "仅部分来源可用",
  stale: "快照超过当前 freshness 窗口",
  conflicted: "来源之间存在冲突",
  forbidden: "当前身份无权查看",
  loading: "正在读取服务端快照",
  error: "读取服务端快照失败",
};

function statusClass(status: DataStatus) {
  return `${styles.status} ${styles[`status-${status}`] ?? ""}`;
}

export function StatusBadge({ status }: { status: DataStatus }) {
  return (
    <span className={statusClass(status)} title={statusDescriptions[status]}>
      <span aria-hidden="true" className={styles.statusDot} />
      {statusLabels[status]}
      <span className={styles.srOnly}>：{statusDescriptions[status]}</span>
    </span>
  );
}

export function AppShell({
  title,
  eyebrow,
  description,
  children,
  status = "loading",
  scope,
  asOf,
  snapshotHash,
  actions,
}: {
  title: string;
  eyebrow: string;
  description: string;
  children: ReactNode;
  status?: DataStatus;
  scope?: ReactNode;
  asOf?: string | null;
  snapshotHash?: string | null;
  actions?: ReactNode;
}) {
  return (
    <div className={styles.appShell}>
      <a className={styles.skipLink} href="#main-content">跳转到主内容</a>
      <header className={styles.appHeader}>
        <div className={styles.brandBlock}>
          <span className={styles.brandMark} aria-hidden="true">K</span>
          <div>
            <strong>KJDS</strong>
            <span>经营可视化产品层</span>
          </div>
        </div>
        <div className={styles.headerMeta}>
          <CommandMenu />
          <StatusBadge status={status} />
          <span className={styles.readOnlyChip}>只读分析 · 无平台写入</span>
        </div>
      </header>
      <main id="main-content" className={styles.appMain} tabIndex={-1}>
        <PageHeader eyebrow={eyebrow} title={title} description={description} actions={actions} />
        {scope ? <div className={styles.scopeBar}>{scope}</div> : null}
        <div className={styles.snapshotBar} aria-label="快照元数据">
          <span>数据截止：{asOf ? formatDate(asOf) : "no_data"}</span>
          <span>快照：{shortHash(snapshotHash)}</span>
          <span>口径：服务端版本化只读投影</span>
        </div>
        {children}
      </main>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className={styles.pageHeader}>
      <div>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h1>{title}</h1>
        <p className={styles.pageDescription}>{description}</p>
      </div>
      {actions ? <div className={styles.pageActions}>{actions}</div> : null}
    </div>
  );
}

const commandItems = [
  { href: "/bi/overview", label: "BI Overview", detail: "经营分析总览" },
  { href: "/bi/capabilities", label: "能力成熟度", detail: "合同、验证与生产 Gate" },
  { href: "/bi/journeys/current", label: "经营旅程", detail: "从信号到现金的只读时间线" },
  { href: "/bi/sources", label: "证据与来源", detail: "来源缺口、排除项与采集边界" },
  { href: "/bi/enterprise", label: "企业与作用域", detail: "Authority / Commercial / Operational" },
  { href: "/bi/product-value", label: "产品价值", detail: "Evidence-backed decision 遥测" },
  { href: "/bi/scenarios", label: "情景实验室", detail: "scenario_* 与实际账隔离" },
  { href: "/bi/agent-control", label: "Agent 控制塔", detail: "Agent 观察、人审与 guardrail" },
  { href: "/bi/reliability", label: "可靠性与降级", detail: "投影可信度与运行信号缺口" },
  { href: "/bi/wallboard", label: "经营流转大屏", detail: "固定时点、异常置顶" },
  { href: "/bi/briefing", label: "经营简报", detail: "四页手动翻页与证据回看" },
  { href: "/profit-command", label: "利润指挥", detail: "利润口径、真相门禁与血缘" },
  { href: "/operating-intelligence", label: "经营智能", detail: "指标、异常和媒体工作台" },
  { href: "/evidenceops", label: "EvidenceOps", detail: "证据与工作项入口" },
] as const;

export function CommandMenu() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const dialogContentId = useId();
  const commandItemsId = useId();
  const searchRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<Array<HTMLAnchorElement | null>>([]);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);
  const normalizedQuery = query.trim().toLowerCase();
  const items = commandItems.filter((item) => !normalizedQuery || `${item.label} ${item.detail}`.toLowerCase().includes(normalizedQuery));

  const focusItem = (index: number) => {
    const target = itemRefs.current[index];
    target?.focus();
  };

  const handleSearchKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (!items.length) return;
    if (event.key === "ArrowDown" || event.key === "Home") {
      event.preventDefault();
      focusItem(0);
    } else if (event.key === "ArrowUp" || event.key === "End") {
      event.preventDefault();
      focusItem(items.length - 1);
    }
  };

  const handleItemKeyDown = (event: ReactKeyboardEvent<HTMLAnchorElement>, index: number) => {
    if (!items.length) return;
    let nextIndex: number | null = null;
    if (event.key === "ArrowDown") nextIndex = (index + 1) % items.length;
    if (event.key === "ArrowUp") nextIndex = (index - 1 + items.length) % items.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = items.length - 1;
    if (nextIndex !== null) {
      event.preventDefault();
      focusItem(nextIndex);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          className={styles.commandTrigger}
          type="button"
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={dialogContentId}
        >
          跳转 <kbd>Ctrl K</kbd>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.commandBackdrop} />
        <Dialog.Content
          className={styles.commandMenu}
          id={dialogContentId}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            searchRef.current?.focus();
          }}
        >
          <header>
            <div>
              <p className={styles.eyebrow}>Command menu</p>
              <Dialog.Title className={styles.dialogTitle}>全局跳转</Dialog.Title>
            </div>
            <Dialog.Close asChild>
              <button className={styles.closeButton} type="button" aria-label="关闭全局跳转">×</button>
            </Dialog.Close>
          </header>
          <Dialog.Description className={styles.srOnly}>
            搜索并跳转到 KJDS 只读分析工作区。
          </Dialog.Description>
          <label className={styles.commandSearch}>
            <span>搜索工作区</span>
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="输入 BI、利润、证据…"
              aria-controls={commandItemsId}
              aria-describedby={`${commandItemsId}-status`}
            />
          </label>
          <p id={`${commandItemsId}-status`} className={styles.srOnly} role="status" aria-live="polite" aria-atomic="true">
            找到 {items.length} 个可跳转工作区
          </p>
          <div className={styles.commandItems} id={commandItemsId}>
            {items.map((item, index) => (
              <Link
                href={item.href}
                key={item.href}
                ref={(node) => { itemRefs.current[index] = node; }}
                onClick={() => setOpen(false)}
                onKeyDown={(event) => handleItemKeyDown(event, index)}
              >
                <strong>{item.label}</strong>
                <span>{item.detail}</span>
              </Link>
            ))}
            {!items.length ? <p className={styles.commandEmpty}>未找到可跳转工作区。</p> : null}
          </div>
          <footer>仅导航和只读问答入口；不会创建审批、Permit 或平台写入。</footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function useDialogReturnFocus(open: boolean) {
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const previousOpenRef = useRef(false);

  if (open && !previousOpenRef.current && typeof document !== "undefined") {
    const activeElement = document.activeElement;
    returnFocusRef.current = activeElement instanceof HTMLElement ? activeElement : null;
  }
  previousOpenRef.current = open;

  return (event: Event) => {
    event.preventDefault();
    const returnTarget = returnFocusRef.current;
    if (!returnTarget) return;
    window.requestAnimationFrame(() => {
      if (returnTarget.isConnected) returnTarget.focus();
    });
  };
}

export function ScopeBar({
  store = "no_data",
  period = "服务端当前快照",
  currency = "服务端口径",
  timezone = "Asia/Shanghai",
  stores,
  selectedStore,
  onStoreChange,
  disabled = false,
  tenant,
  asOf,
  sourceAsOf,
  scopeHash,
  scopeAuthorityHash,
}: {
  store?: string;
  period?: string;
  currency?: string;
  timezone?: string;
  stores?: readonly string[];
  selectedStore?: string;
  onStoreChange?: (store: string) => void;
  disabled?: boolean;
  tenant?: string | null;
  asOf?: string | null;
  sourceAsOf?: string | null;
  scopeHash?: string | null;
  scopeAuthorityHash?: string | null;
}) {
  const storeSelectId = useId();
  const storeSelectErrorId = useId();
  const hasStoreSelector = Boolean(stores?.length);
  const selectedStoreIsAuthorized = !selectedStore || Boolean(stores?.includes(selectedStore));
  const storeValue = selectedStore ?? stores?.[0] ?? store;
  const authorityHash = scopeAuthorityHash ?? scopeHash;
  return (
    <div className={styles.scopeItems} role="group" aria-label="分析作用域">
      {hasStoreSelector ? (
        <label className={styles.scopeSelect} htmlFor={storeSelectId}>
          <b>授权店铺</b>
          <select
            id={storeSelectId}
            value={storeValue}
            disabled={disabled || !onStoreChange}
            onChange={(event) => onStoreChange?.(event.target.value)}
            aria-invalid={!selectedStoreIsAuthorized}
            aria-describedby={!selectedStoreIsAuthorized ? storeSelectErrorId : undefined}
          >
            {!selectedStoreIsAuthorized && selectedStore ? <option value={selectedStore} disabled>{selectedStore}（未授权）</option> : null}
            {stores?.map((storeRef) => <option key={storeRef} value={storeRef}>{storeRef}</option>)}
          </select>
          {!selectedStoreIsAuthorized ? <em className={styles.scopeWarning} id={storeSelectErrorId}>当前值未授权，请显式选择授权店铺</em> : null}
        </label>
      ) : <span><b>店铺</b>{selectedStore ?? store}</span>}
      {tenant !== undefined ? <span><b>Tenant</b>{tenant || "no_data"}</span> : null}
      <span><b>查询截止</b>{asOf ? formatDate(asOf) : period}</span>
      {sourceAsOf !== undefined ? <span><b>数据时点</b>{sourceAsOf ? formatDate(sourceAsOf) : "no_data"}</span> : null}
      <span><b>币种</b>{currency}</span>
      <span><b>时区</b>{timezone}</span>
      {authorityHash !== undefined ? <span><b>Scope authority</b>{shortHash(authorityHash)}</span> : null}
    </div>
  );
}

export function MetricCard({
  label,
  value,
  unit,
  definition,
  status = "ready",
  changeAbs,
  changePct,
  targetGap,
  asOf,
  evidenceId,
  onEvidence,
}: {
  label: string;
  value: string | number;
  unit?: string;
  definition?: string;
  status?: DataStatus;
  changeAbs?: string | number | null;
  changePct?: string | number | null;
  targetGap?: string | number | null;
  asOf?: string | null;
  evidenceId?: string | null;
  onEvidence?: (evidenceId: string) => void;
}) {
  const valueIsNoData = value === "no_data" || value === "blocked" || value === "forbidden";
  return (
    <article className={`${styles.metricCard} ${styles[`metric-${status}`] ?? ""}`}>
      <div className={styles.metricTopline}>
        <span>{label}</span>
        <StatusBadge status={status} />
      </div>
      <div className={valueIsNoData ? styles.metricValueMuted : styles.metricValue}>
        {value}
        {unit && !valueIsNoData ? <small>{unit}</small> : null}
      </div>
      <p className={styles.metricDefinition}>{definition ?? "指标口径由服务端合同定义。"}</p>
      <dl className={styles.metricMeta}>
        <div><dt>变化</dt><dd>{changeAbs === null || changeAbs === undefined ? "no_data" : String(changeAbs)}{changePct === null || changePct === undefined ? "" : ` · ${changePct}`}</dd></div>
        <div><dt>目标差</dt><dd>{targetGap === null || targetGap === undefined ? "no_data" : String(targetGap)}</dd></div>
        <div><dt>时点</dt><dd>{asOf ? formatDate(asOf) : "no_data"}</dd></div>
      </dl>
      {evidenceId ? (
        <button className={styles.evidenceLink} type="button" onClick={() => onEvidence?.(evidenceId)}>
          查看 Evidence · {shortHash(evidenceId)}
        </button>
      ) : (
        <span className={styles.evidenceMissing}>Evidence 入口：由服务端快照提供</span>
      )}
    </article>
  );
}

export function ChartFrame({
  title,
  description,
  status = "ready",
  children,
  table,
}: {
  title: string;
  description?: string;
  status?: DataStatus;
  children: ReactNode;
  table?: ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  const titleId = useId();
  const contentId = useId();
  const isEmpty = status === "no_data"
    || status === "blocked"
    || status === "forbidden"
    || status === "conflicted"
    || status === "error"
    || status === "loading";
  useEffect(() => {
    if (isEmpty) setShowTable(false);
  }, [isEmpty]);
  return (
    <section className={styles.chartFrame} aria-labelledby={titleId}>
      <header className={styles.chartHeader}>
        <div>
          <div className={styles.chartTitleRow}>
            <h2 id={titleId}>{title}</h2>
            <StatusBadge status={status} />
          </div>
          {description ? <p>{description}</p> : null}
        </div>
        {table ? (
          <button
            className={styles.tableToggle}
            type="button"
            aria-pressed={showTable}
            aria-controls={contentId}
            disabled={isEmpty}
            title={isEmpty ? "当前没有可切换的数据表" : undefined}
            onClick={() => setShowTable((current) => !current)}
          >
            {showTable ? "返回图形" : "查看数据表"}
          </button>
        ) : null}
      </header>
      <div id={contentId}>
      {isEmpty ? (
        <div className={styles.chartEmpty} role="status">
          <strong>{statusLabels[status]}</strong>
          <p>{statusDescriptions[status]}；不生成演示趋势或插值。</p>
        </div>
      ) : showTable ? table : children}
      </div>
    </section>
  );
}

export function DataTable({
  caption,
  columns,
  rows,
  rowHeaderKey,
}: {
  caption: string;
  columns: Array<{ key: string; label: string }>;
  rows: Array<Record<string, ReactNode>>;
  rowHeaderKey?: string;
}) {
  const scrollInstructionId = useId();
  return (
    <div
      className={styles.tableWrap}
      role="region"
      aria-label={caption}
      aria-describedby={scrollInstructionId}
      tabIndex={0}
    >
      <span className={styles.srOnly} id={scrollInstructionId}>表格可在内容超出时横向滚动。</span>
      <table>
        <caption>{caption}</caption>
        <thead><tr>{columns.map((column) => <th scope="col" key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>
          {rows.length ? rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>{columns.map((column) => column.key === rowHeaderKey
              ? <th scope="row" key={column.key}>{row[column.key] ?? "—"}</th>
              : <td key={column.key}>{row[column.key] ?? "—"}</td>)}</tr>
          )) : <tr><td colSpan={columns.length}>no_data</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

type EvidenceMetadata = {
  id: string;
  sha256: string;
  byte_size: number;
  filename: string;
  content_type: string;
  source: string;
  source_ref: string;
  grade: string;
  effective_at: string;
  effective_until: string | null;
  recorded_at: string;
  created_by: string;
};

type EvidenceVerification = {
  evidence_id: string;
  expected_sha256: string;
  actual_sha256: string;
  byte_size: number;
  valid: boolean;
};

type EvidenceLineage = {
  id: string;
  from_type: string;
  from_id: string;
  to_type: string;
  to_id: string;
  relationship: string;
  created_by: string;
  recorded_at: string;
};

type EvidenceLoadState = {
  loading: boolean;
  metadata: EvidenceMetadata | null;
  verification: EvidenceVerification | null;
  lineage: EvidenceLineage[];
  error: string | null;
  partial: boolean;
  failureStatus: "forbidden" | "no_data" | "error" | null;
};

const emptyEvidenceState: EvidenceLoadState = {
  loading: false,
  metadata: null,
  verification: null,
  lineage: [],
  error: null,
  partial: false,
  failureStatus: null,
};

class EvidenceHttpError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`Evidence 服务返回 HTTP ${status}`);
    this.name = "EvidenceHttpError";
    this.status = status;
  }
}

async function readEvidenceJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) throw new EvidenceHttpError(response.status);
  return response.json() as Promise<T>;
}

function lineageResultIsSuccessful(
  result: PromiseSettledResult<EvidenceLineage[]>,
): result is PromiseFulfilledResult<EvidenceLineage[]> {
  return result.status === "fulfilled";
}

function evidenceFailureStatus(
  failures: PromiseRejectedResult[],
): "forbidden" | "no_data" | "error" {
  const statuses = failures.map((failure) => (
    failure.reason instanceof EvidenceHttpError ? failure.reason.status : 0
  ));
  if (statuses.includes(403)) return "forbidden";
  if (statuses.length > 0 && statuses.every((status) => status === 404)) return "no_data";
  return "error";
}

function evidenceFailureMessage(
  status: "forbidden" | "no_data" | "error",
  failures: PromiseRejectedResult[],
) {
  if (status === "forbidden") return "当前身份无权查看这条 Evidence。";
  if (status === "no_data") return "未找到这条 Evidence，未生成替代证据。";
  const first = failures[0]?.reason;
  return first instanceof Error ? first.message : "Evidence 服务读取失败";
}

export function EvidenceDrawer({
  evidenceId,
  snapshotHash,
  open,
  onClose,
}: {
  evidenceId: string | null;
  snapshotHash?: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const [evidenceState, setEvidenceState] = useState<EvidenceLoadState>(emptyEvidenceState);
  const lineageTitleId = useId();
  const restoreFocus = useDialogReturnFocus(open);
  useEffect(() => {
    if (!open || !evidenceId) {
      setEvidenceState(emptyEvidenceState);
      return;
    }

    const controller = new AbortController();
    const encodedEvidenceId = encodeURIComponent(evidenceId);
    setEvidenceState({ ...emptyEvidenceState, loading: true });
    void Promise.allSettled([
      readEvidenceJson<EvidenceMetadata>(`/backend/v1/evidence/${encodedEvidenceId}`, controller.signal),
      readEvidenceJson<EvidenceVerification>(`/backend/v1/evidence/${encodedEvidenceId}/verify`, controller.signal),
      readEvidenceJson<EvidenceLineage[]>(`/backend/v1/evidence/${encodedEvidenceId}/lineage`, controller.signal),
    ]).then((results) => {
      if (controller.signal.aborted) return;
      const metadataResult = results[0];
      const verificationResult = results[1];
      const lineageResult = results[2];
      const metadata = metadataResult.status === "fulfilled" ? metadataResult.value : null;
      const verification = verificationResult.status === "fulfilled" ? verificationResult.value : null;
      const lineage = lineageResult.status === "fulfilled" ? lineageResult.value : [];
      const failures = results.filter((result): result is PromiseRejectedResult => result.status === "rejected");
      if (!metadata && !verification && !lineageResultIsSuccessful(lineageResult)) {
        const failureStatus = evidenceFailureStatus(failures);
        setEvidenceState({
          ...emptyEvidenceState,
          error: evidenceFailureMessage(failureStatus, failures),
          failureStatus,
        });
        return;
      }
      setEvidenceState({
        loading: false,
        metadata,
        verification,
        lineage,
        partial: failures.length > 0,
        error: failures.length ? "部分 Evidence 接口不可用；已保留成功返回的只读信息。" : null,
        failureStatus: null,
      });
    });

    return () => controller.abort();
  }, [evidenceId, open]);

  const evidenceStatus: DataStatus = evidenceState.loading
    ? "loading"
    : evidenceState.failureStatus
      ? evidenceState.failureStatus
      : !evidenceId
        ? "no_data"
        : evidenceState.verification?.valid === false
          ? "conflicted"
          : evidenceState.partial
            ? "partial"
          : evidenceState.metadata && typeof evidenceState.verification?.valid === "boolean"
            ? "ready"
            : "partial";
  const encodedEvidenceId = evidenceId ? encodeURIComponent(evidenceId) : null;
  const visibleLineage = evidenceState.lineage.slice(0, 20);

  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.drawerBackdrop} />
        <Dialog.Content className={styles.drawer} onCloseAutoFocus={restoreFocus}>
          <div className={styles.drawerHeader}>
            <div>
              <p className={styles.eyebrow}>Evidence / lineage</p>
              <Dialog.Title className={styles.dialogTitle}>证据回看</Dialog.Title>
            </div>
            <div className={styles.drawerHeaderActions}>
              <StatusBadge status={evidenceStatus} />
              <Dialog.Close asChild>
                <button className={styles.closeButton} type="button" aria-label="关闭证据回看">×</button>
              </Dialog.Close>
            </div>
          </div>
          <Dialog.Description className={styles.drawerDescription}>
            只读查看 Evidence 元数据、完整性校验与直接血缘；不会自动读取原始文件内容。
          </Dialog.Description>

          {evidenceState.loading ? <p className={styles.drawerNotice} role="status">正在并行读取元数据、完整性校验与血缘…</p> : null}
          {evidenceState.error ? <p className={styles.drawerError} role="alert">{evidenceState.error}</p> : null}

          <dl className={styles.evidenceList}>
            <div><dt>Evidence ID</dt><dd>{evidenceState.metadata?.id ?? evidenceId ?? "no_data"}</dd></div>
            <div><dt>Snapshot SHA-256</dt><dd>{snapshotHash ?? "no_data"}</dd></div>
            <div><dt>Evidence SHA-256</dt><dd>{evidenceState.metadata?.sha256 ?? "no_data"}</dd></div>
            <div><dt>文件</dt><dd>{evidenceState.metadata ? `${evidenceState.metadata.filename} · ${evidenceState.metadata.content_type} · ${evidenceState.metadata.byte_size} bytes` : "no_data"}</dd></div>
            <div><dt>来源</dt><dd>{evidenceState.metadata ? `${evidenceState.metadata.source} · ${evidenceState.metadata.source_ref}` : "no_data"}</dd></div>
            <div><dt>等级</dt><dd>{evidenceState.metadata?.grade ?? "no_data"}</dd></div>
            <div><dt>有效期</dt><dd>{evidenceState.metadata ? `${formatDate(evidenceState.metadata.effective_at)} → ${evidenceState.metadata.effective_until ? formatDate(evidenceState.metadata.effective_until) : "持续有效"}` : "no_data"}</dd></div>
            <div><dt>记录</dt><dd>{evidenceState.metadata ? `${formatDate(evidenceState.metadata.recorded_at)} · ${evidenceState.metadata.created_by}` : "no_data"}</dd></div>
            <div>
              <dt>完整性</dt>
              <dd>{evidenceState.verification
                ? `${evidenceState.verification.valid ? "有效" : "冲突"} · expected ${shortHash(evidenceState.verification.expected_sha256)} · actual ${shortHash(evidenceState.verification.actual_sha256)} · ${evidenceState.verification.byte_size} bytes`
                : "no_data"}</dd>
            </div>
            <div><dt>权威边界</dt><dd>当前面板只读服务端投影，不创建、不晋升正式事实。</dd></div>
          </dl>

          <section className={styles.lineageSection} aria-labelledby={lineageTitleId}>
            <h3 id={lineageTitleId}>直接血缘（{evidenceState.lineage.length}）</h3>
            {visibleLineage.length ? (
              <ul>
                {visibleLineage.map((edge) => (
                  <li key={edge.id}>
                    <strong>{edge.relationship}</strong>
                    <span>{edge.from_type}:{edge.from_id} → {edge.to_type}:{edge.to_id}</span>
                    <small>{formatDate(edge.recorded_at)} · {edge.created_by}</small>
                  </li>
                ))}
              </ul>
            ) : <p>{evidenceState.loading ? "正在读取…" : "no_data"}</p>}
            {evidenceState.lineage.length > visibleLineage.length ? <p>另有 {evidenceState.lineage.length - visibleLineage.length} 条直接血缘未在抽屉展开。</p> : null}
          </section>

          {encodedEvidenceId && evidenceState.metadata ? (
            <a
              className={styles.evidenceDownload}
              href={`/backend/v1/evidence/${encodedEvidenceId}/content`}
              download
            >
              显式下载原始 Evidence 文件
            </a>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function DetailDrawer({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const restoreFocus = useDialogReturnFocus(open);
  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.drawerBackdrop} />
        <Dialog.Content className={styles.drawer} onCloseAutoFocus={restoreFocus}>
          <div className={styles.drawerHeader}>
            <Dialog.Title className={styles.dialogTitle}>{title}</Dialog.Title>
            <Dialog.Close asChild>
              <button className={styles.closeButton} type="button" aria-label="关闭详情">×</button>
            </Dialog.Close>
          </div>
          <Dialog.Description className={styles.srOnly}>当前所选数据的只读详情。</Dialog.Description>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function WallboardFrame({
  title,
  asOf,
  snapshotHash,
  status,
  children,
}: {
  title: string;
  asOf?: string | null;
  snapshotHash?: string | null;
  status: DataStatus;
  children: ReactNode;
}) {
  return (
    <div className={styles.wallboardPage}>
      <a className={styles.skipLink} href="#wallboard-content">跳转到大屏内容</a>
      <div className={styles.wallboardFrame}>
        <header className={styles.wallboardHeader}>
          <div><span className={styles.eyebrow}>KJDS · WALLBOARD</span><h1>{title}</h1></div>
          <div className={styles.wallboardMeta}><StatusBadge status={status} /><span>数据截止 {asOf ? formatDate(asOf) : "no_data"}</span><span>只读</span></div>
        </header>
        <main id="wallboard-content" className={styles.wallboardContent} tabIndex={-1}>{children}</main>
        <footer className={styles.wallboardFooter}><span>固定时点 · 异常置顶 · 不自动轮换业务动作</span><span>snapshot {shortHash(snapshotHash)}</span></footer>
      </div>
    </div>
  );
}

export function BriefingFrame({ title, children }: { title: string; children: ReactNode }) {
  const titleId = useId();
  return <section className={styles.briefingFrame} aria-labelledby={titleId}><header><p className={styles.eyebrow}>BRIEFING MODE</p><h2 id={titleId}>{title}</h2></header>{children}</section>;
}

function shortHash(value?: string | null) {
  return value ? `${value.slice(0, 8)}…${value.slice(-8)}` : "no_data";
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
