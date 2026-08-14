import type { Metadata } from "next";
import { MediaFactoryConsole } from "../../features/media-factory/media-factory-console";

export const metadata: Metadata = {
  title: "内容媒体工厂 · KJDS AI ERP",
  description:
    "Exact-scope ContentAsset, media execution timeline, QA and Delivery Manifest authority.",
};

export default function MediaFactoryPage() {
  return <MediaFactoryConsole />;
}
