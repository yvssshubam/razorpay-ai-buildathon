import { useState } from "react";
import { Packet, STRIP_REASON, api, pct, titleise } from "../api";
import { Icon, P } from "./ui";

/* Stages 3 and 4, run live.
 *
 * Everything else in this dashboard is deterministic: the classifier, the
 * rulebook lookup, the EV rule. This is the one panel where a language model
 * writes something and a separate, non-model pass decides whether any of it
 * may be submitted.
 *
 * WHY THE STRIPPED CLAIMS ARE SHOWN AND NOT HIDDEN. A filter quietly removes
 * bad claims and shows a clean packet. A gate shows what it refused and why.
 * The second is the point: a fabricated delivery date in a representment is
 * false evidence submitted to a card network, so the interesting output is not
 * the packet that passed but the claim that did not.
 *
 * WHY THERE IS A FAULT CONTROL. With a competent model the failure rate is
 * zero, which demonstrates nothing about the gate -- it means the model did
 * not test it. Injecting faults is how the gate is shown to work. It is
 * labelled as a test control rather than dressed up as a product feature,
 * because pretending a debugging affordance is a feature is its own kind of
 * dishonesty.
 */

type Props = { disputeId: string };

/* The redraft loop, exposed as a switch rather than a default.
 *
 * It is off unless asked for, because every published figure in this project
 * describes the single-draft path. Turning it on silently would mean the
 * dashboard and the evaluation were measuring different systems.
 *
 * What it demonstrates is narrow and worth stating on screen rather than in a
 * docstring nobody opens: the loop only retries a claim the verifier rejected
 * for a reason a rewrite could fix, so on a model that drafts cleanly it makes
 * no extra calls at all. Its value is a function of how bad the drafter is.
 */

const FAULTS = [
  { v: undefined, label: "As drafted" },
  { v: 0.2, label: "Inject 20% faults" },
  { v: 0.4, label: "Inject 40% faults" },
];

