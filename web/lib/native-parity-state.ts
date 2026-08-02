import type { AcceptanceState } from "../features/native-parity/contracts";

export type NativeParityViewState = "loading" | "ready" | "no_data" | "error";

export function nativeParityView(
  state: NativeParityViewState,
  itemCount: number,
  filtered: boolean,
) {
  if (state === "loading" || state === "error") return state;
  if (itemCount > 0) return "ready";
  return filtered ? "filtered_empty" : "no_data";
}

export function stateLabel(state: AcceptanceState) {
  return {
    mapped: "仅完成映射",
    implemented_unverified: "已实现、未验证",
    gated: "验收门禁中",
    verified_native: "原生验证通过",
    blocked: "失败关闭",
    stale: "验证过期",
  }[state];
}
