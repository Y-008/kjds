import type { Metadata } from "next";
import { PimConsole } from "../../features/pim/pim-console";

export const metadata: Metadata = {
  title: "商品主数据 PIM · KJDS AI ERP",
  description: "Exact-scope Canonical Product, Passport, media QA and Listing readiness.",
};

export default function PimPage() {
  return <PimConsole />;
}
