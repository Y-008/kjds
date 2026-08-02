import type { Metadata } from "next";
import { ListingLifecycleConsole } from "../../features/listing-lifecycle/listing-lifecycle-console";

export const metadata: Metadata = {
  title: "Listing 生命周期 · KJDS AI ERP",
  description:
    "Exact-scope observed, desired, reviewed, approved, planned and readback Listing authority.",
};

export default function ListingsPage() {
  return <ListingLifecycleConsole />;
}
