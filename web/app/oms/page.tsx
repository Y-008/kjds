import type { Metadata } from "next";
import { OmsConsole } from "../../features/oms/oms-console";

export const metadata: Metadata = {
  title: "原生 OMS · KJDS AI ERP",
  description:
    "Evidence-bound Ozon order state, immutable timeline, and governed Agent guidance.",
};

export default function OmsPage() {
  return <OmsConsole />;
}
