export type ChannelAccountProjectionStatus = "ready" | "blocked" | "no_data";

export type ChannelAccountViewStatus =
  | ChannelAccountProjectionStatus
  | "loading"
  | "error";

export type ChannelAccountStateEvent =
  | { type: "request" }
  | { type: "failure" }
  | { type: "success"; status: ChannelAccountProjectionStatus };

export type ChannelAccountView = {
  dataState: ChannelAccountViewStatus;
  domState: `channel-account-${ChannelAccountViewStatus}`;
  showLoading: boolean;
  showRetry: boolean;
  showRows: boolean;
  showEmpty: boolean;
  heading: string;
  detail: string;
};

export function transitionChannelAccountState(
  _current: ChannelAccountViewStatus,
  event: ChannelAccountStateEvent,
): ChannelAccountViewStatus {
  if (event.type === "request") return "loading";
  if (event.type === "failure") return "error";
  return event.status;
}

export function channelAccountView(
  status: ChannelAccountViewStatus,
  rowCount: number,
  filtersApplied = false,
): ChannelAccountView {
  const stable = status !== "loading" && status !== "error";
  const showRows = stable && status !== "no_data" && rowCount > 0;
  const copy: Record<ChannelAccountViewStatus, [string, string]> = {
    loading: [
      "正在读取渠道账户权威",
      "数据返回前不会填充演示账户、凭据或运行身份。",
    ],
    error: [
      "渠道账户权威暂不可用",
      "读取失败；页面不回退到旧授权，也不推断连接状态。",
    ],
    no_data: [
      "真实 no_data",
      "当前 exact scope 尚无有效渠道账户绑定；未创建授权、凭据、Approval 或 Permit。",
    ],
    blocked: [
      "失败关闭",
      rowCount > 0
        ? "账户存在，但最新 Evidence、撤销、指纹、健康或运行身份验证阻断使用。"
        : "作用域或上游权威阻断；历史授权不会回退为当前事实。",
    ],
    ready: [
      rowCount > 0 ? "Exact-scope 权威可用" : "筛选结果为空",
      rowCount > 0
        ? "服务端已验证当前只读运行身份；投影本身仍不授予任何变更权限。"
        : filtersApplied
          ? "当前服务端筛选没有匹配账户。"
          : "权威快照可用，但当前没有返回账户。",
    ],
  };
  return {
    dataState: status,
    domState: `channel-account-${status}`,
    showLoading: status === "loading",
    showRetry: status === "error",
    showRows,
    showEmpty: stable && !showRows,
    heading: copy[status][0],
    detail: copy[status][1],
  };
}
