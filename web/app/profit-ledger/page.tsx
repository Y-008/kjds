import type { Metadata } from "next";
import { ProfitLedgerConsole } from "../../features/profit-ledger/profit-ledger-console";

export const metadata: Metadata = {
  title: "十五项实际利润账 · KJDS AI ERP",
  description:
    "Native exact-scope fifteen-leg actual profit and Actual Cash CM3 ledger.",
};

export default function ProfitLedgerPage() {
  return <ProfitLedgerConsole />;
}
