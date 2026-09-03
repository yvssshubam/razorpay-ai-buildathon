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
 * WHAT IT PROMISES. That the packet stops needing a person, and the change in
 * recovery. It deliberately does not lead with the win probability, even
 * though for a MISSING record that moves a great deal (+0.31 mean across 269
 * disputes, up to +0.84) -- because for a STALE record it moves by exactly
 * 0.000 across all 47 of them, for the reasons in README section 4. One
 * sentence cannot be true of both, and the packet claim is true of both.
 *
 * WHAT IT MUST NOT PROMISE. That what the merchant types is verified. It is
 * not, and cannot be. The five checks compare a claim against a record; for a
 * merchant-supplied record the merchant IS the source, so a faithful claim
 * about an invented value passes every check. This panel previously carried a
 * line saying otherwise and it was false. Provenance marking, not
 * verification, is the control -- see the _INTEGRITY note in
 * serve/evidence.py.
 *
 * PASTING A DOCUMENT IS THE SAME ROAD, NOT A SHORTER ONE. Merchant evidence
 * arrives as courier emails, exports and support threads, so the extractor
 * reads a reference out of pasted text and fills the field with it. What lands
 * in that field is a proposal the merchant confirms, not a value the system
 * commits on its own, and it carries the same provenance as one they typed.
 * The extractor returning NOTHING is the outcome worth watching: a capture
 * with no digits in it used to be folded into a plausible number, which is the
 * one failure the verifier cannot catch, because a faithful claim about a
 * wrong record passes every check.
 */

type Props = { disputeId: string; onChanged: () => void };

type Pasted = {
  text: string;
  busy: boolean;
  err: string | null;
  note: string | null;
};

const EMPTY_PASTE: Pasted = { text: "", busy: false, err: null, note: null };

export default function EvidencePrompt({ disputeId, onChanged }: Props) {
  const [gaps, setGaps] = useState<EvidenceGaps | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [paste, setPaste] = useState<Record<string, Pasted>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    setGaps(null); setValues({}); setPaste({}); setErr(null); setDone(null);
    api.evidenceGaps(disputeId).then(setGaps).catch((e) => setErr((e as Error).message));
  }, [disputeId]);

  if (err) return null;                       // a missing panel beats a broken one
  if (!gaps || gaps.complete) return null;    // nothing to ask for

  const filled = Object.entries(values)
    .filter(([, v]) => v.trim())
    .map(([kind, value]) => ({ kind, value: value.trim() }));

  const setPasteFor = (kind: string, patch: Partial<Pasted>) =>
    setPaste((p) => ({ ...p, [kind]: { ...(p[kind] ?? EMPTY_PASTE), ...patch } }));

  const extract = async (kind: string) => {
    const text = (paste[kind]?.text ?? "").trim();
    if (!text) return;
    setPasteFor(kind, { busy: true, err: null, note: null });
    try {
      const r = await api.extract(text, kind);
      if (r.extracted && r.reference) {
        setValues((v) => ({ ...v, [kind]: r.reference as string }));
        setPasteFor(kind, {
          busy: false,
          note: `Read ${r.reference} from the document · ${r.tool}. Check it before adding.`,
        });
      } else {
        // Clear any value a previous extraction left here. A stale reference
        // sitting under "nothing readable" reads as though the system produced
        // it from the document just pasted.
        setValues((v) => ({ ...v, [kind]: "" }));
        setPasteFor(kind, {
          busy: false,
          note: "Nothing readable in that document. Type the reference instead — "
              + "the extractor declining is safer than it guessing.",
        });
      }
    } catch (e) {
      setPasteFor(kind, { busy: false, err: (e as Error).message });
    }
  };

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
      setPaste({});
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
        {gaps.items.map((it) => {
          const p = paste[it.kind] ?? EMPTY_PASTE;
          const open = p.text !== "" || p.note !== null || p.err !== null;
          return (
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

              <textarea
                className="field"
                rows={open ? 5 : 2}
                placeholder="…or paste the courier email, export, receipt or support thread and let the agent read the reference out of it"
                value={p.text}
                onChange={(e) => setPasteFor(it.kind, { text: e.target.value, note: null, err: null })}
                style={{ fontFamily: "ui-monospace, monospace", fontSize: 12 }}
              />

              <div className="inline" style={{ gap: 10, flexWrap: "wrap" }}>
                <button
                  className="btn"
                  disabled={!p.text.trim() || p.busy}
                  onClick={() => extract(it.kind)}
                >
                  {p.busy ? "Reading…" : "Read reference from document"}
                </button>
                {p.note && <span className="tiny faint">{p.note}</span>}
                {p.err && <span className="tiny" style={{ color: "var(--bad)" }}>{p.err}</span>}
              </div>
            </div>
          );
        })}
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
        Records you add are marked as supplied by you, whether typed or read out
        of a document you pasted, and stay marked in the audit trail and on the
        packet. Only add references you can produce if the bank asks — a
        representment is evidence submitted to a card network.
      </p>
    </section>
  );
}