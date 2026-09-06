"use client";

import { AlertTriangle, ArrowLeft, CheckCircle2, CircleSlash2, LockKeyhole, RefreshCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { FormEvent, useRef, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import { isTimezoneIsoTimestamp, validateWebSession } from "../bi/contract";
import { parseOzonProductionAcceptance, type OzonProductionAcceptance } from "./contracts";
import styles from "./ozon-production-acceptance.module.css";

type LoadState = "idle" | "loading" | "loaded" | "error";

function shortHash(value: string | null | undefined) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "—";
}

function valueLabel(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function GateIcon({ status }: { status: OzonProductionAcceptance["gate_status"] }) {
  if (status === "PASS") return <CheckCircle2 aria-hidden="true" />;
  if (status === "NO_DATA") return <CircleSlash2 aria-hidden="true" />;
  return <AlertTriangle aria-hidden="true" />;
}

export function OzonProductionAcceptanceConsole() {
  const [runId, setRunId] = useState("");
  const [storeRef, setStoreRef] = useState("");
  const [asOf, setAsOf] = useState("");
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState("");
  const [data, setData] = useState<OzonProductionAcceptance | null>(null);
  const requestSequence = useRef(0);

  async function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanRunId = runId.trim();
    const cleanStoreRef = storeRef.trim();
    if (!cleanRunId || !cleanStoreRef) {
      setError("需要填写 run ID 和店铺引用。");
      setState("error");
      return;
    }
    if (cleanRunId.length > 300 || cleanRunId.includes("\n")) {
      setError("run ID 长度或格式不合法。");
      setState("error");
      return;
    }
    const cleanAsOf = asOf.trim();
    if (cleanAsOf) {
      if (!isTimezoneIsoTimestamp(cleanAsOf) || Date.parse(cleanAsOf) > Date.now()) {
        setError("as_of 必须是当前或过去的、包含时区的 ISO-8601 时间。");
        setState("error");
        return;
      }
    }
    const sequence = ++requestSequence.current;
    setState("loading");
    setError("");
    setData(null);
    let sessionResponse;
    try {
      sessionResponse = await fetchJson("/auth/session", { cache: "no-store" });
    } catch {
      if (sequence === requestSequence.current) {
        setError("Web 身份服务读取失败。");
        setState("error");
      }
      return;
    }
    if (sequence !== requestSequence.current) return;
    if (sessionResponse.status === 401) {
      window.location.assign(`/login?next=${encodeURIComponent("/ozon/production-acceptance")}`);
      return;
    }
    if (sessionResponse.status === 428) {
      window.location.assign(`/mfa?next=${encodeURIComponent("/ozon/production-acceptance")}`);
      return;
    }
    const sessionBody = await sessionResponse.json().catch(() => null);
    const sessionValidation = validateWebSession(sessionBody);
    if (!sessionResponse.ok || !sessionValidation.ok) {
      setError(sessionValidation.ok ? "当前 Web 身份不可用。" : sessionValidation.reason);
      setState("error");
      return;
    }
    if (!sessionValidation.value.store_refs.includes(cleanStoreRef)) {
      setError(`当前身份未获授权访问店铺 ${cleanStoreRef}；未发送 Ozon 验收请求。`);
      setState("error");
      return;
    }
    const params = new URLSearchParams({ store_ref: cleanStoreRef });
    if (cleanAsOf) params.set("as_of", cleanAsOf);
    const response = await fetchJson(
      `/backend/v1/ozon/production-acceptance/${encodeURIComponent(cleanRunId)}?${params.toString()}`,
      { cache: "no-store" },
    );
    if (sequence !== requestSequence.current) return;
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string };
      setError(body.detail ?? `验收接口返回 HTTP ${response.status}`);
      setState("error");
      return;
    }
    try {
      setData(parseOzonProductionAcceptance(await response.json()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "验收响应格式无效；本轮结果已清空。");
      setState("error");
      return;
    }
    setState("loaded");
  }

  return (
    <main className={styles.page} data-gate-status={data?.gate_status ?? "idle"}>
      <header className={styles.topbar}>
        <Link href="/channel-accounts"><ArrowLeft size={15} /> 渠道账户</Link>
        <div className={styles.productMark}><span><ShieldCheck size={18} /></span><div><strong>Ozon 外部事实验收</strong><small>READBACK · EVIDENCE · GATE</small></div></div>
        <span className={styles.readOnly}><LockKeyhole size={14} /> NON-SECRET · READ ONLY</span>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}><ShieldCheck size={15} /> OFFICIAL SELLER API OBSERVATION</span>
          <h1>先证明回读事实，<em>再谈生产可用</em></h1>
          <p>这里查看同一租户、主体和店铺作用域下的 Ozon 官方回读。页面只消费服务端验收投影，不读取凭据、不联系 Ozon、不创建 Permit，也不执行外部写入。</p>
        </div>
        <aside data-state={state}>
          <strong>{state === "loading" ? "读取中" : state === "error" ? "读取失败" : data?.gate_status ?? "等待 run ID"}</strong>
          <p>{data?.next_action ?? "输入已完成的只读 Pilot Run 后查询验收。"}</p>
        </aside>
      </section>

      <form className={styles.query} onSubmit={load}>
        <label>只读 Run ID<input value={runId} onChange={(event) => setRunId(event.target.value)} placeholder="ror_…" required /></label>
        <label>已授权店铺引用<input value={storeRef} onChange={(event) => setStoreRef(event.target.value)} placeholder="从 /auth/session 选择已授权店铺" required /></label>
        <label>As of（可选）<input value={asOf} onChange={(event) => setAsOf(event.target.value)} placeholder="2026-09-07T12:00:00+08:00" /></label>
        <button type="submit" disabled={state === "loading"}><RefreshCw size={15} /> 查询只读验收</button>
      </form>

      {state === "loading" ? <section className={styles.notice} aria-live="polite"><RefreshCw size={18} /> 正在读取服务端验收投影…</section> : null}
      {state === "error" ? <section className={styles.error} role="alert"><AlertTriangle size={19} /><div><strong>验收投影不可用</strong><p>{error}</p></div></section> : null}

      {data ? <>
        <section className={styles.gate} aria-label="生产验收状态">
          <div className={styles.gateIcon} data-status={data.gate_status}><GateIcon status={data.gate_status} /></div>
          <div><span>GATE STATUS</span><h2>{data.gate_status}</h2><p>{data.accepted ? "外部观察可以进入受控重放。" : "当前观察不能证明生产可用，必须先修复阻断。"}</p></div>
          <dl><div><dt>external write</dt><dd>false</dd></div><div><dt>fact promotion</dt><dd>false</dd></div><div><dt>release</dt><dd>false</dd></div></dl>
        </section>

        <section className={styles.grid}>
          <article><h3>作用域</h3><dl><div><dt>tenant</dt><dd>{data.scope.tenant_ref}</dd></div><div><dt>entity</dt><dd>{data.scope.entity_ref ?? "no_data"}</dd></div><div><dt>store</dt><dd>{data.scope.store_ref}</dd></div><div><dt>authority</dt><dd>{shortHash(data.scope.scope_grant_authority_sha256)}</dd></div></dl></article>
          <article><h3>服务端检查</h3><ul>{Object.entries(data.checks).map(([name, passed]) => <li key={name} data-passed={passed}>{passed ? "✓" : "!"} {name}</li>)}</ul></article>
          <article><h3>阻断</h3>{data.blockers.length ? <ul className={styles.blockers}>{data.blockers.map((blocker) => <li key={blocker}><AlertTriangle size={14} /> {blocker}</li>)}</ul> : <p>无阻断</p>}</article>
        </section>

        <section className={styles.grid}>
          <article><h3>只读 Run</h3>{data.run ? <dl><div><dt>id</dt><dd>{data.run.id}</dd></div><div><dt>operation</dt><dd>{data.run.operation}</dd></div><div><dt>outcome</dt><dd>{data.run.outcome ?? "—"}</dd></div><div><dt>response</dt><dd>{shortHash(data.run.response_sha256)}</dd></div><div><dt>bytes</dt><dd>{valueLabel(data.run.response_byte_size)}</dd></div><div><dt>raw Evidence</dt><dd>{data.run.raw_response_evidence_id ?? "—"}</dd></div></dl> : <p>没有可用 Run。</p>}</article>
          <article><h3>渠道运行身份</h3>{data.runtime_identity ? <dl><div><dt>account</dt><dd>{data.runtime_identity.account_ref ?? "—"}</dd></div><div><dt>state</dt><dd>{data.runtime_identity.state ?? "—"}</dd></div><div><dt>runtime</dt><dd>{data.runtime_identity.runtime_status ?? "—"}</dd></div><div><dt>capability</dt><dd>{data.runtime_identity.required_capability ?? "—"}</dd></div><div><dt>provider readback</dt><dd>{String(data.runtime_identity.provider_readback_fresh_passed)}</dd></div><div><dt>external verifier</dt><dd>{String(data.runtime_identity.external_verifier_fresh_passed)}</dd></div></dl> : <p>运行身份不可用。</p>}</article>
          <article><h3>证据与合同</h3><dl><div><dt>Evidence IDs</dt><dd>{data.evidence_ids.join(", ") || "—"}</dd></div><div><dt>source contract</dt><dd>{valueLabel(data.source_contract?.contract_version)}</dd></div><div><dt>snapshot</dt><dd>{shortHash(data.snapshot_sha256)}</dd></div><div><dt>credentials returned</dt><dd>false</dd></div></dl></article>
        </section>
      </> : null}
    </main>
  );
}
