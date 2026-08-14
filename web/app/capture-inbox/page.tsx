import type { Metadata } from "next";
import { BrowserCaptureInboxConsole } from "../../features/browser-capture-inbox/browser-capture-inbox-console";

export const metadata: Metadata = {
  title: "Browser Capture Inbox · KJDS",
  description: "User-initiated 1688/Ozon page Evidence staging.",
};

export default function BrowserCaptureInboxPage() {
  return <BrowserCaptureInboxConsole />;
}
