"""Stage 3: grounded packet drafting.

The model receives ONLY the artifacts that Stage 2's deterministic lookup
retrieved for this reason code. It never sees the full order record, so it
cannot cite something that was never retrieved -- one whole class of
fabrication is removed by construction rather than by instruction.

Output is a structured claims list, not prose. Every claim carries the ID of
the artifact that supports it and the evidence kind it asserts. Free prose
cannot be verified claim-by-claim; this shape can.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm as _llm

SYSTEM = """You draft chargeback representment claims for an Indian payment aggregator.

Rules, without exception:
- Use ONLY the artifacts given to you. Never invent an artifact ID.
- One claim per artifact. Do not combine or split.
- artifact_id MUST be copied exactly from the artifacts object.
- asserts_kind MUST be that artifact's own kind. Never upgrade a kind, for
  example never describe a photo_delivery_confirmation as a signed one.
- Every claim MUST also name ONE field of that artifact it relies on
  (asserts_field, one of: value, created_day, api_field, kind) and copy that
  field's exact content into asserts_value. Copy it; do not restate, reformat
  or summarise it. A claim whose asserts_value does not match the artifact is
  discarded and may block the whole packet.
- The prose in "text" must not assert any date, amount or identifier that is
  not the field you copied.
- If an artifact does not support a claim, omit it rather than stretching it.

Return JSON only, no prose, no markdown fences:
{"claims":[{"text":"...","artifact_id":"...","asserts_kind":"...",
            "asserts_field":"...","asserts_value":"..."}]}"""


def build_context(dispute, retrieved):
    """retrieved: {artifact_id: artifact}. Stage 2's output, nothing more."""
    return json.dumps({
        "reason_code": dispute.get("reason_code"),
        "network": dispute.get("network"),
        "amount": dispute.get("amount"),
        "dispute_day": dispute.get("dispute_day"),
        "required_evidence": dispute.get("required_evidence"),
        "artifacts": retrieved,
    }, ensure_ascii=False)


def retrieve(dispute):
    required = set(dispute.get("required_evidence") or [])
    arts = dispute.get("artifacts") or {}
    return {aid: a for aid, a in arts.items()
            if a.get("present") and a.get("kind") in required}


def draft_claims(dispute, provider=None, seed=0):
    provider = provider or _llm.get_provider()
    retrieved = retrieve(dispute)
    if not retrieved:
        return [], "nothing retrieved"

    try:
        raw = provider.draft(SYSTEM, build_context(dispute, retrieved), seed=seed)
    except _llm.LLMError as e:
        return [], f"provider: {e}"

    return parse_claims(raw)


def parse_claims(raw):
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [], "unparseable JSON"

    claims = parsed.get("claims") if isinstance(parsed, dict) else parsed
    if not isinstance(claims, list):
        return [], "no claims list"

    clean = []
    for c in claims:
        if isinstance(c, dict) and c.get("artifact_id"):
            row = {
                "text": str(c.get("text", ""))[:400],
                "artifact_id": str(c["artifact_id"]),
                "asserts_kind": str(c.get("asserts_kind", "")),
            }
            if c.get("asserts_field") and c.get("asserts_value") is not None:
                row["asserts_field"] = str(c["asserts_field"])
                row["asserts_value"] = str(c["asserts_value"])
            clean.append(row)
    return clean, None


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "holdout.jsonl")
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    prov = _llm.get_provider()
    print(f"provider: {type(prov).__name__}")
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= n:
                break
            d = json.loads(line)
            claims, err = draft_claims(d, prov, seed=i)
            print(f"\n-- {d.get('dispute_id')}  {d.get('reason_code')}  "
                  f"retrieved={len(retrieve(d))}  claims={len(claims)}"
                  + (f"  ERROR {err}" if err else ""))
            for c in claims:
                print(f"   [{c['artifact_id']}] {c['asserts_kind']}: {c['text'][:70]}")