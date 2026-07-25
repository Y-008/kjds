"use client";

import { useEffect, useState } from "react";
import { DashboardShell } from "./dashboard-shell";
import { DataImportPanel } from "./data-import-panel";
import { FinancePanel } from "./finance-panel";
import { GovernanceHubPanel } from "./governance-hub-panel";
import { MarketplaceGrowthPanel } from "./marketplace-growth-panel";
import { OperationsPanel } from "./operations-panel";
import { DecisionSciencePanel } from "./decision-science-panel";
import { ResearchGatePanel } from "./research-gate-panel";
import { ProductContentPanel } from "./product-content-panel";
import { SourcingPanel } from "./sourcing-panel";
import { OperationsSummaryPanel } from "./operations-summary-panel";
import { UnifiedOverviewPanel } from "./unified-overview-panel";
import {
  workspaceDefinitions,
  type WorkspaceId,
} from "./dashboard-workspaces";
import type { DashboardModel } from "./use-dashboard-controller";

function isWorkspaceId(value: string): value is WorkspaceId {
  return workspaceDefinitions.some((item) => item.id === value);
}

export function DashboardView({ model }: { model: DashboardModel }) {
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceId>("overview");
  const ozonPilot = model.readOnlyPilots.find((item) => item.platform.toLowerCase() === "ozon");
  const ozonConnection = ozonPilot?.status === "active"
    ? { label: "Ozon 只读试点已激活", ready: true }
    : ozonPilot
      ? { label: `Ozon 只读 · ${ozonPilot.status}`, ready: false }
      : { label: "Ozon 连接待验证", ready: false };
  const domainKey = activeWorkspace === "finance"
    ? "finance"
    : activeWorkspace === "science"
      ? "science"
      : ["governance", "system"].includes(activeWorkspace)
        ? "execution"
        : ["data", "research", "products", "sourcing", "growth"].includes(activeWorkspace)
          ? "product"
          : "core";
  const workspaceState = model.domainStates[domainKey];

  useEffect(() => {
    const syncFromHash = () => {
      const requested = window.location.hash.replace(/^#/, "");
      setActiveWorkspace(isWorkspaceId(requested) ? requested : "overview");
    };
    syncFromHash();
    window.addEventListener("hashchange", syncFromHash);
    window.addEventListener("popstate", syncFromHash);
    return () => {
      window.removeEventListener("hashchange", syncFromHash);
      window.removeEventListener("popstate", syncFromHash);
    };
  }, []);

  useEffect(() => {
    if (activeWorkspace === "growth" && !model.marketplaceGrowthFactsLoaded) {
      void model.loadMarketplaceGrowthFacts();
    }
  }, [activeWorkspace, model.loadMarketplaceGrowthFacts, model.marketplaceGrowthFactsLoaded]);

  const navigate = (workspace: WorkspaceId) => {
    setActiveWorkspace(workspace);
    window.history.pushState(null, "", `#${workspace}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const content = (() => {
    switch (activeWorkspace) {
      case "data":
        return <div className="workspace-page legacy-workspace"><DataImportPanel model={model} /></div>;
      case "research":
        return <div className="workspace-page legacy-workspace"><ResearchGatePanel model={model} /></div>;
      case "products":
        return <div className="workspace-page legacy-workspace"><ProductContentPanel model={model} /></div>;
      case "sourcing":
        return <div className="workspace-page legacy-workspace"><SourcingPanel model={model} /></div>;
      case "growth":
        return <MarketplaceGrowthPanel model={model} />;
      case "finance":
        return <div className="workspace-page legacy-workspace"><FinancePanel model={model} /></div>;
      case "science":
        return <div className="workspace-page legacy-workspace"><DecisionSciencePanel model={model} /></div>;
      case "governance":
        return <GovernanceHubPanel model={model} onNavigate={navigate} />;
      case "system":
        return <div className="workspace-page legacy-workspace"><OperationsPanel model={model} /></div>;
      default:
        return (
          <>
            <UnifiedOverviewPanel model={model} onNavigate={navigate} />
            <div className="overview-details">
              <OperationsSummaryPanel
                health={model.health}
                operatingWorkbench={model.operatingWorkbench}
                recommendations={model.recommendations}
                sourceConnectors={model.sourceConnectors}
                offersCount={model.offers.length}
                skuReadiness={model.skuReadiness}
              />
            </div>
          </>
        );
    }
  })();

  return (
    <DashboardShell
      session={model.webSession}
      activeWorkspace={activeWorkspace}
      ozonConnection={ozonConnection}
      onNavigate={navigate}
      onRefresh={() => void model.load()}
    >
      <div className="global-notice" role="status" aria-live="polite">
        <span className="global-notice-dot" />
        <span>{model.notice}</span>
      </div>
      {workspaceState !== "ready" ? (
        <div className={`workspace-load-state ${workspaceState}`} role={workspaceState === "error" ? "alert" : "status"}>
          <span />
          <div>
            <strong>{workspaceState === "loading" ? "正在加载工作区真源" : "部分工作区真源暂时不可用"}</strong>
            <p>{workspaceState === "loading" ? "计数、门禁和操作状态加载完成前不会用估算值代替。" : "现有内容仍可查看；请刷新或到“系统运行”检查接口与身份状态。"}</p>
          </div>
        </div>
      ) : null}
      {content}
    </DashboardShell>
  );
}
