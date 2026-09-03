import type { Metadata } from "next";
import { ControlPlanePage } from "../../../features/control-tower/control-plane";

export const metadata: Metadata = {
  title: "情景实验室 · KJDS",
  description: "KJDS scenario_* 输入、基线和实际账隔离的只读实验室。",
};

export default function ScenariosPage() {
  return <ControlPlanePage surface="scenarios" />;
}
