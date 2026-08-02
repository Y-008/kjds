import type { Metadata } from "next";
import { NativeParityConsole } from "../../features/native-parity/native-parity-console";

export const metadata: Metadata = {
  title: "Native Parity Acceptance · KJDS",
  description: "Capability-granular, verifier-owned native parity acceptance authority.",
};

export default function NativeParityPage() {
  return <NativeParityConsole />;
}
