import { useCallback, useEffect, useState } from "react";
import { api, Dispute, Health, Policy, Preview, Wallet } from "./api";
import { Icon, P } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Chargebacks from "./pages/Chargebacks";
import Detail from "./pages/Detail";
import Customers from "./pages/Customers";
import WalletPage from "./pages/Wallet";

type Page = "dashboard" | "payments" | "chargebacks" | "customers" | "wallet" | "settings";

const NAV: { key: Page; label: string; icon: string; group: string }[] = [
  { key: "dashboard", label: "Dashboard", icon: P.grid, group: "Overview" },
  { key: "payments", label: "Payments", icon: P.card, group: "Overview" },
  { key: "chargebacks", label: "Chargebacks", icon: P.shield, group: "Disputes" },
  { key: "customers", label: "Customers", icon: P.users, group: "Disputes" },
  { key: "wallet", label: "Contest wallet", icon: P.wallet, group: "Disputes" },
  { key: "settings", label: "Settings", icon: P.cog, group: "Account" },
];

const Mark = () => (
  <svg width="16" height="19" viewBox="0 0 24 28" aria-hidden="true">
    <path d="M17.5 0 8.9 11.9h5.4L7.8 28 22 9.5h-5.6L21 0z" fill="#fff" />
    <path d="M9.4 3.2H2.6L0 7.7h6.6z" fill="#5b6b82" />
  </svg>
);

