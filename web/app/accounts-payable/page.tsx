import type { Metadata } from "next";
import { AccountsPayableConsole } from "../../features/accounts-payable/accounts-payable-console";

export const metadata: Metadata = {
  title: "应付与供应商付款控制 · KJDS AI ERP",
  description:
    "Exact-scope supplier invoice, three-way match, Approval, Permit and bank Readback control.",
};

export default function AccountsPayablePage() {
  return <AccountsPayableConsole />;
}
