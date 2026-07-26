import type { Metadata } from "next";
import { OperatingIntelligence } from "../../features/operating-intelligence/operating-intelligence";

export const metadata: Metadata = {
  title: "Operating Intelligence · KJDS",
  description: "真实利润、经营异常任务与媒体产能工作台。",
};

export default function OperatingIntelligencePage() {
  return <OperatingIntelligence />;
}
