import type { Metadata } from "next";
import { AgentStatusRail } from "../features/agent-control/agent-status-rail";
import "./globals.css";

export const metadata: Metadata = {
  title: "KJDS · Ozon 统一经营平台",
  description: "连接 Ozon 店铺、1688 供应链、商品内容、广告、订单利润与受控执行的 AI 经营操作系统",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        {children}
        <AgentStatusRail />
      </body>
    </html>
  );
}
