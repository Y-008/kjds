"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";

type RailTask = {
  id: string;
  title: string;
  state: string;
  freshness: string;
};

export function AgentStatusRail() {
  const [items, setItems] = useState<RailTask[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let active = true;
    fetchJson<{ status_rail: RailTask[] }>(
      "/backend/v1/agent-control/projects/kjds-059-bas123?store_ref=ozon-primary",
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(`Verifier API ${response.status}`);
        const payload = await response.json();
        if (active) {
          setItems(payload.status_rail ?? []);
          setState("ready");
        }
      })
      .catch(() => {
        if (active) setState("error");
      });
    return () => {
      active = false;
    };
  }, []);

  const critical = items[0];
  return (
    <aside className={`agent-status-rail ${state}`} aria-label="Agent 外部观测状态">
      <span className="agent-status-dot" />
      <div>
        <strong>
          {state === "loading"
            ? "Verifier 读取中"
            : state === "error"
              ? "Verifier 状态不可用"
              : critical
                ? `${critical.state} · ${critical.title}`
                : "当前竖切全部 fresh passed"}
        </strong>
        <span>
          {critical
            ? `${critical.freshness} · ${items.length} 项需关注`
            : "来自 PostgreSQL append-only observations"}
        </span>
      </div>
      <Link href="/agent-control">打开</Link>
    </aside>
  );
}
