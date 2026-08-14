import type { Metadata } from "next";
import { FormalFactsConsole } from "../../features/formal-facts/formal-facts-console";

export const metadata: Metadata = {
  title: "Formal Facts · KJDS",
  description: "Tenant-scoped Ozon formal Fact and Promotion authority.",
};

export default function FormalFactsPage() {
  return <FormalFactsConsole />;
}
