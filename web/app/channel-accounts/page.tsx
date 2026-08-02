import type { Metadata } from "next";
import { ChannelAccountConsole } from "../../features/channel-accounts/channel-account-console";

export const metadata: Metadata = {
  title: "Channel Accounts · KJDS",
  description: "Exact-scope channel account, store authorization, and runtime identity authority.",
};

export default function ChannelAccountsPage() {
  return <ChannelAccountConsole />;
}
