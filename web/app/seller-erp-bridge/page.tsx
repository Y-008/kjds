import type { Metadata } from "next";
import { SellerErpBridgeConsole } from "../../features/seller-erp-bridge/seller-erp-bridge-console";

export const metadata: Metadata = {
  title: "Seller ERP Bridge · KJDS AI ERP",
  description:
    "Authorized exact-scope Seller ERP snapshots reconciled against KJDS Canonical truth.",
};

export default function SellerErpBridgePage() {
  return <SellerErpBridgeConsole />;
}
