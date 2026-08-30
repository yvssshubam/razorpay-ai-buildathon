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
  label: string; value: string; detail?: string; tone?: string;
}> = ({ label, value, detail, tone }) => (
  <div className="card stat">
    <div className="k">{label}</div>
    <div className="v" style={tone ? { color: `var(--${tone})` } : undefined}>{value}</div>
    {detail && <div className="d">{detail}</div>}
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
    <Icon d={tone === "warn" ? P.alert : tone === "good" ? P.check : P.help} />
    <div>{children}</div>
  </div>
);

export const Empty: React.FC<{ title: string; body: string }> = ({ title, body }) => (
  <div className="empty">
    <h2 className="h2">{title}</h2>
    <p className="sub">{body}</p>
  </div>
);

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
