"use client";

import Link from "next/link";
import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./authority-intake-workbench.module.css";

type WebSession = {
  authenticated: boolean;
  auth_mode: "legacy" | "supabase";
  email: string | null;
  actor_id: string;
  roles: string[];
};

type AuthorityTopology = {
  contract_id: "kjds-authority-workflow-topology-v1";
  verifier: { id: string; version: string; authority: string };
  state: "passed" | "blocked" | "failed";
  freshness: "fresh";
  observed_at: string;
  fresh_until: string;
  as_of: string;
  scope: { tenant_ref: string; store_ref: string };
  auth_mode: "legacy" | "supabase";
  counts: {
    registered_actors: number;
    exact_scope_actors: number;
    web_user_bindings: number;
    api_chains: number;
    web_chains: number;
  };
  selected_api_chain: {
    subject_actor_id: string;
    owner_actor_id: string;
    reviewer_actor_id: string;
    recorder_actor_id: string;
  } | null;
  api_chain_ready: boolean;
  web_chain_ready: boolean;
  blocker_codes: string[];
  why: string;
  next_safe_action: string;
  owner: string;
  sla_seconds: number;
  input_sha256: string;
  result_sha256: string;
  role_switch_allowed: false;
  grant_created: false;
  external_write_allowed: false;
};

type Review = {
  id: string;
  sha256: string;
  decision: "accepted" | "rejected";
  reviewed_by: string;
  effective_at: string;
  recorded_at: string;
  lineage_verified: true;
};

type Candidate = {
  source_evidence_id: string;
  source_evidence_sha256: string;
  owner_actor_id: string;
  effective_at: string;
  recorded_at: string;
  review_state: string;
  reviews: Review[];
  accepted_review_evidence_id: string | null;
  can_current_actor_review: boolean;
  can_current_actor_preflight: boolean;
};

type Intake = {
  contract_id: "kjds-scope-authority-intake-v1";
  verifier: { id: string; version: string; authority: string };
  state: string;
  freshness: string;
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    subject_actor_id: string;
    event_type: "grant" | "revoke";
  };
  requester: { actor_id: string; roles: string[] };
  allowed_actions: {
    submit_source: boolean;
    review_source: boolean;
    run_preflight: boolean;
    record_grant: false;
  };
  formal_authority: {
    status: string;
    entity_ref: string | null;
    authority_sha256: string | null;
    reason?: string;
  };
  candidates: Candidate[];
  counts: {
    sources: number;
    reviews: number;
    ready_for_preflight: number;
    invalid_sources: number;
    invalid_reviews: number;
  };
  blocker_codes: string[];
  why: string;
  owner: string;
  sla_seconds: number;
  next_safe_action: string;
  grant_endpoint_exposed: false;
  grant_created: false;
  external_write_allowed: false;
  snapshot_sha256: string;
};

type MutationResult = {
  state?: string;
  detail?: string;
  snapshot_sha256?: string;
  source_evidence_id?: string;
  review_evidence_id?: string;
  blocker_codes?: string[];
  why?: string;
};

function errorMessage(result: MutationResult, fallback: string) {
  return result.detail ?? result.why ?? fallback;
}

function currentIso() {
  return new Date().toISOString();
}

