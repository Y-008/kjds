import type { Metadata } from "next";
import { BiOverview } from "../../../features/bi/bi-overview";

export const metadata: Metadata = {
  title: "BI Overview · KJDS",
  description: "基于 KJDS 服务端 OperatingAnalyticsSnapshot 的只读经营分析总览。",
};

export default function BiOverviewPage() {
  return <BiOverview />;
}
