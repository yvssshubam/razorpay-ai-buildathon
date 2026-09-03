import { useState } from "react";
import { api, type Extraction } from "../api";

/* Paste a document, watch the extractor recover a reference or decline to.
   The declining is the point: a digitless capture used to be folded into a
   plausible number, which is the one failure the verifier cannot catch. */

const KINDS = [
  "tracking_information",
  "delivery_confirmation",
  "service_completion",
  "refund_record",
  "customer_acknowledgement",
];

export default function DocumentExtractor() {
  const [text, setText] = useState("");
  const [kind, setKind] = useState(KINDS[0]);
  const [router, setRouter] = useState<"heuristic" | "model">("heuristic");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Extraction | null>(null);

  async function run() {
    setBusy(true); setErr(null); setRes(null);
    try {
      setRes(await api.extract(text, kind, router));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16 }}>
      <h3 style={{ margin: "0 0 4px" }}>Document extraction</h3>
      <p style={{ margin: "0 0 12px", fontSize: 13, color: "#666" }}>
        Paste a courier email, CSV export, receipt, support thread or internal
        note. The layer returns a candidate artifact or nothing. Nothing is the
        safe answer: the merchant is asked to type the reference instead.
      </p>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={8}
        placeholder="Ref on file: TRK8724 ..."
        style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
      />

      <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 8 }}>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>

        <label style={{ fontSize: 13 }}>
          <input
            type="checkbox"
            checked={router === "model"}
            onChange={(e) => setRouter(e.target.checked ? "model" : "heuristic")}
          />{" "}
          model router
        </label>

        <button onClick={run} disabled={busy || !text.trim()}>
          {busy ? "Extracting..." : "Extract"}
        </button>
      </div>

      {err && (
        <p style={{ color: "#b00", fontSize: 13, marginTop: 12 }}>{err}</p>
      )}

      {res && (
        <div style={{ marginTop: 12, fontSize: 13 }}>
          {res.extracted ? (
            <p style={{ margin: "0 0 8px" }}>
              Recovered <strong>{res.value}</strong>
            </p>
          ) : (
            <p style={{ margin: "0 0 8px", color: "#8a6d00" }}>
              <strong>No value found.</strong> Safe outcome: the merchant is
              asked to type the reference rather than the system inventing one.
            </p>
          )}
          <dl style={{ margin: 0, display: "grid",
                       gridTemplateColumns: "auto 1fr", gap: "2px 12px" }}>
            <dt>tool</dt><dd>{res.tool}</dd>
            <dt>router</dt><dd>{res.router}</dd>
            <dt>raw capture</dt><dd>{res.raw_extraction ?? "none"}</dd>
            <dt>canonicalised</dt><dd>{res.reference ?? "none"}</dd>
            <dt>trust</dt><dd>{res.source}, treated as {res.provenance}</dd>
          </dl>
          <p style={{ marginTop: 8, color: "#666" }}>
            Extraction being confident is not extraction being right. Whatever
            comes out of this layer still passes the same five verifier checks
            as evidence the merchant typed in.
          </p>
        </div>
      )}
    </section>
  );
}