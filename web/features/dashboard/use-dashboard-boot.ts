import { Dispatch, SetStateAction, useEffect } from "react";
import { fetchJson } from "../../lib/fetch-json";
import type { WebSession } from "./contracts";

type BootOptions = {
  load: (signal?: AbortSignal) => Promise<void>;
  setSession: Dispatch<SetStateAction<WebSession | null>>;
  setNotice: Dispatch<SetStateAction<string>>;
};

export function useDashboardBoot({ load, setSession, setNotice }: BootOptions) {
  useEffect(() => {
    const controller = new AbortController();

    async function boot() {
      const response = await fetchJson("/auth/session", { cache: "no-store", signal: controller.signal });
      if (response.status === 401) return window.location.assign("/login");
      if (response.status === 428) return window.location.assign("/mfa");
      if (!response.ok) {
        const body = await response.json();
        setNotice(body.detail ?? "Web 身份服务尚未就绪");
        return;
      }
      setSession(await response.json());
      await load(controller.signal);
    }

    void boot();
    return () => controller.abort("dashboard unmounted");
  }, [load, setNotice, setSession]);
}
