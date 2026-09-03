import { useMemo, useState } from "react";
import { Dispute, inr, pct, shortDate } from "../api";
import {
  Card, Empty, Icon, Meter, P, RecoBadge, SortDir, SortHeader,
  StatusBadge, TableSkeleton,
} from "../components/ui";
type Tab = "open" | "contest" | "accept" | "blocked" | "done" | "all";
type Col = "ev" | "amount" | "p" | "filed" | "id";

const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: "open", label: "Needs decision", hint: "Not yet actioned" },
  { key: "contest", label: "Agent says contest", hint: "Positive expected value" },
  { key: "accept", label: "Agent says accept", hint: "Not worth the attempt" },
  { key: "blocked", label: "Evidence short", hint: "Packet fails the rulebook" },
  { key: "done", label: "Decided", hint: "Already actioned" },
  { key: "all", label: "All", hint: "Everything in the queue" },
];

const match = (d: Dispute, t: Tab) => ({
  open: d.status === "open",
  contest: d.status === "open" && d.recommendation === "contest",
  accept: d.status === "open" && d.recommendation === "accept",
  blocked: d.status === "open" && d.blocked,
  done: d.status !== "open",
  all: true,
}[t]);

const KEY: Record<Col, (d: Dispute) => number | string> = {
  ev: (d) => d.ev.value,
  amount: (d) => d.amount,
  p: (d) => d.p_win,
  filed: (d) => d.filed_on,
  id: (d) => d.id,
};

/** Default direction per column: money and probability read best high-first,
 *  identifiers and dates low-first. Guessing wrong here costs a click every
 *  time someone sorts. */
const DEFAULT_DIR: Record<Col, SortDir> = {
  ev: "desc", amount: "desc", p: "desc", filed: "asc", id: "asc",
};

