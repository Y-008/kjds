import type { Metadata } from "next";
import { OzonProductionAcceptanceConsole } from "../../../features/ozon-production-acceptance/ozon-production-acceptance-console";

export const metadata: Metadata = {
  title: "Ozon 外部事实验收 · KJDS",
  description: "只读查看 Ozon 官方回读、Evidence 完整性和生产验收阻断。",
};

export default function OzonProductionAcceptancePage() {
  return <OzonProductionAcceptanceConsole />;
}
