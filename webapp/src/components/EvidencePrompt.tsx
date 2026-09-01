import { useEffect, useState } from "react";
import { EvidenceGaps, api, inr, titleise } from "../api";
import { Icon, P } from "./ui";

/* "Strengthen this packet" — the missing-evidence prompt.
 *
 * WHY THIS PANEL EXISTS. 40% of the queue blocks at zero model error, on
 * evidence timestamped after the dispute or that never existed. No improvement
 * in drafting removes that share of the human queue — but the merchant has the
 * record. Across the holdout, 172 of those 316 cases need exactly ONE
 * document, and the verdict flips on that single document in 122 of them.
 *
 * WHY IT DOES NOT NAG. The recommendation is already correct without the extra
 * evidence; supplying it changes the inputs, not the policy. There is no
 * badge, no blocking modal, no red state. A merchant who ignores this panel
 * loses nothing they were entitled to.
 *
 * WHAT IT PROMISES, AND WHAT IT DOES NOT. It says the packet stops going to a
 * human and states the change in recovery. It does NOT claim to raise the win
 * probability, because with the current model it does not: packet_blocked and
 * frac_stale have zero permutation sensitivity, and the model's completeness
 * feature counts present_evidence regardless of staleness. All of the movement
 * is through the packet path. Claiming otherwise would be an overstatement a
 * reviewer could disprove by dragging one slider.
 */

type Props = { disputeId: string; onChanged: () => void };

export default function EvidencePrompt({ disputeId, onChanged }: Props) {
  const [gaps, setGaps] = useState<EvidenceGaps | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    setGaps(null); setValues({}); setErr(null); setDone(null);
    api.evidenceGaps(disputeId).then(setGaps).catch((e) => setErr((e as Error).message));
  }, [disputeId]);

  if (err) return null;                       // a missing panel beats a broken one
  if (!gaps || gaps.complete) return null;    // nothing to ask for

  const filled = Object.entries(values)
    .filter(([, v]) => v.trim())
    .map(([kind, value]) => ({ kind, value: value.trim() }));

  const submit = async () => {
    if (!filled.length) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.evidenceSubmit(disputeId, filled);
      setDone(
        r.delta.flipped
          ? `Recommendation is now ${r.after.recommendation === "contest" ? "Contest" : "Do not contest"}.`
          : `Recovery updated to ${inr(Math.round(r.after.ev.gross))}.`
      );
      setValues({});
      const g = await api.evidenceGaps(disputeId);
      setGaps(g);
      onChanged();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const single = gaps.items.length === 1;

  return (
    <section className="card" style={{ padding: 20, marginTop: 18 }}>
      <div className="inline" style={{ gap: 8, marginBottom: 4 }}>
        <Icon d={P.doc} />
        <b style={{ fontSize: 15 }}>
          {single ? "One record would strengthen this" : "Records that would strengthen this"}
        </b>
      </div>

      <p className="tiny faint" style={{ marginTop: 2, marginBottom: 14 }}>
        {single
          ? "We could not find this document. If you have it, add the reference and this packet stops needing a person to finish it."
          : "We could not find these documents. Adding any of them reduces what a person has to finish by hand."}
        {" "}Optional — your recommendation is already calculated without them.
      </p>

      <div style={{ display: "grid", gap: 10 }}>
        {gaps.items.map((it) => (
          <div key={it.kind} style={{ display: "grid", gap: 4 }}>
            <label className="tiny" htmlFor={`ev-${it.kind}`}
                   style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span>
                {titleise(it.kind)}
                {it.state === "stale" && (
                  <span className="faint"> · on file, but dated after the dispute</span>
                )}
              </span>
              {it.ev > 0 && (
                <span className="faint" style={{ fontVariantNumeric: "tabular-nums" }}>
                  worth {inr(Math.round(it.ev))}
                  {it.flipped && " · would change the recommendation"}
                </span>
              )}
            </label>
            <input
              id={`ev-${it.kind}`}
              className="field"
              placeholder="Reference, tracking number or document ID"
              value={values[it.kind] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [it.kind]: e.target.value }))}
            />
          </div>
        ))}
      </div>

      <div className="inline" style={{ gap: 10, marginTop: 14, flexWrap: "wrap" }}>
        <button className="btn pri" disabled={!filled.length || busy} onClick={submit}>
          {busy ? "Checking…" : filled.length > 1 ? `Add ${filled.length} records` : "Add record"}
        </button>
        {done && (
          <span className="tiny" style={{ color: "var(--good)" }}>
            <Icon d={P.check} size={12} /> {done}
          </span>
        )}
      </div>

      <p className="tiny faint" style={{ marginTop: 12 }}>
        What you enter is checked against the packet before anything is submitted.
        A reference that does not match the record is removed and the packet goes
        to a person, exactly as it would have without it.
      </p>
    </section>
  );
}