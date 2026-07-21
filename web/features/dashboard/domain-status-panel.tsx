export type DomainState = "loading" | "ready" | "error";

type Props = {
  states: Record<string, DomainState>;
  onRetry: () => void;
};

const labels: Record<string, string> = {
  core: "核心状态",
  product: "商品与供应链",
  finance: "财务导入",
  science: "决策科学",
  execution: "执行运营",
};

export function DomainStatusPanel({ states, onRetry }: Props) {
  const failed = Object.entries(states).filter(([, state]) => state === "error");
  if (!failed.length) return null;

  return <section className="notice" role="alert" aria-label="领域加载状态">
    <span>{failed.map(([domain]) => labels[domain] ?? domain).join("、")}暂不可用；其他区域保留当前状态。</span>
    <button className="refresh" type="button" onClick={onRetry}>重试失败区域</button>
  </section>;
}
