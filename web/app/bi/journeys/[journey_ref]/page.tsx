import type { Metadata } from "next";
import { ControlPlanePage } from "../../../../features/control-tower/control-plane";

export const metadata: Metadata = {
  title: "经营旅程 · KJDS",
  description: "KJDS 从经营阶段到现金结果的只读旅程控制塔。",
};

export default async function JourneyPage({
  params,
}: {
  params: Promise<{ journey_ref: string }>;
}) {
  const { journey_ref: journeyRef } = await params;
  return <ControlPlanePage surface="journey" journeyRef={journeyRef} />;
}
