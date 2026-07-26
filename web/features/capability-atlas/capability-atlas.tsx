"use client";

import {
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  Cpu,
  Database,
  Fingerprint,
  GitBranch,
  Globe2,
  Layers3,
  LockKeyhole,
  MapPin,
  Network,
  Radar,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import type { WebSession } from "../dashboard/contracts";
import type {
  CapabilityAtlasSnapshot,
  CapabilityDomain,
  CapabilityLeaf,
  CapabilityStatus,
} from "./contracts";
import {
  OperatingGraphExplorer,
  type GraphMode,
} from "./operating-graph-explorer";
import styles from "./capability-atlas.module.css";

type ExplorerMode = GraphMode | "capability";

const statusLabel: Record<CapabilityStatus, string> = {
  implemented: "已实现",
  ready: "已设计",
  gated: "受门禁",
  research_only: "仅研究",
};

const statusIcon = {
  implemented: CheckCircle2,
  ready: Sparkles,
  gated: LockKeyhole,
  research_only: CircleDashed,
};

const platformLabel: Record<string, string> = {
  internal: "KJDS 内核",
  ozon: "Ozon",
  wildberries: "Wildberries",
  yandex_market: "Yandex Market",
  amazon: "Amazon",
  temu: "Temu",
  shopee: "Shopee",
  shein: "SHEIN",
  aliexpress: "AliExpress",
  shopify: "Shopify",
  ebay: "eBay",
  etsy: "Etsy",
  lazada: "Lazada",
  tiktok_shop: "TikTok Shop",
  "1688": "1688",
};

function shortHash(value: string) {
  return value ? `${value.slice(0, 9)}…${value.slice(-9)}` : "—";
}

function matchesQuery(capability: CapabilityLeaf, domain: CapabilityDomain, query: string) {
  if (!query) return true;
  const haystack = [
    capability.label,
    capability.summary,
    capability.linkfox,
    capability.surpass,
    capability.russia,
    capability.global,
    capability.technology,
    domain.label,
    ...capability.inputs,
    ...capability.outputs,
    ...capability.platforms,
  ]
    .join(" ")
    .toLocaleLowerCase("zh-CN");
  return haystack.includes(query.toLocaleLowerCase("zh-CN"));
}

function StatusBadge({ status }: { status: CapabilityStatus }) {
  const Icon = statusIcon[status];
  return (
    <span className={`${styles.statusBadge} ${styles[status]}`}>
      <Icon size={12} />
      {statusLabel[status]}
    </span>
  );
}

function DetailList({ label, values }: { label: string; values: string[] }) {
  return (
    <section className={styles.detailList}>
      <span>{label}</span>
      <div>
        {values.map((item) => (
          <small key={item}>{item}</small>
        ))}
      </div>
    </section>
  );
}

export function CapabilityAtlas() {
  const [session, setSession] = useState<WebSession | null>(null);
  const [atlas, setAtlas] = useState<CapabilityAtlasSnapshot | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"ALL" | "RU" | "GLOBAL">("ALL");
  const [status, setStatus] = useState<"all" | CapabilityStatus>("all");
  const [viewMode, setViewMode] = useState<ExplorerMode>("point");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy(true);
    setError("");
    const [sessionResponse, atlasResponse] = await Promise.all([
      fetchJson<WebSession | { detail?: string }>("/auth/session", {
        cache: "no-store",
        signal,
      }),
      fetchJson<CapabilityAtlasSnapshot | { detail?: string }>(
        "/backend/v1/capability-atlas/snapshot",
        { cache: "no-store", signal },
      ),
    ]);
    const redirectStatus = [sessionResponse.status, atlasResponse.status].find(
      (value) => value === 401 || value === 428,
    );
    if (redirectStatus === 401) {
      window.location.assign("/login");
      return;
    }
    if (redirectStatus === 428) {
      window.location.assign("/mfa");
      return;
    }
    const [sessionBody, atlasBody] = await Promise.all([
      sessionResponse.json(),
      atlasResponse.json(),
    ]);
    if (!sessionResponse.ok || !atlasResponse.ok) {
      const detail =
        ("detail" in atlasBody && atlasBody.detail) ||
        ("detail" in sessionBody && sessionBody.detail) ||
        "能力图谱暂不可用";
      setError(String(detail));
      setBusy(false);
      return;
    }
    const nextAtlas = atlasBody as CapabilityAtlasSnapshot;
    setSession(sessionBody as WebSession);
    setAtlas(nextAtlas);
    setSelectedId((current) => current || nextAtlas.domains[0]?.capabilities[0]?.id || "");
    setBusy(false);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort("capability atlas unmounted");
  }, [load]);

  const visibleDomains = useMemo(() => {
    if (!atlas) return [];
    return atlas.domains
      .map((domain) => ({
        ...domain,
        capabilities: domain.capabilities.filter(
          (capability) =>
            (scope === "ALL" || capability.markets.includes(scope)) &&
            (status === "all" || capability.status === status) &&
            matchesQuery(capability, domain, query.trim()),
        ),
      }))
      .filter((domain) => domain.capabilities.length > 0);
  }, [atlas, query, scope, status]);

  const visibleLeaves = useMemo(
    () => visibleDomains.flatMap((domain) => domain.capabilities),
    [visibleDomains],
  );

  useEffect(() => {
    if (!visibleLeaves.length) return;
    if (!visibleLeaves.some((item) => item.id === selectedId)) {
      setSelectedId(visibleLeaves[0].id);
    }
  }, [selectedId, visibleLeaves]);

  const selected = useMemo(
    () =>
      atlas?.domains
        .flatMap((domain) => domain.capabilities)
        .find((capability) => capability.id === selectedId) ?? null,
    [atlas, selectedId],
  );

  function toggleDomain(domainId: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(domainId)) next.delete(domainId);
      else next.add(domainId);
      return next;
    });
  }

  function resetFilters() {
    setQuery("");
    setScope("ALL");
    setStatus("all");
    setCollapsed(new Set());
  }

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/" className={styles.backLink}>
          <ArrowLeft size={16} />
          返回经营平台
        </Link>
        <div className={styles.productMark}>
          <span>
            <Network size={18} />
          </span>
          <div>
            <strong>Capability Atlas</strong>
            <small>RUSSIA FIRST · GLOBAL READY</small>
          </div>
        </div>
        <div className={styles.identity}>
          <span>{session?.email?.slice(0, 1).toUpperCase() ?? "K"}</span>
          <div>
            <strong>{session?.email ?? "验证身份中"}</strong>
            <small>{session?.roles?.join(" / ") ?? "server-owned identity"}</small>
          </div>
        </div>
      </header>

      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <span className={styles.eyebrow}>
            <Radar size={14} />
            KJDS 0.55.0 · CROSS-BORDER AI OPERATING GRAPH
          </span>
          <h1>
            不止覆盖 LinkFox 每个入口，
            <em>把点、线、面打成真实经营闭环</em>
          </h1>
          <p>
            原子功能点落到对象、合同、Evidence、责任与回读；14 条价值流贯穿选品、
            内容、Listing、供应、履约与财务；8 个经营面支撑俄罗斯优先、全球扩展。
            LinkFox 始终是 C 级公开工作流参考；受门禁能力不会被包装成已接入。
          </p>
          <div className={styles.heroProofs}>
            <span>
              <MapPin size={14} />
              Russia / Ozon 首市场
            </span>
            <span>
              <Globe2 size={14} />
              全球平台适配器
            </span>
            <span>
              <ShieldCheck size={14} />
              Evidence + Approval + Readback
            </span>
          </div>
        </div>

        <div className={styles.heroMetrics}>
          <article>
            <strong>{atlas?.counts.atomic_points ?? "—"}</strong>
            <span>原子功能点</span>
          </article>
          <article>
            <strong>{atlas?.counts.value_streams ?? "—"}</strong>
            <span>端到端价值流</span>
          </article>
          <article>
            <strong>{atlas?.counts.operating_surfaces ?? "—"}</strong>
            <span>经营控制面</span>
          </article>
          <article>
            <strong>0</strong>
            <span>伪造接入</span>
          </article>
          <footer>
            <Fingerprint size={14} />
            <span title={atlas?.registry_sha256}>
              {atlas ? shortHash(atlas.registry_sha256) : "正在读取注册表"}
            </span>
          </footer>
        </div>
      </section>

      <section className={styles.sourceBoundary}>
        <div>
          <span>C</span>
          <div>
            <strong>LinkFox 公开观察边界</strong>
            <p>{atlas?.source_policy.boundary ?? "正在读取服务端来源策略…"}</p>
          </div>
        </div>
        <small>
          审查日期 {atlas?.last_reviewed ?? "—"} · Ozon 接入验证：
          <b>{atlas?.control_envelope.linkfox_ozon_integration_verified ? "是" : "否"}</b>
        </small>
      </section>

      <section className={styles.viewTabs} aria-label="点线面视图">
        {(
          [
            ["point", "点 · 原子功能", "工具、经营与控制最小合同"],
            ["line", "线 · 端到端流", "对象变化、门禁、异常与接管"],
            ["surface", "面 · 经营控制", "维度、真源、决策、KPI 与预警"],
            ["capability", "主干 · 49 能力", "保留稳定宏观导航与竞品对照"],
          ] as const
        ).map(([mode, label, description]) => (
          <button
            type="button"
            key={mode}
            aria-pressed={viewMode === mode}
            className={viewMode === mode ? styles.activeView : ""}
            onClick={() => setViewMode(mode)}
          >
            <strong>{label}</strong>
            <small>{description}</small>
          </button>
        ))}
      </section>

      <section className={styles.filterBar} aria-label="能力筛选">
        <label className={styles.searchBox}>
          <Search size={17} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="跨点、线、面搜索对象、技术、平台、异常、KPI 或决策"
            aria-label="搜索能力"
          />
          {query ? (
            <button type="button" onClick={() => setQuery("")} aria-label="清空搜索">
              <X size={15} />
            </button>
          ) : null}
        </label>
        <div className={styles.segmented} aria-label="市场范围">
          {(["ALL", "RU", "GLOBAL"] as const).map((item) => (
            <button
              type="button"
              className={scope === item ? styles.activeFilter : ""}
              onClick={() => setScope(item)}
              key={item}
            >
              {item === "ALL" ? "全部市场" : item === "RU" ? "俄罗斯" : "全球"}
            </button>
          ))}
        </div>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value as "all" | CapabilityStatus)}
          aria-label="能力状态"
        >
          <option value="all">全部状态</option>
          <option value="implemented">已实现</option>
          <option value="ready">已设计</option>
          <option value="gated">受门禁</option>
          <option value="research_only">仅研究</option>
        </select>
        <button className={styles.resetButton} type="button" onClick={resetFilters}>
          <RefreshCw size={14} />
          重置
        </button>
        <span className={styles.resultCount}>
          {atlas
            ? `${atlas.counts.atomic_points} 点 · ${atlas.counts.value_streams} 线 · ${atlas.counts.operating_surfaces} 面`
            : "读取运行图谱"}
        </span>
      </section>

      {error ? (
        <section className={styles.errorState}>
          <CircleDashed size={24} />
          <div>
            <strong>能力图谱暂不可用</strong>
            <p>{error}</p>
          </div>
          <button type="button" onClick={() => void load()}>
            重试
          </button>
        </section>
      ) : null}

      {busy && !atlas ? (
        <section className={styles.loadingState}>
          <RefreshCw className={styles.spin} size={24} />
          <strong>正在验证身份并读取服务端能力树</strong>
          <p>不会从浏览器补写状态或竞品事实。</p>
        </section>
      ) : null}

      {atlas && viewMode !== "capability" ? (
        <OperatingGraphExplorer
          atlas={atlas}
          mode={viewMode}
          query={query}
          scope={scope}
          status={status}
        />
      ) : null}

      {atlas && viewMode === "capability" ? (
        <section className={styles.atlasWorkspace}>
          <div className={styles.treePanel}>
            <header className={styles.treeHeader}>
              <div>
                <span>
                  <GitBranch size={14} />
                  交互式能力树
                </span>
                <h2>AI 跨境经营能力主干</h2>
                <p>点击任一叶子，在右侧查看逐功能分析与实现合同。</p>
              </div>
              <div>
                <button type="button" onClick={() => setCollapsed(new Set())}>
                  展开全部
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setCollapsed(new Set(visibleDomains.map((domain) => domain.id)))
                  }
                >
                  收起全部
                </button>
              </div>
            </header>

            <div className={styles.treeRoot}>
              <div className={styles.rootNode}>
                <span>
                  <Database size={17} />
                </span>
                <div>
                  <strong>KJDS 统一经营内核</strong>
                  <small>Canonical Product · Evidence · CM3 · Approval</small>
                </div>
              </div>
              <div className={styles.rootStem} aria-hidden="true" />
              <div className={styles.domainTree}>
                {visibleDomains.map((domain, domainIndex) => {
                  const isCollapsed = collapsed.has(domain.id);
                  return (
                    <article className={styles.domainBranch} key={domain.id}>
                      <button
                        type="button"
                        className={styles.domainNode}
                        aria-expanded={!isCollapsed}
                        onClick={() => toggleDomain(domain.id)}
                      >
                        <span>{String(domainIndex + 1).padStart(2, "0")}</span>
                        <div>
                          <strong>{domain.label.replace(/^\d+\s*·\s*/, "")}</strong>
                          <small>{domain.capabilities.length} 项 · {domain.mission}</small>
                        </div>
                        <ChevronDown
                          size={17}
                          className={isCollapsed ? styles.collapsedChevron : ""}
                        />
                      </button>
                      {!isCollapsed ? (
                        <div className={styles.leafGrid}>
                          {domain.capabilities.map((capability) => (
                            <button
                              type="button"
                              className={`${styles.leafNode} ${
                                selectedId === capability.id ? styles.selectedLeaf : ""
                              }`}
                              aria-pressed={selectedId === capability.id}
                              onClick={() => setSelectedId(capability.id)}
                              key={capability.id}
                            >
                              <span className={styles.leafConnector} aria-hidden="true" />
                              <div className={styles.leafHead}>
                                <strong>{capability.label}</strong>
                                <StatusBadge status={capability.status} />
                              </div>
                              <p>{capability.summary}</p>
                              <small>
                                {capability.platforms
                                  .slice(0, 3)
                                  .map((item) => platformLabel[item] ?? item)
                                  .join(" · ")}
                                {capability.platforms.length > 3 ? " +" : ""}
                              </small>
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
              {!visibleDomains.length ? (
                <div className={styles.emptyState}>
                  <Search size={24} />
                  <strong>没有匹配的能力</strong>
                  <p>调整关键词、市场或状态筛选。</p>
                  <button type="button" onClick={resetFilters}>
                    清除筛选
                  </button>
                </div>
              ) : null}
            </div>
          </div>

          <aside className={styles.detailPanel} aria-live="polite">
            {selected ? (
              <>
                <header>
                  <StatusBadge status={selected.status} />
                  <span>{selected.id}</span>
                  <h2>{selected.label}</h2>
                  <p>{selected.summary}</p>
                </header>

                <section className={styles.comparison}>
                  <article>
                    <span>LINKFOX · C 级公开参考</span>
                    <p>{selected.linkfox}</p>
                  </article>
                  <article>
                    <span>KJDS · 超越设计</span>
                    <p>{selected.surpass}</p>
                  </article>
                </section>

                <section className={styles.marketSplit}>
                  <article>
                    <MapPin size={15} />
                    <span>俄罗斯 / Ozon</span>
                    <p>{selected.russia}</p>
                  </article>
                  <article>
                    <Globe2 size={15} />
                    <span>全球扩展</span>
                    <p>{selected.global}</p>
                  </article>
                </section>

                <section className={styles.techCard}>
                  <Cpu size={17} />
                  <div>
                    <span>前沿技术实现</span>
                    <p>{selected.technology}</p>
                  </div>
                </section>

                <div className={styles.ioGrid}>
                  <DetailList label="输入合同" values={selected.inputs} />
                  <DetailList label="输出合同" values={selected.outputs} />
                </div>
                <DetailList
                  label="平台范围"
                  values={selected.platforms.map((item) => platformLabel[item] ?? item)}
                />
                <DetailList label="不可越权控制" values={selected.controls} />

                <footer>
                  <Link href={selected.workspace}>
                    进入 KJDS 工作区
                    <ArrowUpRight size={14} />
                  </Link>
                  <small>
                    {atlas.status_definitions[selected.status]}
                  </small>
                </footer>
              </>
            ) : (
              <div className={styles.emptyDetail}>
                <Layers3 size={28} />
                <strong>选择一个能力叶子</strong>
                <p>右侧会显示逐功能对照、俄罗斯落地与技术合同。</p>
              </div>
            )}
          </aside>
        </section>
      ) : null}

      {atlas ? (
        <section className={styles.technologyRail}>
          <header>
            <span>
              <Cpu size={14} />
              TECHNOLOGY PRINCIPLES
            </span>
            <h2>前沿，不等于无边界地加组件</h2>
            <p>
              先把来源、结构化输出、评测、成本、权限、回读和回滚做实；真实压力出现后再升级基础设施。
            </p>
          </header>
          <div>
            {atlas.technology_principles.map((principle, index) => (
              <article key={principle}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <p>{principle}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  );
}
