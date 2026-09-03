import type { Metadata } from "next";
import { ControlPlanePage } from "../../../features/control-tower/control-plane";

export const metadata: Metadata = {
  title: "能力成熟度 · KJDS",
  description: "KJDS 能力合同、验证证据与生产 Gate 的只读控制塔。",
};

export default function CapabilitiesPage() {
  return <ControlPlanePage surface="capabilities" />;
}
