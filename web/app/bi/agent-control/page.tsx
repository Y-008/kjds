import type { Metadata } from "next";
import { ControlPlanePage } from "../../../features/control-tower/control-plane";

export const metadata: Metadata = {
  title: "Agent 控制塔 · KJDS",
  description: "KJDS Agent 观察、guardrail 与人工审核边界。",
};

export default function AgentControlPage() {
  return <ControlPlanePage surface="agent-control" />;
}
