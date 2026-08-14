import type { Metadata } from "next";
import { SourcingIntelligenceConsole } from "../../features/sourcing-intelligence/sourcing-intelligence-console";

export const metadata: Metadata = {
  title: "供应智能 · KJDS AI ERP",
  description: "Exact-scope market, supplier, RFQ, quote and downside CM3 research.",
};

export default function SourcingIntelligencePage() {
  return <SourcingIntelligenceConsole />;
}
