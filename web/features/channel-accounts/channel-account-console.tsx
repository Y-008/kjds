"use client";

import {
  ArrowLeft,
  Bot,
  CircleAlert,
  Fingerprint,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Store,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  channelAccountView,
  transitionChannelAccountState,
  type ChannelAccountViewStatus,
} from "../../lib/channel-account-state";
import type {
  ChannelAccount,
  ChannelAccountFilterDraft,
  ChannelAccountGovernanceCommandType,
  ChannelAccountGovernanceDraft,
  ChannelAccountGovernanceTransition,
  ChannelAccountState,
  ChannelAccountWorkspace,
} from "./contracts";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./channel-account.module.css";

const states: ChannelAccountState[] = [
  "ready",
  "revoked",
  "expired",
  "verification_stale",
  "health_blocked",
  "rate_limited",
  "schema_drift",
  "unknown_outcome",
  "evidence_blocked",
];

const initialFilters: ChannelAccountFilterDraft = {
  storeRef: "ozon-primary",
  platform: "",
  accountRef: "",
  adapterId: "",
  query: "",
  state: "",
};

const labels: Record<string, string> = {
  ready: "权威可用",
  blocked: "失败关闭",
  no_data: "真实 no_data",
  loading: "读取中",
  error: "读取失败",
  revoked: "已撤销",
  expired: "已过期",
  verification_stale: "复验过期",
  health_blocked: "连接健康阻断",
  rate_limited: "平台限流",
  schema_drift: "外部 schema 漂移",
  unknown_outcome: "结果不确定",
  evidence_blocked: "Evidence 阻断",
};

function label(value: string | null | undefined) {
  return labels[value ?? ""] ?? value ?? "—";
}

function shortHash(value: string | null | undefined) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "—";
}

function booleanMark(value: boolean) {
  return value ? "passed" : "blocked";
}

function hasFilters(filters: ChannelAccountFilterDraft) {
  return Boolean(
    filters.platform ||
      filters.accountRef ||
      filters.adapterId ||
      filters.query ||
      filters.state,
  );
}

