import { useEffect, useState } from "react";
import { CustomerRow, api, inr } from "../api";
import { Card, CardHead, Empty, Icon, Notice, P, Stat } from "../components/ui";

export default function Customers({ onOpen }: { onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<CustomerRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [only, setOnly] = useState(true);

  useEffect(() => {
    api.customers().then((r) => setRows(r.customers)).catch((e) => setErr(e.message));
  }, []);

  if (err) return <Notice tone="warn">{err}</Notice>;
  if (!rows) return <p className="muted">Loading customers…</p>;

  const repeat = rows.filter((r) => r.repeat);
  const shown = only ? repeat : rows;
  const repeatAmount = repeat.reduce((s, r) => s + r.amount, 0);
  const allAmount = rows.reduce((s, r) => s + r.amount, 0);

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1 className="h1">Customers</h1>
          <p className="sub">Who is filing disputes, and who is filing them repeatedly.</p>
        </div>
        <div className="switch">
          <button data-on={only ? "1" : "0"} onClick={() => setOnly(true)}>Repeat filers</button>
          <button data-on={only ? "0" : "1"} onClick={() => setOnly(false)}>Everyone</button>
        </div>
      </div>

      <div className="grid g3">
        <Stat label="Customers in this batch" value={String(rows.length)} />
        <Stat label="Filed more than once" value={String(repeat.length)}
              detail={`${Math.round((repeat.length / Math.max(rows.length, 1)) * 100)}% of filers`}
              tone={repeat.length ? "warn" : undefined} />
        <Stat label="Disputed by repeat filers" value={inr(repeatAmount)}
              detail={`${Math.round((repeatAmount / Math.max(allAmount, 1)) * 100)}% of all disputed value`} />
      </div>

      <Card>
        <CardHead
          title={only ? "Repeat filers" : "All customers"}
          sub="Ranked by lifetime dispute count, then by value"
          right={<span className="badge flat">{shown.length} shown</span>}
        />
        {shown.length === 0 ? (
          <Empty title="No repeat filers in this batch"
                 body="Every customer here has filed exactly one dispute." />
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Customer</th><th className="right">Lifetime disputes</th>
                  <th className="right">In this batch</th><th className="right">Open</th>
                  <th className="right">Total disputed</th><th>Reason codes</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.customer_id}>
                    <td>
                      <div className="inline" style={{ gap: 6 }}>
                        <b>{r.name}</b>
                        {r.lifetime_disputes >= 3 && (
                          <span className="badge bad">
                            <Icon d={P.repeat} size={9} />high
                          </span>
                        )}
                      </div>
                      <div className="tiny faint mono">{r.email}</div>
                    </td>
                    <td className="right num"
                        style={{ color: r.repeat ? "var(--warn)" : undefined, fontWeight: 500 }}>
                      {r.lifetime_disputes}
                    </td>
                    <td className="right num">{r.disputes}</td>
                    <td className="right num">{r.open || "—"}</td>
                    <td className="right num">{inr(r.amount)}</td>
                    <td>
                      <div className="inline" style={{ gap: 4 }}>
                        {r.codes.slice(0, 4).map((c) => (
                          <span className="chip mono tiny" key={c}>{c}</span>
                        ))}
                        {r.codes.length > 4 && <span className="tiny faint">+{r.codes.length - 4}</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="card-foot">
          Lifetime count is this batch plus the prior-dispute count carried on the record itself.
          Customer identity is derived at serve time, not present in the generated data.
        </div>
      </Card>
    </>
  );
}
