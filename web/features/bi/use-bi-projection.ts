"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import type {
  OperatingAnalyticsSnapshot,
  OperatingWorkbenchBriefing,
} from "../dashboard/contracts";
import {
  buildBiScopeSearch,
  createBiProjectionFailure,
  createEmptyBiProjectionRound,
  createEmptyProjectionSlot,
  isTimezoneIsoTimestamp,
  loadBiProjectionRound,
  type BiJsonRequest,
  type BiProjectionRoundResult,
  type BiProjectionSlot,
  type BiProjectionStatus,
  type BiScopeState,
} from "./contract";

export type BiScopeController = BiScopeState & {
  setStoreRef: (storeRef: string) => void;
  setAsOf: (asOf: string | null) => void;
};

export type UseBiProjectionResult = {
  scope: BiScopeController;
  snapshot: OperatingAnalyticsSnapshot | null;
  briefing: OperatingWorkbenchBriefing | null;
  analytics: BiProjectionSlot<OperatingAnalyticsSnapshot>;
  workbench: BiProjectionSlot<OperatingWorkbenchBriefing>;
  status: BiProjectionStatus;
  error: string;
  refresh: () => void;
};

export type UseBiProjectionOptions = {
  allowedUrlParams?: readonly string[];
  request?: BiJsonRequest;
  now?: () => Date;
};

export type {
  BiJsonRequest,
  BiProjectionRoundResult,
  BiProjectionSlot,
  BiProjectionStatus,
  BiScopeState,
} from "./contract";
export { loadBiProjectionRound } from "./contract";

const defaultRequest: BiJsonRequest = (input, init) => fetchJson<unknown>(input, init);
const defaultNow = () => new Date();

export function useBiProjection(
  options: UseBiProjectionOptions = {},
): UseBiProjectionResult {
  const [round, setRound] = useState<BiProjectionRoundResult>(
    () => createEmptyBiProjectionRound(),
  );
  const [revision, setRevision] = useState(0);
  const activeControllerRef = useRef<AbortController | null>(null);
  const roundSequenceRef = useRef(0);
  const allowedKey = (options.allowedUrlParams ?? []).join("\u0000");
  const allowedUrlParams = useMemo(
    () => allowedKey ? allowedKey.split("\u0000") : [],
    [allowedKey],
  );
  const request = options.request ?? defaultRequest;
  const now = options.now ?? defaultNow;

  const invalidateActiveRound = useCallback(() => {
    roundSequenceRef.current += 1;
    activeControllerRef.current?.abort("BI scope changed");
    activeControllerRef.current = null;
  }, []);

  useEffect(() => {
    const onPopState = () => {
      invalidateActiveRound();
      setRound((current) => beginLoadingRound(current));
      setRevision((current) => current + 1);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [invalidateActiveRound]);

  useEffect(() => {
    invalidateActiveRound();
    const controller = new AbortController();
    activeControllerRef.current = controller;
    const roundSequence = roundSequenceRef.current;
    setRound((current) => beginLoadingRound(current));
    void loadBiProjectionRound({
      search: window.location.search,
      signal: controller.signal,
      allowedUrlParams,
      request,
      now,
    })
      .then((next) => {
        if (controller.signal.aborted || roundSequence !== roundSequenceRef.current) return;
        if (next.redirectTo) {
          window.location.assign(next.redirectTo);
          return;
        }
        setRound(next);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || roundSequence !== roundSequenceRef.current) return;
        setRound(createBiProjectionFailure(
          "error",
          reason instanceof Error ? reason.message : "BI 投影读取失败",
        ));
      });
    return () => {
      controller.abort("BI scope changed or component unmounted");
      if (activeControllerRef.current === controller) activeControllerRef.current = null;
    };
  }, [allowedUrlParams, invalidateActiveRound, now, request, revision]);

  const refresh = useCallback(() => {
    invalidateActiveRound();
    setRound((current) => beginLoadingRound(current));
    setRevision((current) => current + 1);
  }, [invalidateActiveRound]);

  const setStoreRef = useCallback((storeRef: string) => {
    const normalized = storeRef.trim();
    if (!round.scope.storeRefs.includes(normalized)) {
      invalidateActiveRound();
      setRound((current) => createBiProjectionFailure(
        "forbidden",
        `当前身份未获授权访问店铺 ${normalized || "(empty)"}；未发送任何经营数据请求。`,
        { ...current.scope, status: "forbidden", storeRef: normalized },
      ));
      return;
    }
    replaceScopeLocation(
      { storeRef: normalized, asOf: round.scope.asOf },
      allowedUrlParams,
    );
    invalidateActiveRound();
    setRound((current) => beginLoadingRound(current, { storeRef: normalized }));
    setRevision((current) => current + 1);
  }, [allowedUrlParams, invalidateActiveRound, round.scope.asOf, round.scope.storeRefs]);

  const setAsOf = useCallback((asOf: string | null) => {
    if (asOf !== null && !isTimezoneIsoTimestamp(asOf)) {
      invalidateActiveRound();
      setRound((current) => createBiProjectionFailure(
        "blocked",
        "as_of 必须是包含时区的 ISO-8601 时间",
        { ...current.scope, status: "blocked" },
      ));
      return;
    }
    replaceScopeLocation(
      { storeRef: round.scope.storeRef || null, asOf },
      allowedUrlParams,
    );
    invalidateActiveRound();
    setRound((current) => beginLoadingRound(current, { asOf }));
    setRevision((current) => current + 1);
  }, [allowedUrlParams, invalidateActiveRound, round.scope.storeRef]);

  return {
    scope: {
      ...round.scope,
      setStoreRef,
      setAsOf,
    },
    snapshot: round.analytics.data,
    briefing: round.workbench.data,
    analytics: round.analytics,
    workbench: round.workbench,
    status: round.status,
    error: round.error,
    refresh,
  };
}

function beginLoadingRound(
  current: BiProjectionRoundResult,
  scopePatch: Partial<BiScopeState> = {},
): BiProjectionRoundResult {
  return {
    ...createEmptyBiProjectionRound(),
    scope: {
      ...current.scope,
      ...scopePatch,
      status: "loading",
      authorityStatus: null,
      requestAsOf: null,
      authoritySha256: null,
    },
    analytics: createEmptyProjectionSlot("loading"),
    workbench: createEmptyProjectionSlot("loading"),
  };
}

function replaceScopeLocation(
  query: { storeRef: string | null; asOf: string | null },
  allowedUrlParams: readonly string[],
) {
  const search = buildBiScopeSearch(window.location.search, query, allowedUrlParams);
  window.history.pushState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
}
