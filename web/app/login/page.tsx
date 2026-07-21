type LoginPageProps = {
  searchParams: Promise<{ error?: string }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const { error } = await searchParams;
  return (
    <main className="login-shell">
      <section className="login-card">
        <p className="eyebrow">KJDS CONTROLLED ACCESS</p>
        <h1>登录经营控制台</h1>
        <p>运营人与审批人必须使用各自账号。系统不会在页面中提供角色切换，也不会把后台密钥交给浏览器。</p>
        {error ? <div className="login-error">登录未通过，请核对账号或联系管理员检查身份绑定。</div> : null}
        <form action="/auth/login" method="post">
          <label>
            邮箱
            <input name="email" type="email" autoComplete="username" required />
          </label>
          <label>
            密码
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          <button type="submit">登录</button>
        </form>
        <small>批准操作仍会在控制面复验审批状态、申请人身份和 Listing 快照。</small>
      </section>
    </main>
  );
}
