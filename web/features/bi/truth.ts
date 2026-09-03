import type { OperatingAnalyticsSnapshot } from "../dashboard/contracts";
import type { DataStatus } from "../ui2/ui2";

export type AnalyticsSummaryKey = keyof OperatingAnalyticsSnapshot["summary"];

type TruthDomain =
  | "catalog"
  | "readiness"
  | "growth"
  | "rfq"
  | "procurement"
  | "execution"
  | "finance"
  | "media";

const summaryDomains: Record<AnalyticsSummaryKey, TruthDomain> = {
  catalog_items: "catalog",
  bound_listings: "catalog",
  available_stock: "catalog",
  external_image_references: "catalog",
  external_video_references: "catalog",
  gate_blockers: "readiness",
  growth_snapshot_skus: "growth",
  rfq_packages: "rfq",
  verified_dispatch_proofs: "rfq",
  formal_finance_entries: "finance",
  ready_execution_plans: "execution",
};

const gapCodes: Record<TruthDomain, readonly string[]> = {
  catalog: ["scoped_catalog_authority_missing"],
  readiness: ["scoped_readiness_authority_missing"],
  growth: ["scoped_growth_authority_missing"],
  rfq: ["scoped_rfq_authority_missing"],
  procurement: ["scoped_procurement_authority_missing"],
  execution: ["scoped_execution_authority_missing"],
  finance: ["scoped_finance_authority_missing"],
  media: ["scoped_media_authority_missing"],
};

const coverageDomains: Record<string, TruthDomain> = {
  official_catalog: "catalog",
  "sku-000": "readiness",
  "sku-002": "readiness",
  "sku-003": "rfq",
  content_rights: "media",
  growth_truth: "growth",
  "ozn-001": "readiness",
  finance_truth: "finance",
};

const pipelineDomains: Record<string, TruthDomain> = {
  catalog: "catalog",
  bound: "catalog",
  growth: "growth",
  rfq: "rfq",
  dispatch: "rfq",
  execution: "execution",
  observation: "execution",
  finance: "finance",
};

export function projectionStatus(value: string | null | undefined): DataStatus {
  if (value === "ready" || value === "ready_for_review") return "ready";
  if (value === "partial" || value === "needs_input") return "partial";
  if (value === "no_data") return "no_data";
  if (value === "blocked") return "blocked";
  if (value === "forbidden") return "forbidden";
  if (value === "loading") return "loading";
  if (value === "error") return "error";
  return "conflicted";
}

export function summaryMetricStatus(
  snapshot: OperatingAnalyticsSnapshot | null,
  key: AnalyticsSummaryKey,
  fallback: DataStatus,
): DataStatus {
  if (!snapshot) return fallback;
  if (fallback === "loading" || fallback === "error" || fallback === "conflicted" || fallback === "forbidden") {
    return fallback;
  }
  const overall = projectionStatus(snapshot.status);
  if (overall === "no_data" || overall === "blocked") return overall;
  return domainStatus(snapshot, summaryDomains[key], overall);
}

export function summaryMetricValue(
  snapshot: OperatingAnalyticsSnapshot | null,
  key: AnalyticsSummaryKey,
  fallback: DataStatus,
): number | "no_data" | "blocked" | "forbidden" {
  const status = summaryMetricStatus(snapshot, key, fallback);
  if (status === "ready") return snapshot?.summary[key] ?? "no_data";
  if (status === "blocked") return "blocked";
  if (status === "forbidden") return "forbidden";
  return "no_data";
}

export function coverageStatus(
  snapshot: OperatingAnalyticsSnapshot,
  id: string,
): DataStatus {
  const overall = projectionStatus(snapshot.status);
  if (overall === "no_data" || overall === "blocked") return overall;
  const domain = coverageDomains[id];
  return domain ? domainStatus(snapshot, domain, overall) : "partial";
}

export function pipelineStatus(
  snapshot: OperatingAnalyticsSnapshot,
  id: string,
): DataStatus {
  const overall = projectionStatus(snapshot.status);
  if (overall === "no_data" || overall === "blocked") return overall;
  const domain = pipelineDomains[id];
  return domain ? domainStatus(snapshot, domain, overall) : "partial";
}

export function hasAdmittedCatalog(snapshot: OperatingAnalyticsSnapshot | null) {
  return Boolean(
    snapshot && domainStatus(snapshot, "catalog", projectionStatus(snapshot.status)) === "ready",
  );
}

function domainStatus(
  snapshot: OperatingAnalyticsSnapshot,
  domain: TruthDomain,
  overall: DataStatus,
): DataStatus {
  const gaps = new Set([
    ...(snapshot.source_gaps ?? []),
    ...(snapshot.data_gaps ?? []),
  ]);
  if (gaps.has("entity_scope_authority_missing")) return "no_data";
  if (gapCodes[domain].some((code) => gaps.has(code))) return "no_data";
  if (overall === "partial") return "ready";
  return overall;
}