export default function Chargebacks({
  disputes, onOpen, loading = false,
}: {
  disputes: Dispute[];
  onOpen: (id: string) => void;
  loading?: boolean;
}) {
  const [tab, setTab] = useState<Tab>("open");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Col>("ev");
  const [dir, setDir] = useState<SortDir>("desc");

  const hit = (d: Dispute, t: string) =>
    !t || d.id.toLowerCase().includes(t)
      || d.customer.name.toLowerCase().includes(t)
      || d.reason_code.toLowerCase().includes(t)
      || d.description.toLowerCase().includes(t);

  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    const out = disputes.filter((d) => match(d, tab) && hit(d, t));
    const k = KEY[sort];
    const sign = dir === "asc" ? 1 : -1;
    return [...out].sort((a, b) => {
      const va = k(a), vb = k(b);
      if (typeof va === "string" || typeof vb === "string")
        return sign * String(va).localeCompare(String(vb));
      return sign * (va - vb);
    });
  }, [disputes, tab, q, sort, dir]);

  /* Tab counts follow the search. Counts that ignore the active filter send
     people to a tab reading "12" that then shows nothing. */
  const totals = useMemo(() => {
    const t = q.trim().toLowerCase();
    return Object.fromEntries(
      TABS.map((x) => [x.key, disputes.filter((d) => match(d, x.key) && hit(d, t)).length])
    ) as Record<Tab, number>;
  }, [disputes, q]);

  const onSort = (col: string) => {
    const c = col as Col;
    if (c === sort) setDir(dir === "asc" ? "desc" : "asc");
    else { setSort(c); setDir(DEFAULT_DIR[c]); }
  };

  /* Rows are clickable, so they must also be reachable by keyboard. Without
     this the whole table is invisible to tab navigation. */
  const rowKeys = (id: string) => ({
    tabIndex: 0,
    role: "link" as const,
    "aria-label": `Open dispute ${id}`,
    onClick: () => onOpen(id),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(id); }
    },
  });

  const stake = rows.reduce((s, d) => s + d.amount, 0);
  const searching = q.trim().length > 0;

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
          <input className="field" style={{ paddingLeft: 28, paddingRight: 30 }} value={q}
                 onChange={(e) => setQ(e.target.value)}
                 aria-label="Search disputes"
                 placeholder="Search dispute ID, customer, reason code" />
          {searching && (
            <button type="button" className="field-clear" aria-label="Clear search"
                    onClick={() => setQ("")}>
              <Icon d={P.x} size={12} />
            </button>
          )}
        </div>
      </div>

      <Card>
        <div className="tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t.key} className="tab" role="tab" title={t.hint}
                    aria-selected={tab === t.key}
                    data-on={tab === t.key ? "1" : "0"}
                    onClick={() => setTab(t.key)}>
              {t.label}<span className="c">{loading ? "–" : totals[t.key]}</span>
            </button>
          ))}
        </div>

        {!loading && rows.length === 0 ? (
          <Empty
            title={searching ? "Nothing matches that search" : "No disputes in this view"}
            body={searching
              ? `No dispute in "${TABS.find((t) => t.key === tab)!.label}" matches “${q.trim()}”.`
              : "Every dispute in this tab has been actioned."}
            action={searching
              ? <button className="btn ghost" onClick={() => setQ("")}>Clear search</button>
              : tab !== "all"
                ? <button className="btn ghost" onClick={() => setTab("all")}>Show all disputes</button>
                : undefined}
          />
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <SortHeader label="Dispute" col="id" active={sort} dir={dir} onSort={onSort} />
                  <SortHeader label="Filed" col="filed" active={sort} dir={dir} onSort={onSort} />
                  <th>Customer</th>
                  <th>Reason</th>
                  <SortHeader label="Amount" col="amount" active={sort} dir={dir}
                              onSort={onSort} align="right" />
                  <SortHeader label="p(win)" col="p" active={sort} dir={dir}
                              onSort={onSort} width={84} />
                  <SortHeader label="Expected value" col="ev" active={sort} dir={dir}
                              onSort={onSort} align="right" />
                  <th>Recommendation</th>
                  <th>Status</th>
                </tr>
              </thead>

              {loading ? <TableSkeleton cols={9} /> : (
                <tbody>
                  {rows.map((d) => (
                    <tr key={d.id} data-click="1" {...rowKeys(d.id)}>
                      <td className="id">{d.id}</td>
                      <td className="num tiny muted">{shortDate(d.filed_on)}</td>
                      <td>
                        {d.customer.name}
                        {d.prior_disputes > 0 && (
                          <span className="badge warn" style={{ marginLeft: 6 }}
                                title={`${d.prior_disputes + 1} disputes from this customer`}>
                            <Icon d={P.repeat} size={9} />{d.prior_disputes + 1}
                          </span>
                        )}
                      </td>
                      <td style={{ maxWidth: 230 }}>
                        <div className="clip" title={d.description || d.category}>
                          {d.description || d.category}
                        </div>
                        <div className="mono tiny faint">{d.network} {d.reason_code}</div>
                      </td>
                      <td className="right num">{inr(d.amount)}</td>
                      <td style={{ width: 84 }}>
                        <span className="num tiny">{pct(d.p_win)}</span>
                        <Meter value={d.p_win}
                               tone={d.p_win > 0.6 ? "good" : d.p_win < 0.35 ? "warn" : undefined} />
                      </td>
                      <td className="right num"
                          style={{ color: d.ev.positive ? "var(--good)" : "var(--ink-4)" }}>
                        {d.ev.positive ? "+" : ""}{inr(d.ev.value)}
                      </td>
                      <td>
                        <RecoBadge d={d} />
                        {d.blocked && (
                          <span className="badge warn" style={{ marginLeft: 4 }}
                                title="Packet is short of the rulebook requirement, so it cannot be submitted">
                            short
                          </span>
                        )}
                      </td>
                      <td><StatusBadge s={d.status} /></td>
                    </tr>
                  ))}
                </tbody>
              )}
            </table>
          </div>
        )}

        <div className="card-foot">
          {loading ? <span className="muted">Loading disputes…</span> : (
            <>
              <span className="num">{rows.length}</span> disputes ·
              <span className="num">{inr(stake)}</span> at stake
            </>
          )}
          <span className="spacer" />
          <span>p(win) from the calibrated model; expected value from the EV policy</span>
        </div>
      </Card>
    </>
  );
}