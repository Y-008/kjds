import type { Metadata } from "next";
import { TeamControlTowerPage } from "../../features/team-control-tower/team-control-tower";

export const metadata: Metadata = {
  title: "Control Tower v2 · KJDS",
  description: "KJDS AI 原生经营控制塔：目标、异常、决策、证据与任务波次。",
};

export default function ControlTowerV2Page() {
  // The visual v2 draft remains quarantined until its cards consume the
  // server-owned projection. Keep this route on the verified control tower so
  // static placeholder economics never become an operating fact.
  return <TeamControlTowerPage />;
}
