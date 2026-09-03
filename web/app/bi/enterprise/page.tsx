import type { Metadata } from "next";
import { ControlPlanePage } from "../../../features/control-tower/control-plane";

export const metadata: Metadata = {
  title: "企业与作用域 · KJDS",
  description: "KJDS Authority、Commercial 与 Operational Scope 的只读控制塔。",
};

export default function EnterprisePage() {
  return <ControlPlanePage surface="enterprise" />;
}
