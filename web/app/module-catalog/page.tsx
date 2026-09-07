import type { Metadata } from "next";
import { ModuleCatalogConsole } from "../../features/module-catalog/module-catalog-console";

export const metadata: Metadata = {
  title: "功能模块中心 · KJDS",
  description: "KJDS 一至四级业务模块、操作步骤、输入输出和前置条件。",
};

export default function ModuleCatalogPage() {
  return <ModuleCatalogConsole />;
}
