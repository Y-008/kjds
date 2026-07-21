"use client";

import { DashboardView } from "./dashboard-view";
import { useDashboardController } from "./use-dashboard-controller";

export function KjdsDashboard() {
  return <DashboardView model={useDashboardController()} />;
}