function AccountCard({ account }: { account: ChannelAccount }) {
  const identityChecks = [
    ["managed store", account.runtime_identity.managed_store_bound],
    ["lease fresh", account.runtime_identity.lease_fresh],
    ["fingerprint", account.runtime_identity.fingerprint_match],
    ["scope", account.runtime_identity.scope_match],
    ["capabilities", account.runtime_identity.capabilities_match],
    ["provider readback", account.runtime_identity.provider_readback_fresh_passed],
    ["external verifier", account.runtime_identity.external_verifier_fresh_passed],
  ] as const;
  return (
    <article className={styles.account} data-state={account.state} data-testid="channel-account-row">
      <header className={styles.accountHeader}>
        <div>
          <span>{account.platform.toUpperCase()} · READ ONLY</span>
          <h2>{account.account_ref}</h2>
          <p>
            {account.role_ref ?? "role no_data"} · {account.subaccount_ref ?? "subaccount no_data"}
          </p>
        </div>
        <strong>{label(account.state)}</strong>
      </header>

      <section className={styles.identityGrid}>
        <div>
          <span>Adapter</span>
          <b>{account.adapter.adapter_id}@{account.adapter.adapter_version}</b>
          <small>{account.adapter.authorization_source ?? "authorization source no_data"}</small>
        </div>
        <div>
          <span>Credential kind</span>
          <b>{account.credential_kind ?? "no_data"}</b>
          <small>reference value returned: false</small>
        </div>
        <div>
          <span>Credential fingerprint</span>
          <b>{shortHash(account.credential_fingerprint_sha256)}</b>
          <small>non-secret SHA-256 only</small>
        </div>
        <div>
          <span>Reference fingerprint</span>
          <b>{shortHash(account.credential_reference.sha256)}</b>
          <small>present {String(account.credential_reference.present)}</small>
        </div>
      </section>

      <section className={styles.capabilities} aria-label="只读 capabilities">
        <span>CAPABILITIES</span>
        <div>
          {account.capabilities.length ? account.capabilities.map((capability) => (
            <code key={capability}>{capability}</code>
          )) : <code>no_data</code>}
        </div>
      </section>

      <section className={styles.accountDetails}>
        <div>
          <h3>Rotation / Revocation lifecycle</h3>
          <dl>
            <div><dt>latest event</dt><dd>{account.lifecycle.latest_event_type ?? "no_data"}</dd></div>
            <div><dt>sequence</dt><dd>{account.lifecycle.latest_sequence ?? "—"}</dd></div>
            <div><dt>effective</dt><dd>{account.lifecycle.latest_effective_at ?? "—"}</dd></div>
            <div><dt>events</dt><dd>{account.lifecycle.event_count}</dd></div>
          </dl>
        </div>
        <div>
          <h3>Health / Readback</h3>
          <dl>
            <div><dt>health</dt><dd>{label(account.health.status)}</dd></div>
            <div><dt>rate limit</dt><dd>{label(account.health.rate_limit_state)}</dd></div>
            <div><dt>readback</dt><dd>{label(account.health.readback_outcome)}</dd></div>
            <div><dt>schema</dt><dd>{account.health.external_schema_version ?? "—"}</dd></div>
            <div><dt>verified</dt><dd>{account.health.last_verified_at ?? "—"}</dd></div>
            <div><dt>expires</dt><dd>{account.health.expires_at ?? "—"}</dd></div>
          </dl>
        </div>
      </section>

      <section className={styles.runtimeIdentity}>
        <header>
          <div><Fingerprint size={17} /><strong>Runtime identity</strong></div>
          <span>{account.runtime_identity.status ?? "no_data"}</span>
        </header>
        <div>
          {identityChecks.map(([name, passed]) => (
            <span key={name} data-check={booleanMark(passed)}>{name} · {booleanMark(passed)}</span>
          ))}
        </div>
        <small>{account.runtime_identity.contract_id ?? "runtime verifier contract no_data"}</small>
      </section>

      <section className={styles.governance}>
        <h3>Approval / Permit / Readback / Kill Switch / Compensation</h3>
        {Object.entries(account.governance).map(([key, value]) => (
          <span key={key}>{key}: <code>{value ?? "not created"}</code></span>
        ))}
      </section>

      <section className={styles.evidenceLineage}>
        <span>Evidence <code>{account.latest_evidence_id ?? "no_data"}</code></span>
        <span>payload <code>{shortHash(account.latest_payload_sha256)}</code></span>
        <span>adapter contract <code>{shortHash(account.adapter.adapter_contract_sha256)}</code></span>
      </section>

      {account.source_gaps.length ? (
        <section className={styles.accountGaps}>
          <CircleAlert size={17} />
          <div><strong>Source gaps</strong>{account.source_gaps.map((gap) => <code key={gap}>{gap}</code>)}</div>
        </section>
      ) : null}
      <footer><strong>Next</strong><p>{account.next}</p></footer>
    </article>
  );
}

const initialGovernanceDraft: ChannelAccountGovernanceDraft = {
  storeRef: "ozon-primary",
  platform: "ozon",
  accountRef: "",
  changeKind: "grant_read_capability",
  capabilities: "catalog.read",
  effectiveUntil: "",
  submitIdempotencyKey: "",
  submissionEvidenceId: "",
  reviewAccepted: true,
  reviewRationale: "",
  reviewedEvidenceId: "",
  approvalId: "",
  decisionApproved: true,
  decisionReason: "",
  planIdempotencyKey: "",
};

type GovernanceRequest = {
  store_ref: string;
  command: { type: ChannelAccountGovernanceCommandType; payload: Record<string, unknown> };
};

