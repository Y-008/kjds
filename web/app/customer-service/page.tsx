import type { Metadata } from "next";
import { CustomerServiceConsole } from "../../features/customer-service/customer-service-console";

export const metadata: Metadata = {
  title: "客户服务权威 · KJDS AI ERP",
  description:
    "Exact-scope redacted Case/Event authority with Approval, Permit and Readback verification.",
};

export default function CustomerServicePage() {
  return <CustomerServiceConsole />;
}