export function AuthorityIntakeWorkbench() {
  const [session, setSession] = useState<WebSession | null>(null);
  const [intake, setIntake] = useState<Intake | null>(null);
  const [topology, setTopology] = useState<AuthorityTopology | null>(null);
  const [entityRef, setEntityRef] = useState("");
  const [subjectActorId, setSubjectActorId] = useState("");
  const [eventType, setEventType] = useState<"grant" | "revoke">("grant");
  const [effectiveAt, setEffectiveAt] = useState(currentIso);
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [selectedReviewId, setSelectedReviewId] = useState("");
  const [notice, setNotice] = useState("正在读取真实身份与 Authority verifier…");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(
    async (
      nextEntity = "",
      nextSubject = "",
      nextEvent: "grant" | "revoke" = "grant",
    ) => {
      setBusy("load");
      const query = new URLSearchParams({
        store_ref: "ozon-primary",
        event_type: nextEvent,
      });
      if (nextEntity.trim()) query.set("entity_ref", nextEntity.trim());
      if (nextSubject.trim()) {
        query.set("subject_actor_id", nextSubject.trim());
      }
      const [sessionResponse, topologyResponse, intakeResponse] = await Promise.all([
        fetchJson<WebSession>("/auth/session"),
        fetchJson<AuthorityTopology>("/auth/authority-topology"),
        fetchJson<Intake>(`/backend/v1/scope-grants/intake?${query}`),
      ]);
      const sessionBody = await sessionResponse.json();
      const topologyBody = await topologyResponse.json();
      const intakeBody = await intakeResponse.json();
      if (sessionResponse.ok) {
        setSession(sessionBody);
        setSubjectActorId((value) => value || sessionBody.actor_id);
      }
      if (topologyResponse.ok) {
        setTopology(topologyBody);
      } else {
        setTopology(null);
      }
      if (intakeResponse.ok) {
        setIntake(intakeBody);
        setNotice(
          `${intakeBody.state} · ${intakeBody.why}`,
        );
        const source = intakeBody.candidates[0];
        if (source) {
          setSelectedSourceId((value) => value || source.source_evidence_id);
          if (source.accepted_review_evidence_id) {
            setSelectedReviewId(
              (value) => value || source.accepted_review_evidence_id || "",
            );
          }
        }
      } else {
        const failure = intakeBody as unknown as MutationResult;
        setNotice(errorMessage(failure, `Intake API ${intakeResponse.status}`));
      }
      setBusy(null);
    },
    [],
  );

  useEffect(() => {
    void load("", "", "grant");
  }, [load]);

  const selectedCandidate = useMemo(
    () =>
      intake?.candidates.find(
        (candidate) => candidate.source_evidence_id === selectedSourceId,
      ) ?? null,
    [intake, selectedSourceId],
  );

  async function submitSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = (
      form.elements.namedItem("source_file") as HTMLInputElement
    ).files?.[0];
    if (!file) {
      setNotice("请选择真实 owner authority 文件。");
      return;
    }
    const data = new FormData();
    data.set("file", file);
    data.set("entity_ref", entityRef.trim());
    data.set("store_ref", "ozon-primary");
    data.set("subject_actor_id", subjectActorId.trim());
    data.set("event_type", eventType);
    data.set("effective_at", effectiveAt.trim());
    data.set(
      "idempotency_key",
      (
        form.elements.namedItem("source_idempotency_key") as HTMLInputElement
      ).value.trim(),
    );
    const effectiveUntil = (
      form.elements.namedItem("effective_until") as HTMLInputElement
    ).value.trim();
    if (effectiveUntil) data.set("effective_until", effectiveUntil);
    setBusy("source");
    const response = await fetchJson<MutationResult>(
      "/backend/v1/scope-grants/evidence",
      { method: "POST", body: data },
    );
    const result = await response.json();
    setBusy(null);
    if (!response.ok) {
      setNotice(errorMessage(result, `Owner source ${response.status}`));
      return;
    }
    setSelectedSourceId(result.source_evidence_id ?? "");
    setNotice(
      `Owner source 已追加：${result.source_evidence_id}。正式 grant 仍未创建。`,
    );
    await load(entityRef, subjectActorId, eventType);
  }

  async function submitReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const checked = (name: string) =>
      (form.elements.namedItem(name) as HTMLInputElement).checked;
    const value = (name: string) =>
      (form.elements.namedItem(name) as HTMLInputElement).value.trim();
    setBusy("review");
    const response = await fetchJson<MutationResult>(
      "/backend/v1/scope-grants/evidence/reviews",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_evidence_id: selectedSourceId,
          entity_ref: entityRef.trim(),
          store_ref: "ozon-primary",
          subject_actor_id: subjectActorId.trim(),
          event_type: eventType,
          effective_at: effectiveAt.trim(),
          accepted: value("review_decision") === "accepted",
          authentic_original: checked("authentic_original"),
          owner_authority_verified: checked("owner_authority_verified"),
          scope_matches: checked("scope_matches"),
          rationale: value("review_rationale"),
          idempotency_key: value("review_idempotency_key"),
        }),
      },
    );
    const result = await response.json();
    setBusy(null);
    if (!response.ok) {
      setNotice(errorMessage(result, `Independent review ${response.status}`));
      return;
    }
    setSelectedReviewId(result.review_evidence_id ?? "");
    setNotice(
      `独立 review 已追加：${result.review_evidence_id}。仍未创建正式 grant。`,
    );
    await load(entityRef, subjectActorId, eventType);
  }

  async function runPreflight(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) =>
      (form.elements.namedItem(name) as HTMLInputElement).value.trim();
    setBusy("preflight");
    const response = await fetchJson<MutationResult>(
      "/backend/v1/scope-grants/preflight",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_ref: entityRef.trim(),
          store_ref: "ozon-primary",
          subject_actor_id: subjectActorId.trim(),
          event_type: eventType,
          effective_at: effectiveAt.trim(),
          evidence_id: selectedReviewId,
          reason: value("preflight_reason"),
          idempotency_key: value("preflight_idempotency_key"),
        }),
      },
    );
    const result = await response.json();
    setBusy(null);
    if (!response.ok) {
      setNotice(errorMessage(result, `Preflight ${response.status}`));
      return;
    }
    setNotice(
      `${result.state} · ${result.why ?? "零写 preflight 完成"} · grant created false`,
    );
  }

  const exactScopeReady =
    Boolean(entityRef.trim()) &&
    Boolean(subjectActorId.trim()) &&
    Boolean(effectiveAt.trim());

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p>IDENTITY GOVERNANCE · ZERO-WRITE INTAKE</p>
          <h1>Scope Authority Intake</h1>
          <span>
            真实 owner source → 独立 review → 零写 preflight。正式 grant 不在本工作台。
          </span>
        </div>
        <div className={styles.headerActions}>
          <Link href="/authority-graph">Authority Graph</Link>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void load(entityRef, subjectActorId, eventType)}
          >
            刷新 verifier
          </button>
        </div>
      </header>

      <section className={styles.statusRail} data-state={intake?.state ?? "loading"}>
        <div>
          <span>requester</span>
          <strong>{session?.actor_id ?? "resolving"}</strong>
          <small>{session?.roles.join(" / ") ?? "identity unavailable"}</small>
        </div>
        <div>
          <span>verifier state</span>
          <strong>{intake?.state ?? "loading"}</strong>
          <small>
            {intake
              ? `${intake.verifier.id}@${intake.verifier.version} · ${intake.freshness}`
              : "server observation pending"}
          </small>
        </div>
        <div>
          <span>owner / SLA</span>
          <strong>{intake?.owner ?? "unknown"}</strong>
          <small>{intake ? `${intake.sla_seconds}s` : "not observed"}</small>
        </div>
        <div>
          <span>formal authority</span>
          <strong>{intake?.formal_authority.status ?? "unknown"}</strong>
          <small>
            {intake?.formal_authority.authority_sha256
              ? `${intake.formal_authority.authority_sha256.slice(0, 14)}…`
              : "no grant hash"}
          </small>
        </div>
        <div>
          <span>external write</span>
          <strong>false</strong>
          <small>grant endpoint exposed false</small>
        </div>
        <div>
          <span>identity topology</span>
          <strong>{topology?.state ?? "unavailable"}</strong>
          <small>
            API {String(topology?.api_chain_ready ?? false)} · Web{" "}
            {String(topology?.web_chain_ready ?? false)}
          </small>
        </div>
      </section>

      <section
        className={styles.topology}
        data-state={topology?.state ?? "unavailable"}
      >
        <div className={styles.topologyHeading}>
          <div>
            <p>EXTERNAL IDENTITY OBSERVATION</p>
            <h2>Four-party workflow topology</h2>
          </div>
          <span>
            {topology
              ? `${topology.verifier.id}@${topology.verifier.version} · ${topology.freshness}`
              : "verifier unavailable"}
          </span>
        </div>
        {topology ? (
          <>
            <div className={styles.topologyGrid}>
              <article>
                <span>API chain</span>
                <strong>{topology.api_chain_ready ? "ready" : "blocked"}</strong>
                <small>
                  {topology.counts.api_chains} valid chain(s) ·{" "}
                  {topology.counts.exact_scope_actors} exact-scope actors
                </small>
              </article>
              <article>
                <span>Web chain</span>
                <strong>{topology.web_chain_ready ? "ready" : "blocked"}</strong>
                <small>
                  {topology.auth_mode} · {topology.counts.web_user_bindings} bound
                  user(s)
                </small>
              </article>
              <article>
                <span>Owner / SLA</span>
                <strong>{topology.owner}</strong>
                <small>{topology.sla_seconds}s · as_of {topology.as_of}</small>
              </article>
            </div>
            {topology.selected_api_chain ? (
              <div className={styles.chain}>
                <div>
                  <span>subject</span>
                  <strong>{topology.selected_api_chain.subject_actor_id}</strong>
                </div>
                <b>→</b>
                <div>
                  <span>owner</span>
                  <strong>{topology.selected_api_chain.owner_actor_id}</strong>
                </div>
                <b>→</b>
                <div>
                  <span>reviewer</span>
                  <strong>{topology.selected_api_chain.reviewer_actor_id}</strong>
                </div>
                <b>→</b>
                <div>
                  <span>recorder</span>
                  <strong>{topology.selected_api_chain.recorder_actor_id}</strong>
                </div>
              </div>
            ) : null}
            <div className={styles.topologyTruth}>
              <strong>{topology.why}</strong>
              <p>{topology.next_safe_action}</p>
              <small>
                blockers{" "}
                {topology.blocker_codes.length
                  ? topology.blocker_codes.join(" · ")
                  : "none"}
              </small>
              <code>input {topology.input_sha256}</code>
              <code>result {topology.result_sha256}</code>
            </div>
          </>
        ) : (
          <p className={styles.empty}>
            failed closed · 无法取得运行中 Web 身份拓扑观测。
          </p>
        )}
        <small className={styles.noSwitch}>
          role switch allowed false · grant created false · external write false
        </small>
      </section>

      <section className={styles.scopeCard}>
        <div>
          <p>EXACT SCOPE</p>
          <h2>冻结查询与交接作用域</h2>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void load(entityRef, subjectActorId, eventType);
          }}
        >
          <label>
            Legal entity ref
            <input
              required
              value={entityRef}
              onChange={(event) => setEntityRef(event.target.value)}
              placeholder="真实法人主体标识"
            />
          </label>
          <label>
            Operating subject actor
            <input
              required
              value={subjectActorId}
              onChange={(event) => setSubjectActorId(event.target.value)}
            />
          </label>
          <label>
            Decision
            <select
              value={eventType}
              onChange={(event) =>
                setEventType(event.target.value as "grant" | "revoke")
              }
            >
              <option value="grant">grant</option>
              <option value="revoke">revoke</option>
            </select>
          </label>
          <label>
            Effective at (ISO-8601)
            <input
              required
              value={effectiveAt}
              onChange={(event) => setEffectiveAt(event.target.value)}
            />
          </label>
          <button type="submit" disabled={busy !== null}>
            核验 exact scope
          </button>
        </form>
        <div className={styles.truth}>
          <strong>{notice}</strong>
          <p>{intake?.next_safe_action ?? "等待 verifier。"}</p>
          <small>
            blockers{" "}
            {intake?.blocker_codes.length
              ? intake.blocker_codes.join(" · ")
              : "none"}
          </small>
          {intake ? <code>snapshot {intake.snapshot_sha256}</code> : null}
        </div>
      </section>

      <section className={styles.steps}>
        <article>
          <div className={styles.stepHeading}>
            <span>01</span>
            <div>
              <p>ACCOUNT OWNER</p>
              <h2>Source Evidence</h2>
            </div>
            <b>
              {intake?.allowed_actions.submit_source
                ? "role ready"
                : "role blocked"}
            </b>
          </div>
          <form onSubmit={submitSource}>
            <label>
              真实 owner authority 文件
              <input name="source_file" type="file" required />
            </label>
            <label>
              Effective until（可空）
              <input
                name="effective_until"
                placeholder="2027-07-01T00:00:00Z"
              />
            </label>
            <label>
              Idempotency key
              <input
                name="source_idempotency_key"
                required
                placeholder="owner-source-..."
              />
            </label>
            <button
              type="submit"
              disabled={
                busy !== null ||
                !exactScopeReady ||
                !intake?.allowed_actions.submit_source
              }
            >
              追加 owner source
            </button>
          </form>
          <small>
            需要 reviewer/admin owner 身份；subject 不能给自己提交授权源。
          </small>
        </article>

        <article>
          <div className={styles.stepHeading}>
            <span>02</span>
            <div>
              <p>INDEPENDENT REVIEWER</p>
              <h2>Review Evidence</h2>
            </div>
            <b>
              {selectedCandidate?.can_current_actor_review
                ? "independent"
                : "blocked"}
            </b>
          </div>
          <form onSubmit={submitReview}>
            <label>
              Source Evidence ID
              <input
                required
                value={selectedSourceId}
                onChange={(event) => setSelectedSourceId(event.target.value)}
              />
            </label>
            <label>
              Review decision
              <select name="review_decision" defaultValue="accepted">
                <option value="accepted">accepted</option>
                <option value="rejected">rejected</option>
              </select>
            </label>
            <fieldset>
              <legend>Verifier checks</legend>
              <label>
                <input name="authentic_original" type="checkbox" /> authentic original
              </label>
              <label>
                <input name="owner_authority_verified" type="checkbox" /> owner authority verified
              </label>
              <label>
                <input name="scope_matches" type="checkbox" /> exact scope matches
              </label>
            </fieldset>
            <label>
              Rationale
              <textarea name="review_rationale" required />
            </label>
            <label>
              Idempotency key
              <input
                name="review_idempotency_key"
                required
                placeholder="independent-review-..."
              />
            </label>
            <button
              type="submit"
              disabled={
                busy !== null ||
                !exactScopeReady ||
                !selectedCandidate?.can_current_actor_review
              }
            >
              追加独立 review
            </button>
          </form>
          <small>owner、reviewer、subject 必须是三个不同真实 actor。</small>
        </article>

        <article>
          <div className={styles.stepHeading}>
            <span>03</span>
            <div>
              <p>COMPLIANCE VERIFIER</p>
              <h2>Zero-write Preflight</h2>
            </div>
            <b>
              {selectedCandidate?.can_current_actor_preflight
                ? "ready"
                : "blocked"}
            </b>
          </div>
          <form onSubmit={runPreflight}>
            <label>
              Accepted Review Evidence ID
              <input
                required
                value={selectedReviewId}
                onChange={(event) => setSelectedReviewId(event.target.value)}
              />
            </label>
            <label>
              Reason
              <textarea name="preflight_reason" required />
            </label>
            <label>
              Idempotency key
              <input
                name="preflight_idempotency_key"
                required
                placeholder="scope-preflight-..."
              />
            </label>
            <button
              type="submit"
              disabled={
                busy !== null ||
                !exactScopeReady ||
                !selectedCandidate?.can_current_actor_preflight
              }
            >
              运行零写 preflight
            </button>
          </form>
          <small>
            只计算请求哈希与 blocker；不创建 grant、approval、permit 或外部写。
          </small>
        </article>
      </section>

      <section className={styles.artifacts}>
        <div>
          <p>VERIFIER-OWNED ARTIFACTS</p>
          <h2>Source / Review / Lineage</h2>
        </div>
        {intake?.candidates.length ? (
          intake.candidates.map((candidate) => (
            <article key={candidate.source_evidence_id}>
              <div>
                <span>{candidate.review_state}</span>
                <strong>{candidate.source_evidence_id}</strong>
                <small>
                  owner {candidate.owner_actor_id} · effective{" "}
                  {candidate.effective_at}
                </small>
                <code>{candidate.source_evidence_sha256}</code>
                <Link
                  href={`/backend/v1/evidence/${candidate.source_evidence_id}`}
                >
                  打开真实 source artifact
                </Link>
              </div>
              <div>
                {candidate.reviews.length ? (
                  candidate.reviews.map((review) => (
                    <div key={review.id} className={styles.review}>
                      <span>
                        {review.decision} · lineage{" "}
                        {String(review.lineage_verified)}
                      </span>
                      <strong>{review.id}</strong>
                      <small>reviewer {review.reviewed_by}</small>
                      <code>{review.sha256}</code>
                      <Link href={`/backend/v1/evidence/${review.id}/lineage`}>
                        打开真实 lineage
                      </Link>
                    </div>
                  ))
                ) : (
                  <p>no independent review observation</p>
                )}
              </div>
            </article>
          ))
        ) : (
          <p className={styles.empty}>
            no_data · exact scope 下尚无 verifier 可接受的 owner Evidence。
          </p>
        )}
      </section>
    </main>
  );
}