function ChannelAccountGovernanceWorkbench() {
  const [draft, setDraft] = useState(initialGovernanceDraft);
  const [transition, setTransition] = useState<ChannelAccountGovernanceTransition | null>(null);
  const [pending, setPending] = useState<ChannelAccountGovernanceCommandType | null>(null);
  const [lastRequest, setLastRequest] = useState<GovernanceRequest | null>(null);
  const [error, setError] = useState("");

  const send = useCallback(async (request: GovernanceRequest) => {
    setPending(request.command.type);
    setError("");
    setLastRequest(request);
    try {
      const response = await fetchJson<ChannelAccountGovernanceTransition>("/backend/v1/channel-account-governance/transitions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { detail?: string };
        throw new Error(body.detail ?? `Governance transition ${response.status}`);
      }
      const value = await response.json();
      setTransition(value);
      setDraft((current) => ({
        ...current,
        submissionEvidenceId: value.canonical_refs.submission_evidence_id ?? current.submissionEvidenceId,
        reviewedEvidenceId: value.canonical_refs.review_evidence_id ?? current.reviewedEvidenceId,
        approvalId: value.canonical_refs.approval_id ?? current.approvalId,
      }));
    } catch (value) {
      setError(value instanceof Error ? value.message : "内部治理转换失败");
    } finally {
      setPending(null);
    }
  }, []);

  function submitProposal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const requestedCapabilities = draft.capabilities.split(",").map((value) => value.trim()).filter(Boolean);
    void send({
      store_ref: draft.storeRef.trim(),
      command: {
        type: "submit_evidence",
        payload: {
          purpose: "change_proposal",
          effective_at: new Date().toISOString(),
          effective_until: draft.effectiveUntil
            ? new Date(draft.effectiveUntil).toISOString()
            : null,
          idempotency_key: draft.submitIdempotencyKey.trim(),
          semantic_metadata: { change_kind: draft.changeKind.trim() },
          canonical_payload: {
            contract_id: "kjds-channel-account-change-proposal-v1",
            platform: draft.platform.trim().toLowerCase(),
            account_ref: draft.accountRef.trim(),
            change_kind: draft.changeKind.trim(),
            requested_capabilities: requestedCapabilities,
          },
        },
      },
    });
  }

  const command = (type: ChannelAccountGovernanceCommandType, payload: Record<string, unknown>) => {
    void send({ store_ref: draft.storeRef.trim(), command: { type, payload } });
  };

  return <section className={styles.governanceWorkbench} aria-label="渠道账户内部治理状态机">
    <header><div><ShieldCheck size={20} /><div><span>INTERNAL GOVERNANCE · HUMAN SOD</span><h2>渠道账户变更治理接力</h2></div></div><strong>provider execution disabled</strong></header>
    <p className={styles.governanceBoundary}>这里只写入内部 Evidence、Approval 与 execution-gated Plan。不同认证人员必须分别提交、复核、决定；不会创建 Permit、读取凭据、联系平台或执行外部写。</p>

    <form className={styles.governanceForm} onSubmit={submitProposal}>
      <h3>1 · 提交 typed change proposal</h3>
      <label>Store<input value={draft.storeRef} onChange={(event) => setDraft({ ...draft, storeRef: event.target.value })} required /></label>
      <label>Platform<input value={draft.platform} onChange={(event) => setDraft({ ...draft, platform: event.target.value })} required /></label>
      <label>Account reference<input value={draft.accountRef} onChange={(event) => setDraft({ ...draft, accountRef: event.target.value })} required /></label>
      <label>Change kind<input value={draft.changeKind} onChange={(event) => setDraft({ ...draft, changeKind: event.target.value })} required /></label>
      <label>Read capabilities<input value={draft.capabilities} onChange={(event) => setDraft({ ...draft, capabilities: event.target.value })} placeholder="catalog.read, finance.read" required /></label>
      <label>Effective until<input type="datetime-local" value={draft.effectiveUntil} onChange={(event) => setDraft({ ...draft, effectiveUntil: event.target.value })} /></label>
      <label>Idempotency key<input value={draft.submitIdempotencyKey} onChange={(event) => setDraft({ ...draft, submitIdempotencyKey: event.target.value })} required /></label>
      <button disabled={pending !== null} type="submit">提交 Evidence proposal</button>
    </form>

    <div className={styles.governanceSteps}>
      <section><h3>2 · 独立 Evidence review</h3><label>Submission Evidence ID<input value={draft.submissionEvidenceId} onChange={(event) => setDraft({ ...draft, submissionEvidenceId: event.target.value })} /></label><label>Rationale<textarea value={draft.reviewRationale} onChange={(event) => setDraft({ ...draft, reviewRationale: event.target.value })} /></label><label className={styles.inlineCheck}><input type="checkbox" checked={draft.reviewAccepted} onChange={(event) => setDraft({ ...draft, reviewAccepted: event.target.checked })} />接受该证据</label><button disabled={pending !== null} onClick={() => command("review_evidence", { submission_evidence_id: draft.submissionEvidenceId.trim(), accepted: draft.reviewAccepted, rationale: draft.reviewRationale.trim() })}>独立复核</button></section>
      <section><h3>3 · Request Approval</h3><label>Reviewed Evidence ID<input value={draft.reviewedEvidenceId} onChange={(event) => setDraft({ ...draft, reviewedEvidenceId: event.target.value })} /></label><p>申请人必须不同于 Evidence submitter 和 reviewer。</p><button disabled={pending !== null} onClick={() => command("request_change_approval", { reviewed_evidence_id: draft.reviewedEvidenceId.trim() })}>申请独立 Approval</button></section>
      <section><h3>4 · Independent decision</h3><label>Approval ID<input value={draft.approvalId} onChange={(event) => setDraft({ ...draft, approvalId: event.target.value })} /></label><label>Reason<textarea value={draft.decisionReason} onChange={(event) => setDraft({ ...draft, decisionReason: event.target.value })} /></label><label className={styles.inlineCheck}><input type="checkbox" checked={draft.decisionApproved} onChange={(event) => setDraft({ ...draft, decisionApproved: event.target.checked })} />批准内部计划</label><button disabled={pending !== null} onClick={() => command("decide_change_approval", { approval_id: draft.approvalId.trim(), approved: draft.decisionApproved, reason: draft.decisionReason.trim() })}>提交独立决定</button></section>
      <section><h3>5 · Materialize internal plan</h3><label>Approval ID<input value={draft.approvalId} onChange={(event) => setDraft({ ...draft, approvalId: event.target.value })} /></label><label>Plan idempotency key<input value={draft.planIdempotencyKey} onChange={(event) => setDraft({ ...draft, planIdempotencyKey: event.target.value })} /></label><p>结果固定为 execution_gated；不生成 Permit，不联系 provider。</p><button disabled={pending !== null} onClick={() => command("materialize_internal_plan", { approval_id: draft.approvalId.trim(), idempotency_key: draft.planIdempotencyKey.trim() })}>生成内部 gated Plan</button></section>
    </div>

    {pending ? <div className={styles.governanceNotice}><RefreshCw size={17} />正在提交 {pending}…</div> : null}
    {error ? <div className={styles.governanceError}><CircleAlert size={18} /><div><strong>转换失败</strong><p>{error}</p></div>{lastRequest ? <button onClick={() => void send(lastRequest)}>按相同 payload 重试</button> : null}</div> : null}
    {transition ? <div className={styles.transitionReceipt}><header><strong>{transition.from_state} → {transition.to_state}</strong><code>{transition.transition_id}</code></header><div><span>submission <code>{transition.canonical_refs.submission_evidence_id ?? "—"}</code></span><span>review <code>{transition.canonical_refs.review_evidence_id ?? "—"}</code></span><span>approval <code>{transition.canonical_refs.approval_id ?? "—"}</code></span><span>plan <code>{transition.canonical_refs.execution_plan_id ?? "—"}</code></span></div><footer><code>permit_created=false</code><code>credential_created_or_read=false</code><code>provider_contact_allowed=false</code><code>external_write_allowed=false</code></footer></div> : null}
  </section>;
}

