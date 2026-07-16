import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KJDS 俄罗斯经营指挥中心",
  description: "以单品净利润为目标的 AI 跨境电商操作系统",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
