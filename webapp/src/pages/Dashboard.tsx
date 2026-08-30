import { Dispute, Health, Policy, Preview, Wallet, inr, pct } from "../api";
import { Card, CardHead, Icon, Meter, P, RecoBadge, Stat, StatusBadge } from "../components/ui";

export default function Dashboard({
  disputes, wallet, health, preview, policy, onOpen, onNav,
}: {
  disputes: Dispute[]; wallet: Wallet | null; health: Health | null;
  preview: Preview | null; policy: Policy | null;
  onOpen: (id: string) => void; onNav: (p: any) => void;
}) {
  const open = disputes.filter((d) => d.status === "open");
  const atStake = open.reduce((s, d) => s + d.amount, 0);
  const worthFighting = open.filter((d) => d.recommendation === "contest");
  const blocked = open.filter((d) => d.blocked);
  const repeat = new Set(
    disputes.filter((d) => d.prior_disputes > 0).map((d) => d.customer.customer_id)
  );
  const people = new Set(disputes.map((d) => d.customer.customer_id));

  // Sort the queue by what the policy says is at stake, not by date. The point
  // of the product is that recency is the wrong ordering.
  const byValue = [...open].sort((a, b) => b.ev.value - a.ev.value).slice(0, 6);

  const recoverable = worthFighting.reduce(
    (s, d) => s + d.amount * d.p_win * (health?.constants.net_recovery_fraction ?? 0.85), 0);

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1 className="h1">Good morning, Acme Commerce</h1>
          <p className="sub">
            {open.length} disputes are waiting on a decision. The agent thinks{" "}
            {worthFighting.length} are worth fighting.
          </p>
        </div>
        <button className="btn" onClick={() => onNav("chargebacks")}>
          Open the queue <Icon d={P.right} size={12} />
        </button>
      </div>

      <div className="grid g5">
        <Stat label="Open disputes" value={String(open.length)}
              detail={`of ${disputes.length} in this batch`} />
        <Stat label="Amount at dispute" value={inr(atStake)}
              detail="across open cases" />
        <Stat label="Worth contesting" value={String(worthFighting.length)}
              detail={`${inr(recoverable)} expected back`} tone="accent" />
        <Stat label="Short of evidence" value={String(blocked.length)}
              detail="packet fails the rulebook" tone={blocked.length ? "warn" : undefined} />
        <Stat label="Repeat filers" value={pct(repeat.size / Math.max(people.size, 1))}
              detail={`${repeat.size} of ${people.size} customers`} />
      </div>

      <div className="split" style={{ marginTop: 12 }}>
        <Card>
          <CardHead
            title="Highest value first"
            sub="Ordered by expected value, not by date filed"
            right={<button className="btn sm" onClick={() => onNav("chargebacks")}>View all</button>}
          />
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Dispute</th><th>Customer</th><th>Code</th>
                  <th className="right">Amount</th><th>p(win)</th>
                  <th className="right">Expected value</th><th>Call</th>
                </tr>
              </thead>
              <tbody>
                {byValue.map((d) => (
                  <tr key={d.id} data-click="1" onClick={() => onOpen(d.id)}>
                    <td className="id">{d.id}</td>
                    <td>
                      {d.customer.name}
                      {d.prior_disputes > 0 && (
                        <span className="badge warn" style={{ marginLeft: 6 }}>
                          {d.prior_disputes + 1}x
                        </span>
                      )}
                    </td>
                    <td className="mono tiny">{d.network} {d.reason_code}</td>
                    <td className="right num">{inr(d.amount)}</td>
                    <td style={{ width: 70 }}>
                      <span className="num tiny">{pct(d.p_win)}</span>
                      <Meter value={d.p_win} tone={d.p_win > 0.6 ? "good" : d.p_win < 0.35 ? "warn" : undefined} />
                    </td>
                    <td className="right num" style={{ color: d.ev.positive ? "var(--good)" : "var(--ink-4)" }}>
                      {d.ev.value > 0 ? "+" : ""}{inr(d.ev.value)}
                    </td>
                    <td><RecoBadge d={d} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card-foot">
            Expected value is p(win) × amount × {health?.constants.net_recovery_fraction} minus the
            cost of the branch each case would actually take.
          </div>
        </Card>

        <div className="stack">
          <Card>
            <CardHead title="Contest wallet" sub="What triage has spent and returned" />
            <div className="card-body">
              <div className="inline" style={{ justifyContent: "space-between" }}>
                <div>
                  <div className="eyebrow">Balance</div>
                  <div className="num" style={{ fontSize: 22, marginTop: 2 }}>
                    {inr(wallet?.balance ?? 0)}
                  </div>
                </div>
                <div className="right">
                  <div className="eyebrow">Net so far</div>
                  <div className="num" style={{
                    fontSize: 22, marginTop: 2,
                    color: (wallet?.net ?? 0) >= 0 ? "var(--good)" : "var(--bad)",
                  }}>
                    {(wallet?.net ?? 0) >= 0 ? "+" : ""}{inr(wallet?.net ?? 0)}
                  </div>
                </div>
              </div>
              <dl style={{ margin: "12px 0 0" }}>
                <div className="kv"><dt>Spent contesting</dt>
                  <dd className="num">{inr(wallet?.spent ?? 0)}</dd></div>
                <div className="kv"><dt>Recovered</dt>
                  <dd className="num">{inr(wallet?.recovered ?? 0)}</dd></div>
              </dl>
              <button className="btn" style={{ width: "100%", marginTop: 12 }}
                      onClick={() => onNav("wallet")}>
                Wallet and automation
              </button>
            </div>
          </Card>

          <Card>
            <CardHead
              title="Automation"
              sub={policy?.mode === "delegated" ? "Agent is acting within your limits" : "You review every dispute"}
              right={<span className={`badge ${policy?.mode === "delegated" ? "acct" : "flat"}`}>
                {policy?.mode === "delegated" ? "On" : "Off"}
              </span>}
            />
            <div className="card-body">
              {preview && (
                <p className="tiny muted" style={{ margin: 0 }}>
                  Under your current limits the agent would handle{" "}
                  <b className="num">{preview.auto_count}</b> of {open.length} open disputes and
                  leave <b className="num">{preview.held_count}</b> for you, spending{" "}
                  <b className="num">{inr(preview.projected_spend)}</b>.
                </p>
              )}
              <button className="btn" style={{ width: "100%", marginTop: 12 }}
                      onClick={() => onNav("wallet")}>
                {policy?.mode === "delegated" ? "Adjust limits" : "Set up automation"}
              </button>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
