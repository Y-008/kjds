import type { Metadata } from "next";
import { ControlPlanePage } from "../../../features/control-tower/control-plane";

export const metadata: Metadata = {
  title: "可靠性与降级 · KJDS",
  description: "KJDS 投影可信度、降级策略和运行信号缺口。",
};

export default function ReliabilityPage() {
  return <ControlPlanePage surface="reliability" />;
}
