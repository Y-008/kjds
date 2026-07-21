"use client";

import { DashboardShell } from "./dashboard-shell";
import { DataImportPanel } from "./data-import-panel";
import { FinancePanel } from "./finance-panel";
import { OperationsPanel } from "./operations-panel";
import { DecisionSciencePanel } from "./decision-science-panel";
import { ResearchGatePanel } from "./research-gate-panel";
import { ProductContentPanel } from "./product-content-panel";
import { SourcingPanel } from "./sourcing-panel";
import { OperationsSummaryPanel } from "./operations-summary-panel";
import type { DashboardModel } from "./use-dashboard-controller";

export function DashboardView({ model }: { model: DashboardModel }) {
  return (
    <DashboardShell session={model.webSession} onRefresh={() => void model.load()}>
      <DataImportPanel model={model} />
      <FinancePanel model={model} />
      <OperationsPanel model={model} />
      <DecisionSciencePanel model={model} />
      <ResearchGatePanel model={model} />
      <ProductContentPanel model={model} />
      <SourcingPanel model={model} />
      <OperationsSummaryPanel health={model.health} recommendations={model.recommendations} sourceConnectors={model.sourceConnectors} offersCount={model.offers.length} skuReadiness={model.skuReadiness} />
    </DashboardShell>
  );
}
