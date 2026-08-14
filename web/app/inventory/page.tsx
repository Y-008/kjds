import type { Metadata } from "next";
import { InventoryConsole } from "../../features/inventory/inventory-console";

export const metadata: Metadata = {
  title: "库存与履约 · KJDS AI ERP",
  description:
    "Evidence-bound warehouse stock, OMS demand coverage, and governed Agent guidance.",
};

export default function InventoryPage() {
  return <InventoryConsole />;
}