function Login({ onIn }: { onIn: () => void }) {
  return (
    <div className="login">
      <div className="login-left">
        <div className="inline"><Mark /><b style={{ fontSize: 14 }}>Razorpay</b></div>
        <h2>Every dispute, already read.</h2>
        <p>
          Chargebacks arrive with the evidence gathered, the reason-code
          requirements checked, and a recommendation you can audit before you act.
        </p>
        <div className="tiny" style={{ color: "#5b6b82", marginTop: 24 }}>
          Prototype · synthetic dispute data
        </div>
      </div>
      <div className="login-right">
        <div className="login-form">
          <h1 className="h1">Merchant Dashboard</h1>
          <p className="sub">Sign in to manage your payments, disputes and chargebacks.</p>
          <label htmlFor="e">Merchant email</label>
          <input id="e" className="field" defaultValue="finance@acmecommerce.in" />
          <label htmlFor="p">Password</label>
          <input id="p" className="field" type="password" defaultValue="demo1234"
                 onKeyDown={(e) => e.key === "Enter" && onIn()} />
          <button className="btn pri lg" style={{ width: "100%", marginTop: 18 }} onClick={onIn}>
            Sign in to Dashboard
          </button>
          <p className="tiny faint" style={{ textAlign: "center", marginTop: 14 }}>
            Signing in as Acme Commerce
          </p>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(false);
  const [page, setPage] = useState<Page>("dashboard");
  const [openId, setOpenId] = useState<string | null>(null);

  const [health, setHealth] = useState<Health | null>(null);
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [h, d, w, p] = await Promise.all([
        api.health(), api.disputes(), api.wallet(), api.policy(),
      ]);
      setHealth(h); setDisputes(d); setWallet(w);
      setPolicy(p.policy); setPreview(p.preview); setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (authed) void refresh(); }, [authed, refresh]);

  if (!authed) return <Login onIn={() => setAuthed(true)} />;

  const open = disputes.filter((d) => d.status === "open");

  const go = (p: Page) => { setPage(p); setOpenId(null); window.scrollTo(0, 0); };
  const openDispute = (id: string) => { setOpenId(id); setPage("chargebacks"); window.scrollTo(0, 0); };

  const crumbs = openId
    ? ["Acme Commerce", "Chargebacks", openId]
    : ["Acme Commerce", NAV.find((n) => n.key === page)?.label ?? "Dashboard"];

  const groups = [...new Set(NAV.map((n) => n.group))];

  return (
    <div className="shell">
      <aside className="side">
        <div className="side-brand"><Mark /><b>Razorpay</b></div>
        <div className="side-merchant">
          <div className="n">Acme Commerce</div>
          <div className="i mono">acc_····7842</div>
        </div>
        {groups.map((g) => (
          <div className="side-group" key={g}>
            <div className="eyebrow">{g}</div>
            {NAV.filter((n) => n.group === g).map((n) => (
              <button key={n.key} className="nav"
                      data-on={page === n.key ? "1" : "0"}
                      onClick={() => go(n.key)}>
                <Icon d={n.icon} />
                {n.label}
                {n.key === "chargebacks" && open.length > 0 && (
                  <span className="count">{open.length}</span>
                )}
              </button>
            ))}
          </div>
        ))}
        <div className="side-foot">
          {health ? (
            <>
              <div>Rulebook v{health.rulebook.version} · {health.rulebook.codes} codes</div>
              <div style={{ color: health.model.source === "learned" ? "#7f9c8e" : "#b58a55" }}>
                {health.model.source === "learned"
                  ? `Calibrated model · ECE ${health.model.validation?.ece.toFixed(3)}`
                  : "Heuristic fallback"}
              </div>
            </>
          ) : "Connecting…"}
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <nav className="crumbs">
            {crumbs.map((c, i) => (
              <span key={c + i} className="inline" style={{ gap: 6 }}>
                {i > 0 && <span>›</span>}
                {i === crumbs.length - 1 ? <b>{c}</b> : c}
              </span>
            ))}
          </nav>
          <div className="topbar-right">
            {wallet && (
              <button className="chip" onClick={() => go("wallet")} title="Contest wallet">
                <Icon d={P.wallet} size={12} />
                <span className="num">₹{wallet.balance.toLocaleString("en-IN")}</span>
              </button>
            )}
            {policy && (
              <span className={`badge ${policy.mode === "delegated" ? "acct" : "flat"}`}>
                <span className="dot" />
                {policy.mode === "delegated" ? "Agent acting" : "Manual review"}
              </span>
            )}
            <div className="avatar">AC</div>
          </div>
        </div>

        {err && (
          <div className="page">
            <div className="notice warn">
              <Icon d={P.alert} />
              <div>
                <b>Cannot reach the pipeline.</b> {err}
                <div className="tiny" style={{ marginTop: 6 }}>
                  Start it with <span className="mono">uvicorn app:app --port 8000</span> from
                  {" "}<span className="mono">serve/</span>, then{" "}
                  <button className="btn sm" onClick={() => void refresh()}>retry</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {!err && loading && <div className="page"><p className="muted">Loading queue…</p></div>}

        {!err && !loading && (
          <div className="page">
            {openId ? (
              <Detail id={openId} onBack={() => setOpenId(null)} onChanged={refresh}
                      onOpen={openDispute} />
            ) : page === "dashboard" ? (
              <Dashboard disputes={disputes} wallet={wallet} health={health}
                         preview={preview} policy={policy}
                         onOpen={openDispute} onNav={go} />
            ) : page === "chargebacks" ? (
              <Chargebacks disputes={disputes} onOpen={openDispute} />
            ) : page === "customers" ? (
              <Customers onOpen={openDispute} />
            ) : page === "wallet" ? (
              <WalletPage wallet={wallet} policy={policy} preview={preview}
                          health={health} onChanged={refresh} />
            ) : (
              <>
                <div className="page-head">
                  <div className="grow">
                    <h1 className="h1">{NAV.find((n) => n.key === page)?.label}</h1>
                    <p className="sub">Outside the scope of this prototype.</p>
                  </div>
                </div>
                <div className="card">
                  <Empty />
                </div>
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

const Empty = () => (
  <div className="empty">
    <h2 className="h2">Nothing here yet</h2>
    <p className="sub">
      This build covers the dispute loop end to end. Payments and account settings are stubs.
    </p>
  </div>
);
