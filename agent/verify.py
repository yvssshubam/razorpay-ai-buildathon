"""Stage 4: the verifier. A hard gate, not a filter.

Four checks, cheapest first. Every one is deterministic -- no model verifies
another model's output, because that just moves the trust problem.

  1. exists      the cited artifact_id is in the retrieved set
  2. kind        asserts_kind matches the artifact's actual kind
  3. temporal    the artifact predates the dispute
  4. required    after stripping, the surviving kinds still cover the rulebook

Checks 1-3 strip individual claims. Check 4 blocks the whole packet and routes
it to a human. That distinction is the point: a packet with a bad claim removed
may still be submittable; a packet that no longer meets the reason code's
documented requirement must not be.

WHY THIS IS A GATE. A fabricated delivery timestamp in a representment is not a
quality bug. It is false evidence submitted to a card network by a merchant the
aggregator is responsible for. Post-hoc filtering leaves a window where the
false claim is submittable. A gate does not.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from draft import retrieve

EXISTS, KIND, TEMPORAL = "no_such_artifact", "kind_mismatch", "stale_artifact"


def verify(dispute, claims):
    """Returns a dict: kept claims, stripped claims with reasons, blocked flag.

    hallucination_rate here counts EXISTS and KIND strips only. A stale artifact
    is a real record cited about the wrong period -- a grounding error, not a
    fabrication. Folding the two together would inflate the headline number and
    hide which failure mode the model actually has.
    """
    retrieved = retrieve(dispute)
    dispute_day = dispute.get("dispute_day", 0)

    kept, stripped = [], []
    for c in claims:
        aid = c.get("artifact_id")
        art = retrieved.get(aid)

        if art is None:
            stripped.append({**c, "reason": EXISTS})
            continue
        if c.get("asserts_kind") and c["asserts_kind"] != art.get("kind"):
            stripped.append({**c, "reason": KIND,
                             "actual_kind": art.get("kind")})
            continue
        if art.get("created_day", 0) >= dispute_day:
            stripped.append({**c, "reason": TEMPORAL})
            continue
        kept.append({**c, "verified_kind": art.get("kind")})

    required = set(dispute.get("required_evidence") or [])
    covered = {c["verified_kind"] for c in kept}
    missing = sorted(required - covered)

    n = len(claims)
    fabricated = sum(1 for s in stripped if s["reason"] in (EXISTS, KIND))

    return {
        "kept": kept,
        "stripped": stripped,
        "missing_evidence": missing,
        "blocked": bool(missing),
        "n_claims": n,
        "n_stripped": len(stripped),
        "n_fabricated": fabricated,
        "hallucination_rate": fabricated / n if n else 0.0,
        "completeness": (len(required & covered) / len(required)) if required else 1.0,
    }


if __name__ == "__main__":
    import json
    import llm as _llm
    from draft import draft_claims

    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "holdout.jsonl")
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    prov = _llm.get_provider()
    print(f"provider: {type(prov).__name__}   "
          f"fault_rate: {getattr(prov, 'fault_rate', 'n/a')}")

    tot_claims = tot_fab = tot_stale = blocked = 0
    comp_sum = 0.0
    shown = 0

    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= n:
                break
            d = json.loads(line)
            claims, err = draft_claims(d, prov, seed=i)
            if type(prov).__name__ == "GeminiProvider":
                import time; time.sleep(4.5)
            r = verify(d, claims)

            tot_claims += r["n_claims"]
            tot_fab += r["n_fabricated"]
            tot_stale += sum(1 for s in r["stripped"] if s["reason"] == TEMPORAL)
            blocked += r["blocked"]
            comp_sum += r["completeness"]

            if r["blocked"] and shown < 3:
                shown += 1
                print(f"\nBLOCKED  {d.get('dispute_id')}  {d.get('reason_code')}")
                print(f"  missing: {', '.join(r['missing_evidence'])}")
                for s in r["stripped"]:
                    extra = f" (actual {s['actual_kind']})" if "actual_kind" in s else ""
                    print(f"  stripped [{s['artifact_id']}] {s['reason']}{extra}")
                print("  -> human queue")

    print(f"\n-- {n} disputes, provider {type(prov).__name__} --")
    print(f"claims              {tot_claims}")
    print(f"fabricated          {tot_fab}  ({tot_fab / max(tot_claims,1):.3f})")
    print(f"stale               {tot_stale}")
    print(f"packets blocked     {blocked}  ({blocked / n:.3f})")
    print(f"mean completeness   {comp_sum / n:.3f}")