import { useMemo, useState } from "react";
import { Dispute, inr, pct, shortDate } from "../api";
import { Card, Empty, Icon, Meter, P, RecoBadge, StatusBadge } from "../components/ui";

type Tab = "open" | "contest" | "accept" | "blocked" | "done" | "all";

const TABS: { key: Tab; label: string }[] = [
  { key: "open", label: "Needs decision" },
  { key: "contest", label: "Agent says contest" },
  { key: "accept", label: "Agent says accept" },
  { key: "blocked", label: "Evidence short" },
  { key: "done", label: "Decided" },
  { key: "all", label: "All" },
];

const match = (d: Dispute, t: Tab) => ({
  open: d.status === "open",
  contest: d.status === "open" && d.recommendation === "contest",
  accept: d.status === "open" && d.recommendation === "accept",
  blocked: d.status === "open" && d.blocked,
  done: d.status !== "open",
  all: true,
}[t]);

export default function Chargebacks({
  disputes, onOpen,
}: { disputes: Dispute[]; onOpen: (id: string) => void }) {
  const [tab, setTab] = useState<Tab>("open");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"ev" | "amount" | "p">("ev");

  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    const out = disputes.filter((d) => {
      if (!match(d, tab)) return false;
      if (!t) return true;
      return d.id.toLowerCase().includes(t)
        || d.customer.name.toLowerCase().includes(t)
        || d.reason_code.toLowerCase().includes(t)
        || d.description.toLowerCase().includes(t);
    });
    const key = { ev: (d: Dispute) => d.ev.value, amount: (d: Dispute) => d.amount, p: (d: Dispute) => d.p_win };
    return out.sort((a, b) => key[sort](b) - key[sort](a));
  }, [disputes, tab, q, sort]);

  const totals = useMemo(
    () => Object.fromEntries(TABS.map((t) => [t.key, disputes.filter((d) => match(d, t.key)).length])),
    [disputes]
  );

  const stake = rows.reduce((s, d) => s + d.amount, 0);

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1 className="h1">Chargebacks</h1>
          <p className="sub">Review disputes and decide which ones are worth contesting.</p>
        </div>
      </div>

      <div className="toolbar">
        <div className="search" style={{ position: "relative" }}>
          <span style={{ position: "absolute", left: 9, top: 7, color: "var(--ink-4)" }}>
            <Icon d={P.search} size={13} />
          </span>
          <input className="field" style={{ paddingLeft: 28 }} value={q}
                 onChange={(e) => setQ(e.target.value)}
                 placeholder="Search dispute ID, customer, reason code" />
        </div>
        <select className="field" style={{ width: "auto" }} value={sort}
                onChange={(e) => setSort(e.target.value as any)}>
          <option value="ev">Sort by expected value</option>
          <option value="amount">Sort by amount</option>
          <option value="p">Sort by win probability</option>
        </select>
      </div>

      <Card>
        <div className="tabs">
          {TABS.map((t) => (
            <button key={t.key} className="tab" data-on={tab === t.key ? "1" : "0"}
                    onClick={() => setTab(t.key)}>
              {t.label}<span className="c">{totals[t.key]}</span>
            </button>
          ))}
        </div>

        {rows.length === 0 ? (
          <Empty title="No disputes in this view"
                 body="Clear the search or pick a different tab." />
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Dispute</th><th>Filed</th><th>Customer</th><th>Reason</th>
                  <th className="right">Amount</th><th>p(win)</th>
                  <th className="right">Expected value</th><th>Recommendation</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id} data-click="1" onClick={() => onOpen(d.id)}>
                    <td className="id">{d.id}</td>
                    <td className="num tiny muted">{shortDate(d.filed_on)}</td>
                    <td>
                      {d.customer.name}
                      {d.prior_disputes > 0 && (
                        <span className="badge warn" style={{ marginLeft: 6 }}
                              title="This customer has filed before">
                          <Icon d={P.repeat} size={9} />{d.prior_disputes + 1}
                        </span>
                      )}
                    </td>
                    <td style={{ maxWidth: 230 }}>
                      <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {d.description || d.category}
                      </div>
                      <div className="mono tiny faint">{d.network} {d.reason_code}</div>
                    </td>
                    <td className="right num">{inr(d.amount)}</td>
                    <td style={{ width: 74 }}>
                      <span className="num tiny">{pct(d.p_win)}</span>
                      <Meter value={d.p_win}
                             tone={d.p_win > 0.6 ? "good" : d.p_win < 0.35 ? "warn" : undefined} />
                    </td>
                    <td className="right num"
                        style={{ color: d.ev.positive ? "var(--good)" : "var(--ink-4)" }}>
                      {d.ev.value > 0 ? "+" : ""}{inr(d.ev.value)}
                    </td>
                    <td>
                      <RecoBadge d={d} />
                      {d.blocked && (
                        <span className="badge warn" style={{ marginLeft: 4 }} title="Packet is short of the rulebook requirement">
                          short
                        </span>
                      )}
                    </td>
                    <td><StatusBadge s={d.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="card-foot">
          <span className="num">{rows.length}</span> disputes ·
          <span className="num">{inr(stake)}</span> at stake
          <span className="spacer" />
          <span>p(win) from the calibrated model; expected value from the EV policy</span>
        </div>
      </Card>
    </>
  );
}
