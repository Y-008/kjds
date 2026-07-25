"use client";

import { ShieldCheck } from "lucide-react";
import { DashboardShell } from "./dashboard-shell";
import { DataImportPanel } from "./data-import-panel";
import { FinancePanel } from "./finance-panel";
import { OperationsPanel } from "./operations-panel";
import { DecisionSciencePanel } from "./decision-science-panel";
import { ResearchGatePanel } from "./research-gate-panel";
import { ProductContentPanel } from "./product-content-panel";
import { SourcingPanel } from "./sourcing-panel";
import { OperationsSummaryPanel } from "./operations-summary-panel";
import { IntelligenceHubPanel } from "./intelligence-hub-panel";
import { SalesFulfillmentPanel } from "./sales-fulfillment-panel";
import type { DashboardModel } from "./use-dashboard-controller";

export function DashboardView({ model }: { model: DashboardModel }) {
  const refresh = () => {
    if (model.identityStatus === "ready") void model.load();
    else window.location.reload();
  };
  return (
    <DashboardShell session={model.webSession} identityStatus={model.identityStatus} onRefresh={refresh}>
      {model.identityStatus === "ready" ? <>
        <IntelligenceHubPanel model={model} />
        <DataImportPanel model={model} />
        <FinancePanel model={model} />
        <OperationsPanel model={model} />
        <DecisionSciencePanel model={model} />
        <ResearchGatePanel model={model} />
        <ProductContentPanel model={model} />
        <SourcingPanel model={model} />
        <SalesFulfillmentPanel model={model} />
      </> : <section className="identity-lock" role="alert"><ShieldCheck size={24} /><div><strong>{model.identityStatus === "checking" ? "正在核验经营身份" : "身份服务不可用，经营状态显示为未知"}</strong><p>依赖身份权限的上传、审批、采购、上架和执行操作已全部隐藏。恢复身份服务后刷新页面。</p></div></section>}
      <OperationsSummaryPanel identityStatus={model.identityStatus} health={model.health} operatingWorkbench={model.operatingWorkbench} recommendations={model.recommendations} sourceConnectors={model.sourceConnectors} offersCount={model.offers.length} skuReadiness={model.skuReadiness} />
    </DashboardShell>
  );
}
