import type { Metadata } from "next";
import { FrontendToolkitPage } from "../../features/frontend-toolkit/frontend-toolkit-page";

export const metadata: Metadata = {
  title: "内部设计研究 / internal_preview / not_for_sale | KJDS",
  description: "卖家前台的内部设计研究预览页，供评审页面结构、审美和实施路径，不构成销售。",
};

export default function Page() {
  return <FrontendToolkitPage />;
}
