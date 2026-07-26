import type { Metadata } from "next";
import { EvidenceOpsCopilot } from "../../features/evidenceops/evidenceops-copilot";

export const metadata: Metadata = {
  title: "EvidenceOps Copilot · KJDS",
  description: "把跨境经营目标编译成可验证事实、未知项、责任 Agent 与受控任务合同。",
};

export default function EvidenceOpsPage() {
  return <EvidenceOpsCopilot />;
}
