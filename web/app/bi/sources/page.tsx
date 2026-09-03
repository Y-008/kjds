import type { Metadata } from "next";
import { ControlPlanePage } from "../../../features/control-tower/control-plane";

export const metadata: Metadata = {
  title: "证据与来源 · KJDS",
  description: "KJDS 作用域内来源缺口、排除项与采集边界。",
};

export default function SourcesPage() {
  return <ControlPlanePage surface="sources" />;
}
