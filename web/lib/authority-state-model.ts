export type AuthorityStatus =
  | "loading"
  | "error"
  | "ready"
  | "partial"
  | "blocked"
  | "no_data";

export type AuthorityStateEvent =
  | { type: "request" }
  | { type: "failure" }
  | {
      type: "success";
      status: Exclude<AuthorityStatus, "loading" | "error">;
    };

export function transitionAuthorityState(
  _current: AuthorityStatus,
  event: AuthorityStateEvent,
): AuthorityStatus {
  if (event.type === "request") return "loading";
  if (event.type === "failure") return "error";
  return event.status;
}

export function authorityStateView(
  status: AuthorityStatus,
  hasRows: boolean,
) {
  return {
    dataState: status,
    showRetry: status === "error",
    showLoading: status === "loading",
    showRows:
      hasRows &&
      status !== "loading" &&
      status !== "error" &&
      status !== "no_data",
    heading:
      status === "no_data"
        ? "真实 no_data"
        : status === "blocked"
          ? "blocked"
          : status === "ready"
            ? "ready"
            : status === "partial"
              ? "partial"
              : status,
  };
}
