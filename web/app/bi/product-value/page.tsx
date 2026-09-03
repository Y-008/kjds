import type { Metadata } from "next";
import { ControlPlanePage } from "../../../features/control-tower/control-plane";

export const metadata: Metadata = {
  title: "产品价值与 ROI · KJDS",
  description: "KJDS 证据支持决策、工作项和 Outcome telemetry 的只读视图。",
};

export default function ProductValuePage() {
  return <ControlPlanePage surface="product-value" />;
}
