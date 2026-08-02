import type { Metadata } from "next";
import { ReturnsConsole } from "../../features/returns/returns-console";

export const metadata: Metadata = {
  title: "退货退款控制 · KJDS AI ERP",
  description:
    "Exact-scope Return Fact, settlement, bank Readback and gated after-sales control.",
};

export default function ReturnsPage() {
  return <ReturnsConsole />;
}
