import type { Metadata } from "next";
import { CapabilityAtlas } from "../../features/capability-atlas/capability-atlas";

export const metadata: Metadata = {
  title: "AI 跨境能力图谱 · KJDS",
  description: "逐项覆盖 LinkFox，面向 Russia/Ozon 落地并扩展全球平台的 AI 跨境经营能力树。",
};

export default function CapabilityAtlasPage() {
  return <CapabilityAtlas />;
}
