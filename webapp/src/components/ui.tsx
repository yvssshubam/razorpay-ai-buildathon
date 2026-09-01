import React from "react";
import { Dispute, STATUS_LABEL, STATUS_TONE, inr, pct } from "../api";

/* Inline SVG rather than an icon package: eight glyphs do not justify a
   dependency, and these inherit currentColor cleanly. */
export const Icon = ({ d, size = 14 }: { d: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth="2" strokeLinecap="round"
       strokeLinejoin="round" aria-hidden="true" style={{ flex: "0 0 auto" }}>
    <path d={d} />
  </svg>
);

export const P = {
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
  card: "M2 7h20v12H2zM2 11h20",
  shield: "M12 2l8 4v6c0 5-3.4 8.5-8 10-4.6-1.5-8-5-8-10V6z",
  chart: "M3 21V9M9 21V3M15 21v-7M21 21V6",
  users: "M16 21v-2a4 4 0 0 0-8 0v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
  wallet: "M3 7h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H3zM3 7V5h13M17 13h.01",
  cog: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 0 0-1.7-1L14.5 3h-4l-.4 2.6a7 7 0 0 0-1.7 1l-2.3-1-2 3.4L6 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 1.7 1l.4 2.6h4l.4-2.6a7 7 0 0 0 1.7-1l2.3 1 2-3.4-2-1.5c.06-.3.1-.66.1-1z",
  check: "M20 6L9 17l-5-5",
  x: "M18 6L6 18M6 6l12 12",
  alert: "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M12 6v6l4 2",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16M21 21l-4.3-4.3",
  left: "M19 12H5M12 19l-7-7 7-7",
  right: "M5 12h14M12 5l7 7-7 7",
  doc: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
  bolt: "M13 2L3 14h9l-1 8 10-12h-9z",
  repeat: "M17 1l4 4-4 4M3 11V9a4 4 0 0 1 4-4h14M7 23l-4-4 4-4M21 13v2a4 4 0 0 1-4 4H3",
  plus: "M12 5v14M5 12h14",
  help: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M12 16v-4M12 8h.01",
  down: "M12 5v14M19 12l-7 7-7-7",
  up: "M12 19V5M5 12l7-7 7 7",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z",
};

export const Card: React.FC<{ children: React.ReactNode; className?: string }> = ({
  children, className = "",
}) => <section className={`card ${className}`}>{children}</section>;

export const CardHead: React.FC<{
  title: string; sub?: string; right?: React.ReactNode;
}> = ({ title, sub, right }) => (
  <header className="card-head">
    <div className="grow">
      <h2 className="h2">{title}</h2>
      {sub && <p className="sub">{sub}</p>}
    </div>
    {right}
  </header>
);

export const Stat: React.FC<{
  label: string; value: string; detail?: string; tone?: string; loading?: boolean;
}> = ({ label, value, detail, tone, loading }) => (
  <div className="card stat">
    <div className="k">{label}</div>
    {loading
      ? <Skeleton w="60%" h={22} />
      : <div className="v" style={tone ? { color: `var(--${tone})` } : undefined}>{value}</div>}
    {detail && !loading && <div className="d">{detail}</div>}
    {loading && <Skeleton w="40%" h={11} style={{ marginTop: 6 }} />}
  </div>
);

export const StatusBadge: React.FC<{ s: Dispute["status"] }> = ({ s }) => (
  <span className={`badge ${STATUS_TONE[s]}`}>{STATUS_LABEL[s]}</span>
);

export const RecoBadge: React.FC<{ d: Dispute }> = ({ d }) => {
  const yes = d.recommendation === "contest";
  return (
    <span className={`badge ${yes ? "acct" : "flat"}`}>
      {yes ? "Contest" : "Accept"}
      <span className="mono" style={{ opacity: 0.7 }}>{pct(d.p_win)}</span>
    </span>
  );
};

export const Meter: React.FC<{ value: number; tone?: string }> = ({ value, tone }) => (
  <div className="meter">
    <i style={{ width: `${Math.max(2, Math.round(value * 100))}%` }} data-tone={tone} />
  </div>
);

export const Money: React.FC<{ n: number; dp?: number }> = ({ n, dp = 0 }) => (
  <span className="num">{inr(n, dp)}</span>
);

export const Notice: React.FC<{
  tone?: "info" | "warn" | "good" | "flat"; children: React.ReactNode;
}> = ({ tone = "flat", children }) => (
  <div className={`notice ${tone}`}>
    <Icon d={tone === "warn" ? P.alert : tone === "good" ? P.check
            : tone === "info" ? P.info : P.help} />
    <div>{children}</div>
  </div>
);

/* --------------------------------------------------------------------------
   Loading
   --------------------------------------------------------------------------
   Content that appears without a placeholder makes the page jump, which reads
   as "choppy". A skeleton of roughly the right size holds the space so nothing
   reflows when the data lands.
   -------------------------------------------------------------------------- */

export const Skeleton: React.FC<{
  w?: string | number; h?: number; style?: React.CSSProperties;
}> = ({ w = "100%", h = 12, style }) => (
  <span className="skel" aria-hidden="true"
        style={{ width: w, height: h, ...style }} />
);

/** Placeholder rows sized to the real table, so the layout does not shift. */
export const TableSkeleton: React.FC<{ cols: number; rows?: number }> = ({
  cols, rows = 6,
}) => (
  <tbody aria-hidden="true">
    {Array.from({ length: rows }).map((_, r) => (
      <tr key={r}>
        {Array.from({ length: cols }).map((__, c) => (
          <td key={c}><Skeleton w={c === 0 ? 74 : c === 3 ? "80%" : "60%"} /></td>
        ))}
      </tr>
    ))}
  </tbody>
);

/* --------------------------------------------------------------------------
   Empty states
   -------------------------------------------------------------------------- */

export const Empty: React.FC<{
  title: string; body: string; action?: React.ReactNode; icon?: string;
}> = ({ title, body, action, icon = P.inbox }) => (
  <div className="empty">
    <span className="empty-ico"><Icon d={icon} size={22} /></span>
    <h2 className="h2">{title}</h2>
    <p className="sub">{body}</p>
    {action && <div style={{ marginTop: 14 }}>{action}</div>}
  </div>
);

/* --------------------------------------------------------------------------
   Sortable table header
   --------------------------------------------------------------------------
   A table showing a sorted order with no indication of what it is sorted by,
   and no way to change it from the header, makes people hunt for a dropdown.
   -------------------------------------------------------------------------- */

export type SortDir = "asc" | "desc";

export const SortHeader: React.FC<{
  label: string;
  col: string;
  active: string;
  dir: SortDir;
  onSort: (col: string) => void;
  align?: "left" | "right";
  width?: number;
}> = ({ label, col, active, dir, onSort, align = "left", width }) => {
  const on = active === col;
  return (
    <th className={align === "right" ? "right" : undefined} style={{ width }}
        aria-sort={on ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="th-sort" data-on={on ? "1" : "0"}
              data-align={align} onClick={() => onSort(col)}>
        {label}
        <span className="th-ico">
          {on && <Icon d={dir === "asc" ? P.up : P.down} size={11} />}
        </span>
      </button>
    </th>
  );
};

/** Decision → Evidence → Verification → Submission, driven by real state. */
export const FlowStrip: React.FC<{ status: Dispute["status"]; blocked: boolean }> = ({
  status, blocked,
}) => {
  const decided = status !== "open";
  const settled = status === "won" || status === "lost";
  const steps: [string, string][] = [
    ["Decision", decided ? "done" : "now"],
    ["Evidence", decided ? "done" : "idle"],
    ["Verification", !decided ? "idle" : blocked ? "hold" : "done"],
    ["Submission", settled ? "done" : decided && !blocked ? "now" : "idle"],
  ];
  return (
    <div className="flow">
      {steps.map(([label, s], i) => (
        <React.Fragment key={label}>
          {i > 0 && <span className="arr">›</span>}
          <span className="step" data-s={s}>
            <Icon d={s === "done" ? P.check : s === "hold" ? P.alert : P.clock} size={11} />
            {label}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
};