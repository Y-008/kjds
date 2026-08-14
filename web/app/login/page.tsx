import {
  ArrowRight,
  BadgeRussianRuble,
  BarChart3,
  Boxes,
  Image as ImageIcon,
  LockKeyhole,
  ShieldCheck,
  Store,
} from "lucide-react";

type LoginPageProps = {
  searchParams: Promise<{ error?: string }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const { error } = await searchParams;
  const errorMessage = error === "origin"
    ? "该登录请求不是从 KJDS 登录页发起，已被安全门拒绝。请在本页重新登录。"
    : "登录未通过，请核对账号或联系管理员检查身份绑定。";
  return (
    <main className="login-shell">
      <section className="login-story">
        <div className="login-brand">
          <span><Store size={19} /></span>
          <div><strong>KJDS</strong><small>OZON OPERATING SYSTEM</small></div>
        </div>
        <div className="login-story-copy">
          <span className="login-kicker">ONE STORE · ONE SOURCE OF TRUTH</span>
          <h1>一个店铺，一套事实，<br />一条受控增长链。</h1>
          <p>把 Ozon 店铺、1688 货源、商品内容、同行价格、广告、订单与实际利润统一到同一个经营平台。</p>
        </div>
        <div className="login-capabilities">
          <article><Boxes size={20} /><div><strong>1688 全成本</strong><span>三家报价、十五项成本、样品与备选供应商</span></div></article>
          <article><BarChart3 size={20} /><div><strong>Ozon 增长诊断</strong><span>价格带、转化、评价、库存和广告上限</span></div></article>
          <article><ImageIcon size={20} /><div><strong>商品内容工厂</strong><span>七类图片、俄语 Listing、QA 与权利证据</span></div></article>
          <article><BadgeRussianRuble size={20} /><div><strong>订单与真实利润</strong><span>CM3、平台费用、结算、银行与 FX 对账</span></div></article>
        </div>
        <div className="login-trust">
          <ShieldCheck size={18} />
          <span>AI 负责解释和建议，真实改价、发布与广告由独立审批控制。</span>
        </div>
      </section>

      <section className="login-access">
        <div className="login-card">
          <div className="login-card-heading">
            <span className="login-lock"><LockKeyhole size={19} /></span>
            <div>
              <p className="eyebrow">CONTROLLED ACCESS</p>
              <h2>登录经营平台</h2>
            </div>
          </div>
          <p className="login-intro">使用分配给你的运营或审批账号。角色由服务端身份绑定决定，页面不提供角色切换。</p>
          {error ? (
            <div className="login-error" role="alert">
              {errorMessage}
            </div>
          ) : null}
          <form action="/auth/login" method="post">
            <label>
              工作邮箱
              <input name="email" type="email" autoComplete="username" placeholder="name@company.com" required autoFocus />
            </label>
            <label>
              密码
              <input name="password" type="password" autoComplete="current-password" placeholder="输入你的密码" required />
            </label>
            <button type="submit">进入经营平台 <ArrowRight size={17} /></button>
          </form>
          <div className="login-security-note">
            <LockKeyhole size={15} />
            <p><strong>安全边界</strong><span>浏览器不会获得 Ozon API 密钥；审批账号执行关键操作时还需通过 AAL2 复验。</span></p>
          </div>
        </div>
        <p className="login-footer">KJDS · Evidence-first commerce control plane</p>
      </section>
    </main>
  );
}
