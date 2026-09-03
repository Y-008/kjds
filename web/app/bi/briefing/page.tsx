import type { Metadata } from "next";
import { BiBriefing } from "../../../features/bi/briefing";

export const metadata: Metadata = {
  title: "经营简报 · KJDS",
  description: "固定作用域、手动翻页且保留数据缺口与 Evidence 边界的 KJDS 经营简报。",
};

export default function BiBriefingPage() {
  return <BiBriefing />;
}
