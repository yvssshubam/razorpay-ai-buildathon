import { useEffect, useState } from "react";
import { DisputeDetail, api, inr, pct, shortDate, titleise } from "../api";
import { Card, CardHead, FlowStrip, Icon, Meter, Notice, P, StatusBadge } from "../components/ui";

export default function Detail({
  id, onBack, onChanged, onOpen,
}: {
  id: string; onBack: () => void;
  onChanged: () => Promise<void> | void; onOpen: (id: string) => void;
}) {
  const [d, setD] = useState<DisputeDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = () => api.dispute(id).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); void load(); }, [id]);

  if (err) return <Notice tone="warn">{err}</Notice>;
  if (!d) return <p className="muted">Loading dispute…</p>;

  const act = async (action: "contest" | "accept") => {
    setBusy(true); setErr(null);
    try {
      await api.decide(id, action, "merchant");
      await load();
      await onChanged();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const contest = d.recommendation === "contest";
  const decided = d.status !== "open";
  const missing = d.evidence.filter((e) => e.state !== "verified");
  const c = d.customer_history;
  const lifetime = c.in_queue + c.prior_before_queue;

  return (
    <>
      <button className="btn sm" onClick={onBack} style={{ marginBottom: 12 }}>
        <Icon d={P.left} size={12} /> Back to queue
      </button>

      <div className="page-head">
        <div className="grow">
          <h1 className="h1">{d.description || titleise(d.category)}</h1>
          <p className="sub">
            <span className="mono">{d.id}</span> · filed {shortDate(d.filed_on)} ·{" "}
            <span className="mono">{d.network} {d.reason_code}</span>
          </p>
        </div>
        <div className="right">
          <StatusBadge s={d.status} />
          <div className="tiny faint" style={{ marginTop: 4 }}>
            {d.decided_by ? `Decided by ${d.decided_by}` : "Awaiting your decision"}
          </div>
        </div>
      </div>

      {d.provenance.code_provenance === "network_docs" && (
        <div style={{ marginBottom: 12 }}>
          <Notice tone="warn">
            This reason code's evidence list is compiled from card-network documentation, not
            confirmed against Razorpay's own mapping. Completeness here is provisional.
          </Notice>
        </div>
      )}

      <div className="split">
        <div className="stack">
          {/* ---- recommendation ---- */}
          <div className="reco" data-accept={contest ? "0" : "1"}>
            <div className="reco-top">
              <Icon d={P.bolt} size={12} />
              Chargeback Agent
              <span className="spacer" />
              <span style={{ fontWeight: 400, opacity: 0.8 }}>
                calibrated model · EV policy
              </span>
            </div>
            <div className="card-body">
              <div className="verdict">{contest ? "CONTEST" : "DO NOT CONTEST"}</div>

              <div className="grid g3" style={{ marginTop: 14 }}>
                <div>
                  <div className="eyebrow">Win probability</div>
                  <div className="num" style={{ fontSize: 18 }}>{pct(d.p_win)}</div>
                  <Meter value={d.p_win} tone={d.p_win > 0.6 ? "good" : d.p_win < 0.35 ? "warn" : undefined} />
                </div>
                <div>
                  <div className="eyebrow">Amount at stake</div>
                  <div className="num" style={{ fontSize: 18 }}>{inr(d.amount)}</div>
                </div>
                <div>
                  <div className="eyebrow">Expected value</div>
                  <div className="num" style={{
                    fontSize: 18, color: d.ev.positive ? "var(--good)" : "var(--bad)",
                  }}>
                    {d.ev.value > 0 ? "+" : ""}{inr(d.ev.value)}
                  </div>
                </div>
              </div>

              {/* The arithmetic, shown rather than asserted. */}
              <div className="ev-line" style={{ marginTop: 14 }}>
                <span>{pct(d.p_win)}</span><span className="op">×</span>
                <span>{inr(d.amount)}</span><span className="op">×</span>
                <span>{d.ev.gross / (d.p_win * d.amount) < 1 ? "0.85" : "0.85"}</span>
                <span className="op">=</span>
                <span>{inr(d.ev.gross)}</span>
                {d.ev.resolve_rate != null && (
                  <>
                    <span className="op">×</span>
                    <span>{d.ev.resolve_rate} resolved</span>
                  </>
                )}
                <span className="op">−</span>
                <span>{inr(d.ev.cost)} {d.ev.cost_label}</span>
                <span className="op">=</span>
                <span className="res" style={{ color: d.ev.positive ? "var(--good)" : "var(--bad)" }}>
                  {d.ev.value > 0 ? "+" : ""}{inr(d.ev.value)}
                </span>
              </div>

              <ul className="why" style={{ marginTop: 12 }}>
                <li>
                  {d.claims_supported} of {d.claims_total} claims trace to an artifact that exists
                  and predates the dispute.
                </li>
                <li>
                  Packet is {pct(d.completeness)} complete against the {d.evidence.length} documents
                  the rulebook lists for {d.reason_code}
                  {missing.length > 0 && `, short ${missing.map((m) => titleise(m.kind)).join(", ")}`}.
                </li>
                <li>
                  {d.blocked
                    ? `Because the packet is short, this case is priced at ${inr(d.ev.cost)} human review and pays out on the ${d.ev.resolve_rate} a person can resolve, not at the contest fee.`
                    : `Priced at the ${inr(d.ev.cost)} contest fee, since the packet clears the rulebook and can be submitted directly.`}
                </li>
                {!d.address_match && <li>Billing address did not match on authorisation.</li>}
                {d.new_device && <li>Checkout came from a device not seen on this customer before.</li>}
                {d.prior_disputes > 0 && (
                  <li>This customer has filed {d.prior_disputes} dispute
                    {d.prior_disputes > 1 ? "s" : ""} before this one.</li>
                )}
              </ul>

              {err && <div style={{ marginTop: 12 }}><Notice tone="warn">{err}</Notice></div>}

              {!decided ? (
                <>
                  <div className="inline" style={{ marginTop: 16 }}>
                    <button className="btn pri lg" style={{ flex: 1 }} disabled={busy}
                            onClick={() => void act("contest")}>
                      Contest chargeback · {inr(d.ev.cost)}
                    </button>
                    <button className="btn lg" style={{ flex: 1 }} disabled={busy}
                            onClick={() => void act("accept")}>
                      Do not contest
                    </button>
                  </div>
                  <p className="tiny faint" style={{ textAlign: "center", marginTop: 8, marginBottom: 0 }}>
                    Nothing is submitted until you choose. The fee is drawn from your contest wallet.
                  </p>
                </>
              ) : (
                <div style={{ marginTop: 16 }}>
                  <FlowStrip status={d.status} blocked={d.blocked} />
                </div>
              )}
            </div>
          </div>

          {/* ---- evidence ---- */}
          <Card>
            <CardHead
              title="Evidence"
              sub={`Required by ${d.network} ${d.reason_code} per rulebook v${d.provenance.rulebook_version}`}
              right={
                <span className={`badge ${d.blocked ? "warn" : "good"}`}>
                  {d.evidence.length - missing.length}/{d.evidence.length} verified
                </span>
              }
            />
            <div>
              {d.evidence.map((e) => (
                <div className="row" key={e.kind}>
                  <div className={`icon-sq ${e.state === "verified" ? "good" : e.state === "stale" ? "warn" : "bad"}`}>
                    <Icon d={e.state === "verified" ? P.check : e.state === "stale" ? P.clock : P.x} size={13} />
                  </div>
                  <div className="grow">
                    <div className="t">{titleise(e.kind)}</div>
                    <div className="s mono tiny">
                      {e.api_field}
                      {e.created_on && ` · dated ${shortDate(e.created_on)}`}
                      {e.artifact_id && ` · ${e.artifact_id}`}
                    </div>
                  </div>
                  <span className={`badge ${e.state === "verified" ? "good" : e.state === "stale" ? "warn" : "bad"}`}>
                    {e.state === "verified" ? "Verified"
                      : e.state === "stale" ? "Dated after dispute" : "Not on file"}
                  </span>
                </div>
              ))}
            </div>
            <div className="card-foot">
              A document counts only if it exists and predates the dispute. Anything created
              afterwards cannot evidence what happened before it.
            </div>
          </Card>

          {/* ---- verification gate ---- */}
          <Card>
            <CardHead title="Submission safety check" />
            <div className="card-body">
              <Notice tone={d.blocked ? "warn" : "good"}>
                {d.blocked
                  ? "Part of the evidence this reason code requires is missing or stale. If you contest, the packet stops at the verification gate and a person reviews it. It is not submitted automatically."
                  : "Every claim in this packet is backed by a retrieved artifact. The packet is verified again before Razorpay submits the representment."}
              </Notice>
              <div style={{ marginTop: 12 }}>
                <FlowStrip status={d.status} blocked={d.blocked} />
              </div>
            </div>
          </Card>
        </div>

        {/* ---- right rail ---- */}
        <div className="stack">
          <Card>
            <CardHead title="Transaction" />
            <div className="card-body" style={{ paddingTop: 4, paddingBottom: 6 }}>
              <dl style={{ margin: 0 }}>
                <div className="kv"><dt>Dispute ID</dt><dd className="mono">{d.id}</dd></div>
                <div className="kv"><dt>Reason code</dt><dd className="mono">{d.network} {d.reason_code}</dd></div>
                <div className="kv"><dt>Category</dt><dd>{titleise(d.category)}</dd></div>
                <div className="kv"><dt>Amount</dt><dd className="num">{inr(d.amount, 2)}</dd></div>
                <div className="kv"><dt>Filed</dt><dd className="num">{shortDate(d.filed_on)}</dd></div>
                <div className="kv"><dt>Address match</dt>
                  <dd><span className={`badge ${d.address_match ? "good" : "bad"}`}>
                    {d.address_match ? "Match" : "No match"}</span></dd></div>
                <div className="kv"><dt>Device</dt>
                  <dd><span className={`badge ${d.new_device ? "warn" : "flat"}`}>
                    {d.new_device ? "New device" : "Known device"}</span></dd></div>
              </dl>
            </div>
          </Card>

          <Card>
            <CardHead
              title="Customer history"
              sub={`${d.customer.name} · ${d.customer.email}`}
              right={lifetime > 1
                ? <span className="badge warn"><Icon d={P.repeat} size={10} />Repeat filer</span>
                : <span className="badge flat">First dispute</span>}
            />
            <div className="card-body" style={{ paddingBottom: 8 }}>
              <div className="grid g3">
                <div>
                  <div className="num" style={{ fontSize: 18, color: lifetime > 1 ? "var(--warn)" : undefined }}>
                    {lifetime}
                  </div>
                  <div className="tiny muted">Lifetime disputes</div>
                </div>
                <div>
                  <div className="num" style={{ fontSize: 18 }}>{c.in_queue}</div>
                  <div className="tiny muted">In this batch</div>
                </div>
                <div>
                  <div className="num" style={{ fontSize: 18 }}>{inr(c.total_amount)}</div>
                  <div className="tiny muted">Total disputed</div>
                </div>
              </div>
            </div>
            <div>
              {c.items.map((it) => (
                <div className="row" key={it.id}
                     data-click={it.is_current ? "0" : "1"}
                     onClick={() => !it.is_current && onOpen(it.id)}
                     style={{ cursor: it.is_current ? "default" : "pointer" }}>
                  <div className="grow">
                    <div className="t mono">{it.id}{it.is_current && " · this one"}</div>
                    <div className="s mono tiny">{it.reason_code}</div>
                  </div>
                  <span className="num tiny">{inr(it.amount)}</span>
                  <StatusBadge s={it.status} />
                </div>
              ))}
              {c.prior_before_queue > 0 && (
                <div className="row">
                  <div className="grow s">
                    {c.prior_before_queue} earlier dispute{c.prior_before_queue > 1 ? "s" : ""} before
                    this batch
                  </div>
                </div>
              )}
            </div>
            <div className="card-foot">
              Customer identity is derived at serve time from each record's prior-dispute count.
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
