import type { Metadata } from "next";
import { BiWallboard } from "../../../features/bi/wallboard";

export const metadata: Metadata = {
  title: "经营流转大屏 · KJDS",
  description: "固定时点、异常置顶、只读轮播的 KJDS 经营数据大屏。",
};

export default function BiWallboardPage() {
  return <BiWallboard />;
}
