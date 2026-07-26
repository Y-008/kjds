import type { Metadata } from "next";
import { OperatingWorkspace } from "../../../../features/operating-workspace/operating-workspace";

export const metadata: Metadata = {
  title: "全链路经营工作区 · KJDS",
  description: "点、线、面业务合同与真实经营信号的只读穿透工作区。",
};

export default async function OperatingWorkspacePage({
  params,
}: {
  params: Promise<{ kind: string; itemId: string }>;
}) {
  const { kind, itemId } = await params;
  return <OperatingWorkspace kind={kind} itemId={itemId} />;
}
