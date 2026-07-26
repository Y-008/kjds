"use client";

import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Boxes,
  CheckCircle2,
  CircleDashed,
  Cpu,
  Database,
  Fingerprint,
  GitBranch,
  Layers3,
  LockKeyhole,
  Network,
  Route,
  ShieldCheck,
  Sparkles,
  TimerReset,
  UserRoundCheck,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type {
  AtomicPoint,
  CapabilityAtlasSnapshot,
  CapabilityStatus,
  OperatingSurface,
  ValueStream,
} from "./contracts";
import styles from "./operating-graph-explorer.module.css";

export type GraphMode = "point" | "line" | "surface";

type Props = {
  atlas: CapabilityAtlasSnapshot;
  mode: GraphMode;
  query: string;
  scope: "ALL" | "RU" | "GLOBAL";
  status: "all" | CapabilityStatus;
};

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

const sourceLabel: Record<AtomicPoint["source_kind"], string> = {
  linkfox_public_C: "LinkFox 公开观察 · C",
  repository_verified: "KJDS 仓库合同",
  product_architecture: "KJDS 产品架构",
};

function includesQuery(values: Array<string | string[]>, query: string) {
  if (!query) return true;
  return values
    .flat()
    .join(" ")
    .toLocaleLowerCase("zh-CN")
    .includes(query.toLocaleLowerCase("zh-CN"));
}

function PointStatus({ status }: { status: CapabilityStatus }) {
  const Icon = statusIcon[status];
  return (
    <span className={`${styles.pointStatus} ${styles[status]}`}>
      <Icon size={11} />
      {statusLabel[status]}
    </span>
  );
}

function Pills({ label, values }: { label: string; values: string[] }) {
  return (
    <section className={styles.pills}>
      <span>{label}</span>
      <div>
        {values.map((value) => (
          <small key={value}>{value}</small>
        ))}
      </div>
    </section>
  );
}

function PointDetail({
  point,
  atlas,
}: {
  point: AtomicPoint | null;
  atlas: CapabilityAtlasSnapshot;
}) {
  if (!point) {
    return (
      <div className={styles.emptyDetail}>
        <Fingerprint size={30} />
        <strong>选择一个原子功能点</strong>
        <p>查看业务对象、合同、Evidence、失败队列、回读、责任和 KPI。</p>
      </div>
    );
  }
  const streamIndex = new Map(
    atlas.operating_graph.value_streams.map((stream) => [stream.id, stream.label]),
  );
  return (
    <>
      <header className={styles.detailHeader}>
        <div>
          <PointStatus status={point.status} />
          <span className={styles.sourceTag}>{sourceLabel[point.source_kind]}</span>
        </div>
        <small>{point.id}</small>
        <h2>{point.label}</h2>
        <p>{point.objective}</p>
      </header>
      <section className={styles.contractStrip}>
        <article>
          <span>业务对象</span>
          <strong>{point.business_object}</strong>
        </article>
        <article>
          <span>操作类型</span>
          <strong>{point.operation_kind}</strong>
        </article>
        <article>
          <span>合同 Profile</span>
          <strong>{point.contract_profile_id}</strong>
        </article>
        <article>
          <span>SLO / SLA</span>
          <strong>{point.sla}</strong>
        </article>
      </section>
      <section className={styles.boundaryCard}>
        <ShieldCheck size={17} />
        <div>
          <span>Evidence 门与来源边界</span>
          <p>{point.evidence_gate}</p>
          <small>{point.source_boundary}</small>
        </div>
      </section>
      <section className={styles.techCard}>
        <Cpu size={17} />
        <div>
          <span>技术实现</span>
          <p>{point.technology}</p>
        </div>
      </section>
      <div className={styles.twoColumns}>
        <Pills label="输入合同" values={point.input_contract} />
        <Pills label="输出合同" values={point.output_contract} />
      </div>
      <section className={styles.readbackGrid}>
        <article>
          <AlertTriangle size={15} />
          <span>失败队列</span>
          <strong>{point.failure_queue}</strong>
          <p>{point.failure_modes.join(" · ")}</p>
        </article>
        <article>
          <TimerReset size={15} />
          <span>独立回读</span>
          <p>{point.readback}</p>
        </article>
        <article>
          <UserRoundCheck size={15} />
          <span>责任与复核</span>
          <strong>{point.owner}</strong>
          <p>{point.reviewer}</p>
        </article>
      </section>
      <Pills label="价值流成员关系" values={point.value_stream_ids.map((id) => streamIndex.get(id) ?? id)} />
      <Pills label="KPI" values={point.kpi} />
      <Pills label="不可越权控制" values={point.controls} />
      <footer className={styles.detailFooter}>
        <Link href={point.workspace}>
          进入真实 KJDS 工作区
          <ArrowUpRight size={14} />
        </Link>
        <small>本图谱只读，不是执行权限。</small>
      </footer>
    </>
  );
}

