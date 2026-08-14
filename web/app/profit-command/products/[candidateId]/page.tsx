import { ProfitCommandConsole } from "../../../../features/profit-command/profit-command-console";

export default async function ProfitProductDetailPage({
  params,
}: {
  params: Promise<{ candidateId: string }>;
}) {
  const { candidateId } = await params;
  return <ProfitCommandConsole surface="product-detail" candidateId={decodeURIComponent(candidateId)} />;
}
