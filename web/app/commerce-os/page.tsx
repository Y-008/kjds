import type { Metadata } from "next";
import { CommerceOsConsole } from "../../features/commerce-os/commerce-os-console";

export const metadata: Metadata = {
  title: "Commerce OS · KJDS",
  description: "KJDS 原生跨境 ERP、内容工厂与可审计 Agent Team。",
};

export default function CommerceOsPage() {
  return <CommerceOsConsole />;
}
