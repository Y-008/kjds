import type { Metadata } from "next";
import { FinanceControlConsole } from "../../features/finance-control/finance-control-console";

export const metadata: Metadata = {
  title: "结算与现金控制 · KJDS AI ERP",
  description:
    "Exact-scope Order/Accrual, Platform Settlement, Bank Cash and Actual Cash CM3 control.",
};

export default function FinanceControlPage() {
  return <FinanceControlConsole />;
}
