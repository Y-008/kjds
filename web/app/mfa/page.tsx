"use client";

import { useEffect, useState } from "react";

type MfaStatus = {
  required: boolean;
  verified: boolean;
  enrolled: boolean;
  factor_id: string | null;
};

export default function MfaPage() {
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [factorId, setFactorId] = useState("");
  const [qrCode, setQrCode] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("正在检查审批人安全状态…");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      const response = await fetch("/auth/mfa/status", { cache: "no-store" });
      if (response.status === 401) {
        window.location.assign("/login");
        return;
      }
      const result = await response.json();
      if (!response.ok) {
        setMessage(result.detail ?? "无法读取 MFA 状态");
        return;
      }
      const nextStatus = result as MfaStatus;
      if (!nextStatus.required || nextStatus.verified) {
        window.location.assign("/");
        return;
      }
      setStatus(nextStatus);
      setFactorId(nextStatus.factor_id ?? "");
      setMessage(nextStatus.enrolled ? "输入认证器中的六位动态码。" : "先绑定认证器，再输入六位动态码。");
    })();
  }, []);

  async function enroll() {
    setBusy(true);
    setMessage("正在创建安全绑定…");
    const response = await fetch("/auth/mfa/enroll", { method: "POST" });
    const result = await response.json();
    if (response.ok) {
      setFactorId(result.factor_id);
      setQrCode(result.qr_code);
      setStatus((current) => current ? { ...current, enrolled: true, factor_id: result.factor_id } : current);
      setMessage("用认证器扫描二维码，然后输入六位动态码。");
    } else {
      setMessage(result.detail ?? "无法绑定认证器");
    }
    setBusy(false);
  }

  async function verify(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("正在验证动态码…");
    const response = await fetch("/auth/mfa/verify", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ factor_id: factorId, code }),
    });
    const result = await response.json();
    if (response.ok) {
      window.location.assign("/");
      return;
    }
    setMessage(result.detail ?? "动态码验证失败");
    setBusy(false);
  }

  return (
    <main className="login-shell">
      <section className="login-card">
        <p className="eyebrow">APPROVER MFA</p>
        <h1>审批人双重验证</h1>
        <p>审批账号必须达到 AAL2 才能进入控制台。运营账号不会在这里获得审批权限。</p>
        <div className="login-error">{message}</div>
        {status && !status.enrolled ? (
          <button type="button" disabled={busy} onClick={enroll}>绑定认证器</button>
        ) : null}
        {qrCode ? <img className="mfa-qr" src={qrCode} alt="认证器绑定二维码" /> : null}
        {status?.enrolled ? (
          <form onSubmit={verify}>
            <label>
              六位动态码
              <input
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="\d{6}"
                required
              />
            </label>
            <button type="submit" disabled={busy || !factorId || code.length !== 6}>验证并进入</button>
          </form>
        ) : null}
        <form action="/auth/logout" method="post">
          <button type="submit">退出当前账号</button>
        </form>
        <small>恢复码、因素撤销和人员离职仍由管理员在 Supabase 控制台处理并留痕。</small>
      </section>
    </main>
  );
}
