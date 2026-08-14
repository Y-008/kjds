import type { Metadata } from "next";
import { ProcurementConsole } from "../../features/procurement/procurement-console";

export const metadata: Metadata = {
  title: "采购与收货控制 · KJDS AI ERP",
  description:
    "Exact-scope procurement decision, supplier order, receiving and inspection Evidence control.",
};

export default function ProcurementPage() {
  return <ProcurementConsole />;
}
