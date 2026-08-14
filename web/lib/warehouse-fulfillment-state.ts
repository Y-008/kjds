export type WarehouseStatus =
  | "loading"
  | "error"
  | "ready"
  | "partial"
  | "blocked"
  | "no_data";

export type WarehouseStateEvent =
  | { type: "request" }
  | { type: "failure" }
  | {
      type: "success";
      status: Exclude<WarehouseStatus, "loading" | "error">;
    };

export type WarehouseView = {
  dataState: WarehouseStatus;
  showRetry: boolean;
  showLoading: boolean;
  showRows: boolean;
  heading: string;
  domState: `warehouse-${WarehouseStatus}`;
  emptyMessage: string | null;
};

export function transitionWarehouseState(
  _current: WarehouseStatus,
  event: WarehouseStateEvent,
): WarehouseStatus {
  if (event.type === "request") return "loading";
  if (event.type === "failure") return "error";
  return event.status;
}

export function warehouseView(
  status: WarehouseStatus,
  rowCount: number,
): WarehouseView {
  const hasRows = rowCount > 0;
  return {
    dataState: status,
    showRetry: status === "error",
    showLoading: status === "loading",
    showRows:
      hasRows &&
      status !== "loading" &&
      status !== "error" &&
      status !== "no_data" &&
      status !== "blocked",
    heading:
      status === "no_data"
        ? "真实 no_data"
        : status === "blocked"
          ? "blocked"
          : status,
    domState: `warehouse-${status}`,
    emptyMessage:
      status === "no_data"
        ? "没有正式 Order、Inventory 或仓库执行事件；不合成 wave。"
        : status === "blocked"
          ? "最新权威验证失败；历史记录不会回退为当前事实。"
          : status === "ready" && rowCount === 0
            ? "过滤结果为空。"
            : null,
  };
}