function PointView({ atlas, points }: { atlas: CapabilityAtlasSnapshot; points: AtomicPoint[] }) {
  const [selectedId, setSelectedId] = useState("");
  useEffect(() => {
    if (!points.some((point) => point.id === selectedId)) {
      setSelectedId(points[0]?.id ?? "");
    }
  }, [points, selectedId]);
  const selected = points.find((point) => point.id === selectedId) ?? null;
  const grouped = useMemo(
    () =>
      atlas.domains
        .map((domain) => ({
          ...domain,
          groups: domain.capabilities
            .map((capability) => ({
              capability,
              points: points.filter(
                (point) => point.parent_capability_id === capability.id,
              ),
            }))
            .filter((group) => group.points.length),
        }))
        .filter((domain) => domain.groups.length),
    [atlas, points],
  );

  return (
    <section className={styles.graphWorkspace}>
      <div className={styles.graphPanel}>
        <header className={styles.graphHeader}>
          <div>
            <span><Boxes size={14} /> POINT · 原子功能合同</span>
            <h2>从 LinkFox 工具，到经营与控制原子点</h2>
            <p>143 个点均落到对象、合同、Evidence、责任、失败队列、回读与 KPI。</p>
          </div>
          <strong>{points.length}<small>可见原子点</small></strong>
        </header>
        <div className={styles.pointRoot}>
          <div className={styles.kernelNode}>
            <Database size={17} />
            <div>
              <strong>KJDS governed kernel</strong>
              <small>Product · Evidence · Passport · CM3 · Approval · Execution</small>
            </div>
          </div>
          {grouped.map((domain, domainIndex) => (
            <article className={styles.pointDomain} key={domain.id}>
              <header>
                <span>{String(domainIndex + 1).padStart(2, "0")}</span>
                <div>
                  <strong>{domain.label.replace(/^\d+\s*·\s*/, "")}</strong>
                  <small>{domain.groups.reduce((total, group) => total + group.points.length, 0)} 个原子点</small>
                </div>
              </header>
              <div className={styles.capabilityClusters}>
                {domain.groups.map(({ capability, points: groupPoints }) => (
                  <section className={styles.capabilityCluster} key={capability.id}>
                    <div className={styles.clusterHead}>
                      <div>
                        <GitBranch size={13} />
                        <strong>{capability.label}</strong>
                      </div>
                      <small>{groupPoints.length} POINTS</small>
                    </div>
                    <div className={styles.pointGrid}>
                      {groupPoints.map((point) => (
                        <button
                          type="button"
                          key={point.id}
                          aria-pressed={point.id === selectedId}
                          className={point.id === selectedId ? styles.selectedPoint : ""}
                          onClick={() => setSelectedId(point.id)}
                        >
                          <span className={styles.pointDot} aria-hidden="true" />
                          <div>
                            <strong>{point.label}</strong>
                            <small>{point.business_object}</small>
                          </div>
                          <PointStatus status={point.status} />
                        </button>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </article>
          ))}
          {!grouped.length ? (
            <div className={styles.emptyGraph}>
              <Boxes size={26} />
              <strong>没有匹配的原子点</strong>
              <p>调整搜索、市场或状态过滤。</p>
            </div>
          ) : null}
        </div>
      </div>
      <aside className={styles.graphDetail}>
        <PointDetail point={selected} atlas={atlas} />
      </aside>
    </section>
  );
}

function StreamDetail({
  stream,
  pointIndex,
}: {
  stream: ValueStream | null;
  pointIndex: Map<string, AtomicPoint>;
}) {
  if (!stream) {
    return (
      <div className={styles.emptyDetail}>
        <Route size={30} />
        <strong>选择一条价值流</strong>
        <p>查看入口/出口门、对象状态变化、事件、异常、SLO 与人工接管。</p>
      </div>
    );
  }
  return (
    <>
      <header className={styles.detailHeader}>
        <div><span className={styles.lineTag}>LINE · END TO END</span></div>
        <small>{stream.id}</small>
        <h2>{stream.label}</h2>
        <p>{stream.mission}</p>
      </header>
      <section className={styles.gatePair}>
        <article>
          <span>ENTRY GATE</span>
          <p>{stream.entry_gate}</p>
        </article>
        <ArrowRight size={18} />
        <article>
          <span>EXIT GATE</span>
          <p>{stream.exit_gate}</p>
        </article>
      </section>
      <Pills label="业务对象状态变化" values={stream.object_transitions} />
      <Pills label="领域事件" values={stream.events} />
      <Pills label="异常类型" values={stream.exceptions} />
      <section className={styles.boundaryCard}>
        <UserRoundCheck size={17} />
        <div>
          <span>人工接管</span>
          <p>{stream.human_takeover}</p>
          <small>{stream.sla}</small>
        </div>
      </section>
      <section className={styles.techCard}>
        <Network size={17} />
        <div>
          <span>适配器边界</span>
          <p>{stream.adapter_boundary}</p>
        </div>
      </section>
      <Pills label="价值流 KPI" values={stream.kpi} />
      <Pills
        label="支撑原子点"
        values={stream.supporting_point_ids.map((id) => pointIndex.get(id)?.label ?? id)}
      />
    </>
  );
}

function StreamView({
  atlas,
  streams,
  visiblePointIds,
}: {
  atlas: CapabilityAtlasSnapshot;
  streams: ValueStream[];
  visiblePointIds: Set<string>;
}) {
  const [selectedId, setSelectedId] = useState("");
  useEffect(() => {
    if (!streams.some((stream) => stream.id === selectedId)) {
      setSelectedId(streams[0]?.id ?? "");
    }
  }, [selectedId, streams]);
  const pointIndex = useMemo(
    () => new Map(atlas.operating_graph.atomic_points.map((point) => [point.id, point])),
    [atlas],
  );
  const selected = streams.find((stream) => stream.id === selectedId) ?? null;
  return (
    <section className={styles.graphWorkspace}>
      <div className={styles.graphPanel}>
        <header className={styles.graphHeader}>
          <div>
            <span><Route size={14} /> LINE · 端到端价值流</span>
            <h2>对象在流动，门禁与责任不能断</h2>
            <p>从趋势到财务与复盘，14 条线显式展示状态变化、异常和人工接管。</p>
          </div>
          <strong>{streams.length}<small>可见价值流</small></strong>
        </header>
        <div className={styles.streamList}>
          {streams.map((stream, streamIndex) => (
            <article
              className={`${styles.streamCard} ${
                stream.id === selectedId ? styles.selectedStream : ""
              }`}
              key={stream.id}
            >
              <button type="button" onClick={() => setSelectedId(stream.id)}>
                <span>{String(streamIndex + 1).padStart(2, "0")}</span>
                <div>
                  <strong>{stream.label}</strong>
                  <small>{stream.mission}</small>
                </div>
                <b>{stream.stage_point_ids.length} stages</b>
              </button>
              <div className={styles.stageLane}>
                {stream.stage_point_ids.map((pointId, index) => {
                  const point = pointIndex.get(pointId);
                  const visible = visiblePointIds.has(pointId);
                  return (
                    <div className={visible ? "" : styles.filteredStage} key={pointId}>
                      <span>{index + 1}</span>
                      <strong>{point?.label ?? pointId}</strong>
                      <small>{point?.business_object ?? "unknown"}</small>
                      {point ? <PointStatus status={point.status} /> : null}
                      {index < stream.stage_point_ids.length - 1 ? (
                        <ArrowRight className={styles.stageArrow} size={14} />
                      ) : null}
                    </div>
                  );
                })}
              </div>
              <footer>
                <span>ENTRY</span><p>{stream.entry_gate}</p>
                <ArrowRight size={13} />
                <span>EXIT</span><p>{stream.exit_gate}</p>
              </footer>
            </article>
          ))}
          {!streams.length ? (
            <div className={styles.emptyGraph}>
              <Route size={26} />
              <strong>没有匹配的价值流</strong>
              <p>搜索价值流、阶段、对象、异常或 KPI。</p>
            </div>
          ) : null}
        </div>
      </div>
      <aside className={styles.graphDetail}>
        <StreamDetail stream={selected} pointIndex={pointIndex} />
      </aside>
    </section>
  );
}

function SurfaceDetail({
  surface,
  streamIndex,
  pointIndex,
}: {
  surface: OperatingSurface | null;
  streamIndex: Map<string, ValueStream>;
  pointIndex: Map<string, AtomicPoint>;
}) {
  if (!surface) {
    return (
      <div className={styles.emptyDetail}>
        <Layers3 size={30} />
        <strong>选择一个经营控制面</strong>
        <p>查看维度、真源、管理决策、价值流、指标、预警与写边界。</p>
      </div>
    );
  }
  return (
    <>
      <header className={styles.detailHeader}>
        <div><span className={styles.surfaceTag}>SURFACE · CONTROL PLANE</span></div>
        <small>{surface.id}</small>
        <h2>{surface.label}</h2>
        <p>{surface.mission}</p>
      </header>
      <section className={styles.boundaryCard}>
        <Database size={17} />
        <div>
          <span>真源 Owner</span>
          <p>{surface.truth_owner}</p>
        </div>
      </section>
      <Pills label="经营维度" values={surface.dimensions} />
      <Pills label="必须回答的决策" values={surface.decisions} />
      <Pills
        label="关联价值流"
        values={surface.value_stream_ids.map((id) => streamIndex.get(id)?.label ?? id)}
      />
      <Pills
        label="核心原子点"
        values={surface.focus_point_ids.map((id) => pointIndex.get(id)?.label ?? id)}
      />
      <Pills label="经营 KPI" values={surface.kpi} />
      <section className={styles.alertCard}>
        <AlertTriangle size={17} />
        <div>
          <span>预警条件</span>
          <p>{surface.alerts.join(" · ")}</p>
        </div>
      </section>
      <section className={styles.techCard}>
        <LockKeyhole size={17} />
        <div>
          <span>写入边界</span>
          <p>{surface.write_boundary}</p>
        </div>
      </section>
    </>
  );
}

function SurfaceView({
  atlas,
  surfaces,
}: {
  atlas: CapabilityAtlasSnapshot;
  surfaces: OperatingSurface[];
}) {
  const [selectedId, setSelectedId] = useState("");
  useEffect(() => {
    if (!surfaces.some((surface) => surface.id === selectedId)) {
      setSelectedId(surfaces[0]?.id ?? "");
    }
  }, [selectedId, surfaces]);
  const streamIndex = useMemo(
    () => new Map(atlas.operating_graph.value_streams.map((stream) => [stream.id, stream])),
    [atlas],
  );
  const pointIndex = useMemo(
    () => new Map(atlas.operating_graph.atomic_points.map((point) => [point.id, point])),
    [atlas],
  );
  const selected = surfaces.find((surface) => surface.id === selectedId) ?? null;
  return (
    <section className={styles.graphWorkspace}>
      <div className={styles.graphPanel}>
        <header className={styles.graphHeader}>
          <div>
            <span><Layers3 size={14} /> SURFACE · 经营控制面</span>
            <h2>从单工具，升到跨店铺经营决策</h2>
            <p>8 个面把价值流按维度、真源、指标、预警和权限边界重新组织。</p>
          </div>
          <strong>{surfaces.length}<small>可见经营面</small></strong>
        </header>
        <div className={styles.surfaceMatrix}>
          <div className={styles.surfaceKernel}>
            <Database size={20} />
            <strong>ONE GOVERNED KERNEL</strong>
            <small>Evidence / Product / Passport / CM3 / Approval / Execution / Reconciliation</small>
          </div>
          {surfaces.map((surface, index) => (
            <button
              type="button"
              key={surface.id}
              aria-pressed={surface.id === selectedId}
              className={`${styles.surfaceCard} ${
                surface.id === selectedId ? styles.selectedSurface : ""
              }`}
              onClick={() => setSelectedId(surface.id)}
            >
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{surface.label}</strong>
                <p>{surface.mission}</p>
              </div>
              <footer>
                <small><Route size={11} /> {surface.value_stream_ids.length} 条价值流</small>
                <small><Boxes size={11} /> {surface.focus_point_ids.length} 个核心点</small>
              </footer>
              <div className={styles.surfaceMetrics}>
                {surface.kpi.slice(0, 3).map((kpi) => <small key={kpi}>{kpi}</small>)}
              </div>
            </button>
          ))}
          {!surfaces.length ? (
            <div className={styles.emptyGraph}>
              <Layers3 size={26} />
              <strong>没有匹配的经营面</strong>
              <p>搜索决策、真源、维度、价值流、KPI 或预警。</p>
            </div>
          ) : null}
        </div>
      </div>
      <aside className={styles.graphDetail}>
        <SurfaceDetail
          surface={selected}
          streamIndex={streamIndex}
          pointIndex={pointIndex}
        />
      </aside>
    </section>
  );
}

export function OperatingGraphExplorer({ atlas, mode, query, scope, status }: Props) {
  const normalizedQuery = query.trim();
  const scopedPoints = useMemo(
    () =>
      atlas.operating_graph.atomic_points.filter(
        (point) =>
          (scope === "ALL" || point.markets.includes(scope)) &&
          (status === "all" || point.status === status),
      ),
    [atlas, scope, status],
  );
  const points = useMemo(
    () =>
      scopedPoints.filter((point) =>
          includesQuery(
            [
              point.label,
              point.objective,
              point.business_object,
              point.operation_kind,
              point.technology,
              point.input_contract,
              point.output_contract,
              point.failure_modes,
              point.kpi,
              point.platforms,
              point.value_stream_ids,
            ],
            normalizedQuery,
          )
      ),
    [normalizedQuery, scopedPoints],
  );
  const scopedPointIds = useMemo(
    () => new Set(scopedPoints.map((point) => point.id)),
    [scopedPoints],
  );
  const pointIndex = useMemo(
    () => new Map(atlas.operating_graph.atomic_points.map((point) => [point.id, point])),
    [atlas],
  );
  const streams = useMemo(
    () =>
      atlas.operating_graph.value_streams.filter((stream) => {
        const referenced = [...stream.stage_point_ids, ...stream.supporting_point_ids];
        const hasVisiblePoint = referenced.some((id) => scopedPointIds.has(id));
        return (
          hasVisiblePoint &&
          includesQuery(
            [
              stream.label,
              stream.mission,
              stream.object_transitions,
              stream.events,
              stream.exceptions,
              stream.kpi,
              referenced.map((id) => pointIndex.get(id)?.label ?? id),
            ],
            normalizedQuery,
          )
        );
      }),
    [atlas, normalizedQuery, pointIndex, scopedPointIds],
  );
  const eligibleStreamIds = useMemo(
    () =>
      new Set(
        atlas.operating_graph.value_streams
          .filter((stream) =>
            [...stream.stage_point_ids, ...stream.supporting_point_ids].some((id) =>
              scopedPointIds.has(id),
            ),
          )
          .map((stream) => stream.id),
      ),
    [atlas, scopedPointIds],
  );
  const surfaces = useMemo(
    () =>
      atlas.operating_graph.operating_surfaces.filter(
        (surface) =>
          surface.value_stream_ids.some((id) => eligibleStreamIds.has(id)) &&
          includesQuery(
            [
              surface.label,
              surface.mission,
              surface.dimensions,
              surface.decisions,
              surface.truth_owner,
              surface.kpi,
              surface.alerts,
              surface.value_stream_ids.flatMap((id) => {
                const stream = atlas.operating_graph.value_streams.find(
                  (item) => item.id === id,
                );
                if (!stream) return [id];
                return [
                  stream.label,
                  stream.mission,
                  ...stream.stage_point_ids.map(
                    (pointId) => pointIndex.get(pointId)?.label ?? pointId,
                  ),
                  ...stream.supporting_point_ids.map(
                    (pointId) => pointIndex.get(pointId)?.label ?? pointId,
                  ),
                ];
              }),
              surface.focus_point_ids.map((id) => pointIndex.get(id)?.label ?? id),
            ],
            normalizedQuery,
          ),
      ),
    [atlas, eligibleStreamIds, normalizedQuery, pointIndex],
  );

  if (mode === "line") {
    return <StreamView atlas={atlas} streams={streams} visiblePointIds={scopedPointIds} />;
  }
  if (mode === "surface") {
    return <SurfaceView atlas={atlas} surfaces={surfaces} />;
  }
  return <PointView atlas={atlas} points={points} />;
}
