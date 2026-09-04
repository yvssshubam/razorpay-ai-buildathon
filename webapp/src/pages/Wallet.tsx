import { useState } from "react";
import { Health, Policy, Preview, Wallet, api, inr, pct } from "../api";
import { Card, CardHead, Icon, Notice, P, Stat } from "../components/ui";

export default function WalletPage({
  wallet, policy, preview, health, onChanged,
}: {
  wallet: Wallet | null; policy: Policy | null; preview: Preview | null;
  health: Health | null; onChanged: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (!wallet || !policy) return <p className="muted">Loading wallet…</p>;

  const run = async (fn: () => Promise<unknown>, note?: string) => {
    setBusy(true); setErr(null); setMsg(null);
    try { await fn(); await onChanged(); if (note) setMsg(note); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  const patch = (p: Partial<Policy>) => run(() => api.setPolicy(p));
  const delegated = policy.mode === "delegated";
  const capLeft = policy.daily_spend_cap - wallet.spent_today;

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1 className="h1">Contest wallet</h1>
          <p className="sub">
            Contesting costs money. This is the budget it comes out of, and the rules that
            govern who may spend it.
          </p>
        </div>
        <button className="btn" disabled={busy} onClick={() => void run(() => api.topup(10000), "Added ₹10,000.")}>
          <Icon d={P.plus} size={12} /> Add ₹10,000
        </button>
      </div>

      {msg && <div style={{ marginBottom: 12 }}><Notice tone="good">{msg}</Notice></div>}
      {err && <div style={{ marginBottom: 12 }}><Notice tone="warn">{err}</Notice></div>}

      <div className="grid g5">
        <Stat label="Balance" value={inr(wallet.balance)} />
        <Stat label="Spent contesting" value={inr(wallet.spent)} detail="fees and reviews" />
        <Stat label="Recovered" value={inr(wallet.recovered)} detail="settled representments" />
        <Stat label="Net" value={`${wallet.net >= 0 ? "+" : ""}${inr(wallet.net)}`}
              tone={wallet.net >= 0 ? "good" : "bad"} detail="recovered minus spent" />
        <Stat label="Spent today" value={inr(wallet.spent_today)}
              detail={`${inr(Math.max(capLeft, 0))} left under cap`}
              tone={capLeft <= 0 ? "warn" : undefined} />
      </div>

      <div className="split" style={{ marginTop: 12 }}>
        <div className="stack">
          {/* ---- the two modes ---- */}
          <Card>
            <CardHead
              title="Who decides"
              sub="Both modes use the same policy. They differ only in who presses the button."
            />
            <div className="card-body">
              <div className="grid g2">
                <button
                  onClick={() => patch({ mode: "manual" })}
                  className="card"
                  style={{
                    textAlign: "left", padding: 13,
                    borderColor: !delegated ? "var(--accent)" : "var(--line)",
                    background: !delegated ? "var(--accent-soft)" : "var(--paper)",
                  }}
                >
                  <div className="inline">
                    <b style={{ fontSize: 13 }}>Review every dispute</b>
                    {!delegated && <span className="badge acct">Active</span>}
                  </div>
                  <p className="tiny muted" style={{ margin: "5px 0 0" }}>
                    The agent scores, retrieves evidence and recommends. Nothing is contested
                    until you click. Safest, and the slowest.
                  </p>
                </button>

                <button
                  onClick={() => patch({ mode: "delegated" })}
                  className="card"
                  style={{
                    textAlign: "left", padding: 13,
                    borderColor: delegated ? "var(--accent)" : "var(--line)",
                    background: delegated ? "var(--accent-soft)" : "var(--paper)",
                  }}
                >
                  <div className="inline">
                    <b style={{ fontSize: 13 }}>Agent acts within limits</b>
                    {delegated && <span className="badge acct">Active</span>}
                  </div>
                  <p className="tiny muted" style={{ margin: "5px 0 0" }}>
                    The agent contests on its own when a dispute clears every limit you set
                    below. Everything else still comes to you.
                  </p>
                </button>
              </div>

              <div style={{ marginTop: 14 }}>
                <Notice tone="info">
                  These limits are not the decision rule. The EV policy already decides whether
                  contesting is worth it, and the floor sweep showed it needs no confidence
                  threshold to do that well. These bound how much can go wrong before a person
                  sees it.
                </Notice>
              </div>
            </div>
          </Card>

          {/* ---- limits ---- */}
          <Card>
            <CardHead title="Delegation limits"
                      sub={delegated ? "In force now" : "Saved, but not acting while review is manual"} />
            <div className="card-body stack">
              <div>
                <div className="inline">
                  <label className="eyebrow" htmlFor="p">Only act above</label>
                  <span className="spacer" />
                  <b className="num">{pct(policy.min_p_win)}</b>
                </div>
                <input id="p" className="range" type="range" min={0.5} max={0.9} step={0.05}
                       value={policy.min_p_win}
                       onChange={(e) => patch({ min_p_win: Number(e.target.value) })} />
                <p className="tiny muted" style={{ margin: 0 }}>
                  Win probability from the calibrated model.
                </p>
              </div>

              <div>
                <div className="inline">
                  <label className="eyebrow" htmlFor="a">Only act below</label>
                  <span className="spacer" />
                  <b className="num">{inr(policy.max_amount)}</b>
                </div>
                <input id="a" className="range" type="range" min={1000} max={15000} step={500}
                       value={policy.max_amount}
                       onChange={(e) => patch({ max_amount: Number(e.target.value) })} />
                <p className="tiny muted" style={{ margin: 0 }}>
                  Large disputes always come to you, however confident the model is.
                </p>
              </div>

              <div>
                <div className="inline">
                  <label className="eyebrow" htmlFor="c">Daily spend cap</label>
                  <span className="spacer" />
                  <b className="num">{inr(policy.daily_spend_cap)}</b>
                </div>
                <input id="c" className="range" type="range" min={500} max={20000} step={500}
                       value={policy.daily_spend_cap}
                       onChange={(e) => patch({ daily_spend_cap: Number(e.target.value) })} />
                <p className="tiny muted" style={{ margin: 0 }}>
                  Hard ceiling on what the agent can spend in a day without you.
                </p>
              </div>

              <label className="inline" style={{ cursor: "pointer" }}>
                <input type="checkbox" checked={policy.require_complete_packet}
                       onChange={(e) => patch({ require_complete_packet: e.target.checked })} />
                <span>
                  <b style={{ fontSize: 12.5 }}>Never act on an incomplete packet</b>
                  <span className="tiny muted" style={{ display: "block" }}>
                    Cases the verifier blocks go to a person, never to the agent.
                  </span>
                </span>
              </label>
            </div>
          </Card>
        </div>

        <div className="stack">
          {/* ---- preview ---- */}
          <Card>
            <CardHead title="What this would do" sub="Against your open queue, right now" />
            <div className="card-body">
              {preview && (
                <>
                  <div className="grid g2">
                    <div>
                      <div className="num" style={{ fontSize: 22, color: "var(--accent)" }}>
                        {preview.auto_count}
                      </div>
                      <div className="tiny muted">handled by the agent</div>
                    </div>
                    <div>
                      <div className="num" style={{ fontSize: 22 }}>{preview.held_count}</div>
                      <div className="tiny muted">still come to you</div>
                    </div>
                  </div>
                  <dl style={{ margin: "12px 0 0" }}>
                    <div className="kv"><dt>Projected spend</dt>
                      <dd className="num">{inr(preview.projected_spend)}</dd></div>
                    <div className="kv"><dt>Projected recovery</dt>
                      <dd className="num" style={{ color: "var(--good)" }}>
                        {inr(preview.projected_recovery)}</dd></div>
                    <div className="kv"><dt><b>Projected net</b></dt>
                      <dd className="num" style={{
                        fontSize: 16,
                        color: preview.projected_net >= 0 ? "var(--good)" : "var(--bad)",
                      }}>{inr(preview.projected_net)}</dd></div>
                  </dl>

                  {preview.binding_label && (
                    <p className="tiny muted" style={{ margin: "8px 0 0" }}>
                      Limited by: <b>{preview.binding_label}</b>.{" "}
                      {preview.budget_exhausted
                        ? "Your cap sets how many run; the other limits set which ones."
                        : "Raising your cap would let more through."}
                    </p>
                  )}

                  {preview.auto.length > 0 && (
                    <div style={{ marginTop: 14 }}>
                      <div className="eyebrow" style={{ marginBottom: 6 }}>
                        Order the agent will work in
                      </div>
                      <p className="tiny muted" style={{ margin: "0 0 6px" }}>
                        Closest to its deadline first. A dispute with days in hand
                        is still contestable tomorrow; one expiring tonight is not.
                      </p>
                      <div className="scroll-y">
                        {preview.auto.slice(0, 12).map((a) => (
                          <div className="inline tiny" key={a.id}
                               style={{ padding: "4px 0", borderBottom: "1px solid var(--line-2)" }}>
                            <span className="mono">{a.id}</span>
                            <span className="spacer" />
                            <span className="muted">{inr(a.amount)}</span>
                            <span style={{ width: 10 }} />
                            <span className={a.days_left != null && a.days_left <= 1
                              ? "badge flat" : "muted"}>
                              {a.days_left != null ? `${a.days_left}d left` : "—"}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <button className="btn pri" style={{ width: "100%", marginTop: 12 }}
                          disabled={!delegated || busy || preview.auto_count === 0}
                          onClick={() => void run(() => api.runAgent(),
                            `Agent contested ${preview.auto_count} disputes.`)}>
                    {delegated
                      ? `Let the agent handle ${preview.auto_count}`
                      : "Switch to delegated mode first"}
                  </button>

                  {preview.held.length > 0 && (
                    <div style={{ marginTop: 14 }}>
                      <div className="eyebrow" style={{ marginBottom: 6 }}>Why the rest are held</div>
                      <div className="scroll-y">
                        {preview.held.slice(0, 12).map((h) => (
                          <div className="inline tiny" key={h.id}
                               style={{ padding: "4px 0", borderBottom: "1px solid var(--line-2)" }}>
                            <span className="mono">{h.id}</span>
                            <span className="spacer" />
                            <span className="muted">{h.reason}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </Card>

          {/* ---- ledger ---- */}
          <Card>
            <CardHead
              title="Ledger"
              sub="Every rupee, against the dispute that moved it"
              right={
                <button className="btn sm" disabled={busy}
                        onClick={() => void run(() => api.settle(), "Issuer verdicts applied.")}>
                  Settle verdicts
                </button>
              }
            />
            {wallet.ledger.length === 0 ? (
              <div className="empty">
                <h2 className="h2">Nothing spent yet</h2>
                <p className="sub">Contest a dispute and the fee appears here.</p>
              </div>
            ) : (
              <div className="scroll-y">
                {wallet.ledger.map((l) => (
                  <div className="row" key={l.seq}>
                    <div className={`icon-sq ${l.kind === "credit" ? "good" : l.kind === "topup" ? "" : "warn"}`}>
                      <Icon d={l.kind === "credit" ? P.check : l.kind === "topup" ? P.plus : P.doc} size={12} />
                    </div>
                    <div className="grow">
                      <div className="t">{l.note}</div>
                      <div className="s mono tiny">
                        {l.dispute_id ?? "—"} · {new Date(l.at).toLocaleTimeString("en-IN")}
                      </div>
                    </div>
                    <span className="num" style={{
                      color: l.kind === "debit" ? "var(--bad)" : "var(--good)", fontWeight: 500,
                    }}>
                      {l.kind === "debit" ? "−" : "+"}{inr(l.amount)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="card-foot">
              Fees are {inr(wallet.constants.contest_cost)} to submit and{" "}
              {inr(wallet.constants.human_review_cost)} for a blocked packet, the same constants
              the EV policy prices against.
            </div>
          </Card>

          <Card>
            <CardHead title="Settlement is simulated" />
            <div className="card-body">
              <Notice tone="warn">
                Settle verdicts resolves queued contests against the held-out ground-truth label so
                net rupee impact can be shown. That label is never read while scoring, only after a
                decision is committed. Real issuer verdicts take 15 to 30 days.
              </Notice>
              <button className="btn danger sm" style={{ marginTop: 10 }} disabled={busy}
                      onClick={() => void run(() => api.reset(), "Demo state reset.")}>
                Reset demo state
              </button>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}