export default function PacketDrafter({ disputeId }: Props) {
  const [pk, setPk] = useState<Packet | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fault, setFault] = useState<number | undefined>(undefined);
  const [loop, setLoop] = useState(false);

  const run = async (f: number | undefined) => {
    setBusy(true); setErr(null); setFault(f);
    try {
      setPk(await api.packet(disputeId, f, loop));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" style={{ padding: 20, marginTop: 18 }}>
      <div className="inline" style={{ gap: 8 }}>
        <Icon d={P.bolt} />
        <b style={{ fontSize: 15 }}>Draft and verify the evidence packet</b>
      </div>

      <p className="tiny faint" style={{ marginTop: 4, marginBottom: 12 }}>
        A model writes one claim per retrieved record. Five deterministic checks
        then decide what survives: the record must exist, be the kind claimed,
        predate the dispute, and actually contain the value the claim states —
        and what is left must still cover the reason code.
      </p>

      <div className="inline" style={{ gap: 8, flexWrap: "wrap" }}>
        {FAULTS.map((f) => (
          <button key={f.label} className={f.v === undefined ? "btn pri" : "btn"}
                  disabled={busy} onClick={() => void run(f.v)}>
            {busy && fault === f.v ? "Drafting…" : f.label}
          </button>
        ))}
      </div>

      <label className="tiny" style={{ display: "flex", alignItems: "center",
                                       gap: 8, marginTop: 12, cursor: "pointer" }}>
        <input type="checkbox" checked={loop}
               onChange={(e) => setLoop(e.target.checked)} />
        <span>
          Let the drafter retry once when the verifier rejects a claim
          <span className="faint">
            {" "}· off by default, because every published figure describes the
            single-draft path
          </span>
        </span>
      </label>

      {err && <p className="tiny" style={{ color: "var(--bad)", marginTop: 10 }}>{err}</p>}

      {pk && (
        <div style={{ marginTop: 16 }}>
          <div className="tiny faint">
            {pk.provider}{pk.model ? ` · ${pk.model}` : ""} · {pk.artifacts_retrieved} records
            retrieved · {pk.claims_drafted} claims drafted
            {pk.fault_rate != null && ` · ${pct(pk.fault_rate)} faults injected`}
            {!pk.field_check && " · field check disabled"}
          </div>

          <div className={`notice ${pk.blocked ? "warn" : ""}`} style={{ marginTop: 12 }}>
            <Icon d={pk.blocked ? P.alert : P.check} />
            <div>
              <b>
                {pk.blocked
                  ? "Blocked — this packet cannot be submitted"
                  : "Verified — this packet may be submitted"}
              </b>
              <div className="tiny" style={{ marginTop: 4 }}>
                {pk.kept.length} of {pk.claims_drafted} claims survived.
                {" "}Hallucination rate {pk.hallucination_rate.toFixed(3)}.
                {pk.blocked && pk.missing_evidence.length > 0 && (
                  <> Still missing: {pk.missing_evidence.map(titleise).join(", ")}. Routed to a person.</>
                )}
              </div>
            </div>
          </div>

          {pk.redraft && pk.trace && (
            <div style={{ marginTop: 14 }}>
              <div className="eyebrow">
                Retry loop
                {pk.recovered
                  ? " · recovered a packet the first draft lost"
                  : pk.attempts > 1
                    ? " · retried and did not recover"
                    : " · declined to retry"}
              </div>
              <ul className="why" style={{ marginTop: 6 }}>
                {pk.trace.map((t, i) => (
                  <li key={i}>
                    <b>Attempt {t.attempt}</b>{" "}
                    {t.skipped ? (
                      <span className="faint">{t.skipped}</span>
                    ) : (
                      <>
                        {t.drafted} drafted, {t.kept} kept, {t.stripped} stripped
                        {t.blocked ? ", blocked" : ", submittable"}
                        {t.discarded && (
                          <span className="faint"> · discarded: {t.discarded}</span>
                        )}
                      </>
                    )}
                  </li>
                ))}
              </ul>
              {pk.attempts === 1 && (
                <p className="tiny faint" style={{ marginTop: 6 }}>
                  Nothing here a rewrite could fix. A stale record cannot be made
                  younger and a missing one cannot be written, so the loop spent
                  no model call.
                </p>
              )}
            </div>
          )}

          {pk.depends_on_merchant_evidence && (
            <div className="notice warn" style={{ marginTop: 12 }}>
              <Icon d={P.alert} />
              <div>
                <b>Clears the rulebook only because of records you supplied</b>
                <div className="tiny" style={{ marginTop: 4 }}>
                  The checks confirm each claim matches its record. They cannot
                  confirm a record you provided is real — nothing can, so this is
                  stated rather than checked. {pk.merchant_artifacts} supplied
                  {pk.merchant_artifacts === 1 ? " record is" : " records are"} marked
                  in the audit trail.
                </div>
              </div>
            </div>
          )}

          {pk.stripped.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="eyebrow">Refused by the verifier</div>
              <ul className="why" style={{ marginTop: 6 }}>
                {pk.stripped.map((c, i) => (
                  <li key={i}>
                    <span className="mono tiny">{c.artifact_id}</span>
                    {" — "}{STRIP_REASON[c.reason] ?? c.reason}
                    {c.actual_value != null && c.actual_value !== "" && (
                      <span className="faint"> (record says {c.actual_value})</span>
                    )}
                    {c.actual_kind && (
                      <span className="faint"> (record is {titleise(c.actual_kind)})</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {pk.kept.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="eyebrow">Claims that survived</div>
              <ul className="why" style={{ marginTop: 6 }}>
                {pk.kept.map((c, i) => (
                  <li key={i}>
                    {c.text}
                    {c.field && (
                      <span className="faint">
                        {" "}· checked {c.field} = {c.value}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {pk.draft_error && (
            <p className="tiny faint" style={{ marginTop: 12 }}>
              The model returned nothing usable ({pk.draft_error}). An empty packet
              cannot cover the reason code, so it blocks — a drafting failure never
              becomes a submission.
            </p>
          )}
        </div>
      )}
    </section>
  );
}