export function ChannelAccountConsole() {
  const [workspace, setWorkspace] = useState<ChannelAccountWorkspace | null>(null);
  const [status, setStatus] = useState<ChannelAccountViewStatus>("loading");
  const [filters, setFilters] = useState<ChannelAccountFilterDraft>(initialFilters);
  const [appliedFilters, setAppliedFilters] = useState<ChannelAccountFilterDraft>(initialFilters);
  const [error, setError] = useState("");

  const load = useCallback(async (cursor?: string | null, signal?: AbortSignal) => {
    setStatus((current) => transitionChannelAccountState(current, { type: "request" }));
    setError("");
    try {
      const params = new URLSearchParams({
        store_ref: appliedFilters.storeRef,
        page_size: "25",
      });
      if (appliedFilters.platform) params.set("platform", appliedFilters.platform);
      if (appliedFilters.accountRef) params.set("account_ref", appliedFilters.accountRef);
      if (appliedFilters.adapterId) params.set("adapter_id", appliedFilters.adapterId);
      if (appliedFilters.query) params.set("query", appliedFilters.query);
      if (appliedFilters.state) params.set("state", appliedFilters.state);
      if (cursor) params.set("cursor", cursor);
      const response = await fetch(`/backend/v1/channel-accounts/workspace?${params}`, {
        cache: "no-store",
        signal,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { detail?: string };
        throw new Error(body.detail ?? `Channel Account API ${response.status}`);
      }
      const value = await response.json() as ChannelAccountWorkspace;
      setWorkspace(value);
      setStatus((current) => transitionChannelAccountState(current, {
        type: "success",
        status: value.status,
      }));
    } catch (value) {
      if (value instanceof DOMException && value.name === "AbortError") return;
      setError(value instanceof Error ? value.message : "读取失败");
      setStatus((current) => transitionChannelAccountState(current, { type: "failure" }));
    }
  }, [appliedFilters]);

  useEffect(() => {
    const controller = new AbortController();
    void load(null, controller.signal);
    return () => controller.abort("channel account filters changed");
  }, [load]);

  const view = channelAccountView(
    status,
    workspace?.channel_accounts.length ?? 0,
    hasFilters(appliedFilters),
  );
  const denialFlags = useMemo(() => workspace ? [
    ...Object.entries(workspace.agent_artifact).filter(([key]) => key.endsWith("_allowed")),
    ...Object.entries(workspace.control_envelope).filter(([key]) =>
      key.endsWith("_allowed") || key.endsWith("_returned") || key.endsWith("_stored"),
    ),
    ["projection_grants_permission", workspace.governed_action_contract.projection_grants_permission],
    ["provider_mutation_api_exposed", workspace.governed_action_contract.provider_mutation_api_exposed],
    ["provider_mutation_enabled", workspace.governed_action_contract.provider_mutation_enabled],
  ] : [], [workspace]);

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setWorkspace(null);
    setAppliedFilters({
      storeRef: filters.storeRef.trim(),
      platform: filters.platform.trim().toLowerCase(),
      accountRef: filters.accountRef.trim(),
      adapterId: filters.adapterId.trim(),
      query: filters.query.trim(),
      state: filters.state,
    });
  }

  return (
    <main className={styles.page} data-authority-state={view.domState}>
      <header className={styles.topbar}>
        <Link href="/commerce-os"><ArrowLeft size={15} /> Commerce OS</Link>
        <div className={styles.productMark}>
          <span><Store size={18} /></span>
          <div><strong>Channel Accounts</strong><small>EXACT-SCOPE AUTHORITY</small></div>
        </div>
        <span className={styles.topBoundary}><LockKeyhole size={14} /> NON-SECRET · READ ONLY</span>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}><ShieldCheck size={15} /> NATIVE CHANNEL IDENTITY</span>
          <h1>渠道账户与运行身份，<em>只认当前 exact scope</em></h1>
          <p>
            服务端组合 Scope Grant、官方或书面授权的 Adapter Evidence、非秘密凭据指纹、
            rotation/revocation、连接健康和只读 capabilities。页面不读取或接收 Secret、Cookie、
            内部 Token、设备 Session，也不把成功响应冒充正式授权。
          </p>
        </div>
        <aside data-state={status}>
          <Fingerprint size={25} />
          <strong>{label(status)}</strong>
          <p>{view.detail}</p>
          <small>{workspace ? `snapshot ${shortHash(workspace.snapshot_sha256)}` : "等待服务端权威"}</small>
        </aside>
      </section>

      <form className={styles.filters} onSubmit={applyFilters}>
        <label>授权店铺<input value={filters.storeRef} onChange={(event) => setFilters((current) => ({ ...current, storeRef: event.target.value }))} required /></label>
        <label>平台<input value={filters.platform} onChange={(event) => setFilters((current) => ({ ...current, platform: event.target.value }))} placeholder="ozon" /></label>
        <label>账户引用<input value={filters.accountRef} onChange={(event) => setFilters((current) => ({ ...current, accountRef: event.target.value }))} placeholder="账户别名或官方 ID" /></label>
        <label>Adapter<input value={filters.adapterId} onChange={(event) => setFilters((current) => ({ ...current, adapterId: event.target.value }))} placeholder="ozon-seller-read" /></label>
        <label>搜索<input value={filters.query} onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))} placeholder="角色、子账户或 capability" /></label>
        <label>状态<select value={filters.state} onChange={(event) => setFilters((current) => ({ ...current, state: event.target.value as ChannelAccountFilterDraft["state"] }))}><option value="">全部</option>{states.map((state) => <option value={state} key={state}>{label(state)}</option>)}</select></label>
        <button type="submit"><RefreshCw size={15} /> 应用服务端筛选</button>
      </form>

      {view.showLoading ? <section className={styles.notice} data-testid="channel-account-loading"><RefreshCw size={19} /><div><strong>{view.heading}</strong><p>{view.detail}</p></div></section> : null}
      {view.showRetry ? <section className={styles.error} data-testid="channel-account-error"><CircleAlert size={20} /><div><strong>{view.heading}</strong><p>{error || view.detail}</p></div><button type="button" onClick={() => void load(null)}><RefreshCw size={15} /> 重试</button></section> : null}

      {workspace && status !== "loading" && status !== "error" ? <>
        <section className={styles.scopeBar}>
          <div><span>Tenant</span><strong>{workspace.scope.tenant_ref}</strong></div>
          <div><span>Entity</span><strong>{workspace.scope.entity_ref ?? "no_data"}</strong></div>
          <div><span>Store</span><strong>{workspace.scope.store_ref}</strong></div>
          <div><span>As of</span><strong>{workspace.as_of}</strong></div>
          <div><span>Scope authority</span><code>{shortHash(workspace.scope.scope_grant_authority_sha256)}</code></div>
        </section>

        <section className={styles.metrics} aria-label="服务端权威计数">
          {Object.entries(workspace.counts).map(([key, value]) => <article key={key}><span>{label(key)}</span><strong>{value}</strong></article>)}
          <article><span>filtered</span><strong>{workspace.pagination.filtered_total}</strong></article>
        </section>

        <section className={styles.filterSnapshot}>
          <strong>Server filters</strong>
          {Object.entries(workspace.filters).map(([key, value]) => <span key={key}>{key}: <code>{value ?? "all"}</code></span>)}
        </section>

        {workspace.source_gaps.length ? <section className={styles.gapPanel}><CircleAlert size={20} /><div><strong>Workspace source gaps</strong><p>任何缺口都保持 no_data / blocked，不回退旧授权。</p><div>{workspace.source_gaps.map((gap) => <code key={gap}>{gap}</code>)}</div></div></section> : null}

        {view.showEmpty ? <section className={styles.empty} data-testid={`channel-account-${status}`}><LockKeyhole size={23} /><div><h2>{view.heading}</h2><p>{view.detail}</p></div></section> : null}
        {view.showRows ? <section className={styles.accountList}>{workspace.channel_accounts.map((account) => <AccountCard key={`${account.platform}:${account.account_ref}:${account.adapter.adapter_id}:${account.adapter.adapter_version}`} account={account} />)}</section> : null}

        {workspace.pagination.next_cursor ? <section className={styles.pagination}><span>本页 {workspace.channel_accounts.length} · filtered {workspace.pagination.filtered_total}</span><button type="button" onClick={() => void load(workspace.pagination.next_cursor)}>下一页</button></section> : null}

        <section className={styles.agentArtifact}>
          <header><div><Bot size={20} /><div><span>AGENT ARTIFACT</span><h2>只建议修复与内部任务</h2></div></div><code>{shortHash(workspace.agent_artifact.artifact_sha256)}</code></header>
          <p>{workspace.agent_artifact.authority}</p>
          <div>{workspace.agent_artifact.accounts.length ? workspace.agent_artifact.accounts.map((account) => <article key={`${account.platform}:${account.account_ref}`}><strong>{account.platform} · {account.account_ref}</strong><span>{label(account.state)}</span><p>{account.next}</p></article>) : <span>no_data · 没有生成虚构修复建议</span>}</div>
        </section>

        <section className={styles.governedActions}>
          <div><ShieldCheck size={19} /><div><span>GOVERNED ACTIONS</span><h2>投影不授予权限</h2></div></div>
          <p>动作：{workspace.governed_action_contract.actions.join(" · ")}</p>
          <p>前置：{workspace.governed_action_contract.requires.join(" · ")}</p>
          <p>
            {workspace.governed_action_contract.production_workflow_status} · {workspace.governed_action_contract.policy_mode} · contract_only={String(workspace.governed_action_contract.contract_only)}
          </p>
        </section>

      <section className={styles.denials} aria-label="全部禁止动作">
          <header><LockKeyhole size={20} /><div><span>DENY BY DEFAULT</span><h2>全部禁止动作与敏感输入边界</h2></div></header>
          <div>{denialFlags.map(([name, value], index) => <span key={`${name}:${index}`}><code>{name}</code><b>{String(value)}</b></span>)}</div>
          <p>
            reauthorization_allowed=false · credential_rotation_allowed=false · secret_read_allowed=false ·
            scope_expansion_allowed=false · authorization_change_allowed=false · self_approval_allowed=false ·
            permit_issue_allowed=false · external_verification_allowed=false · customer_contact_allowed=false ·
            platform_contact_allowed=false · fictional_authority_allowed=false · secret_reference_returned=false ·
            plaintext_secret_stored=false · cookie_allowed=false · internal_token_allowed=false ·
            device_session_allowed=false · private_endpoint_allowed=false · captcha_bypass_allowed=false ·
            access_control_bypass_allowed=false · projection_grants_permission=false · external_write_allowed=false
            · internal_governance_api_exposed=true · provider_mutation_api_exposed=false · provider_mutation_enabled=false
          </p>
      </section>

      <ChannelAccountGovernanceWorkbench />

      <footer className={styles.audit}>
          <code>snapshot {workspace.snapshot_sha256}</code>
          <code>artifact {workspace.agent_artifact.artifact_sha256}</code>
          {Object.entries(workspace.upstream).map(([key, value]) => <code key={key}>{key} {value ?? "no_data"}</code>)}
          <p>native implementation {workspace.native_implementation_status} · verified native {String(workspace.verified_native)}</p>
        </footer>
      </> : null}
    </main>
  );
}
