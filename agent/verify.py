"""Stage 4: the verifier. A hard gate, not a filter.

Five checks, cheapest first. Every one is deterministic -- no model verifies
another model's output, because that just moves the trust problem.

  1. exists      the cited artifact_id is in the retrieved set
  2. kind        asserts_kind matches the artifact's actual kind
  3. temporal    the artifact predates the dispute
  4. value       asserts_value equals the artifact's actual field value
  5. required    after stripping, the surviving kinds still cover the rulebook

Checks 1-4 strip individual claims. Check 5 blocks the whole packet and routes
it to a human. That distinction is the point: a packet with a bad claim removed
may still be submittable; a packet that no longer meets the reason code's
documented requirement must not be.

WHY THIS IS A GATE. A fabricated delivery timestamp in a representment is not a
quality bug. It is false evidence submitted to a card network by a merchant the
aggregator is responsible for. Post-hoc filtering leaves a window where the
false claim is submittable. A gate does not.

WHY CHECK 4 EXISTS (added after audit). Checks 1-3 are all STRUCTURAL: they ask
whether the citation points at a real, correctly typed, sufficiently old
document. They say nothing about whether the claim's content matches that
document's content. So the exact failure mode quoted above -- "delivered on 3
March" citing a real, correctly typed, correctly dated delivery_confirmation
that actually records 11 March -- passed all four of the original checks. The
most dangerous fault is not a kind mismatch. It is a field-level fabrication
inside a correctly typed, correctly dated, genuinely existing document, because
every structural check passes and the packet looks perfect.

A claim that asserts no checkable field is not silently trusted. It is stripped
as UNVERIFIABLE, under the same logic: a gate cannot pass what it cannot check.
That is counted separately from fabrication -- an unverifiable claim is a
drafting-format failure, not a lie. CB_FIELD_CHECK=off restores the pre-audit
four-check behaviour, which exists only so the two can be compared.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from draft import retrieve

EXISTS, KIND, TEMPORAL = "no_such_artifact", "kind_mismatch", "stale_artifact"
VALUE, UNVERIFIABLE = "value_mismatch", "unverifiable_claim"

# Artifact fields a claim is allowed to assert against. Restricted on purpose:
# a claim may not assert against 'present' (a pipeline flag, not evidence) or
# against a field the artifact does not carry.
CHECKABLE_FIELDS = ("value", "created_day", "api_field", "kind")


def _field_check(claim, art):
    """Returns (reason, detail) if the claim fails check 4, else (None, None).

    Comparison is on the string form. The artifact payloads are scalars, and a
    loose comparison here would reintroduce exactly the ambiguity the check
    exists to remove.
    """
    if os.environ.get("CB_FIELD_CHECK", "on").lower() == "off":
        return None, None

    field = claim.get("asserts_field")
    if not field or "asserts_value" not in claim:
        return UNVERIFIABLE, None
    if field not in CHECKABLE_FIELDS:
        return UNVERIFIABLE, f"unknown field {field}"
    asserted = str(claim.get("asserts_value")).strip()
    if not asserted:
        # An empty value is the same failure as supplying none: the model gave
        # the gate nothing to check. Counting it as a fabrication would inflate
        # the headline number with a formatting fault, which is the thing this
        # file is careful not to do everywhere else.
        return UNVERIFIABLE, "empty value"
    if str(art.get(field)) != asserted:
        return VALUE, str(art.get(field))
    return None, None


def verify(dispute, claims):
    """Returns a dict: kept claims, stripped claims with reasons, blocked flag.

    hallucination_rate counts EXISTS, KIND and VALUE strips. All three are the
    model asserting something the source records do not contain. A stale
    artifact is a real record cited about the wrong period -- a grounding error,
    not a fabrication -- and an unverifiable claim asserts nothing checkable at
    all. Folding those two in would inflate the headline number and hide which
    failure mode the model actually has.
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
        reason, detail = _field_check(c, art)
        if reason:
            row = {**c, "reason": reason}
            if detail is not None:
                row["actual_value"] = detail
            stripped.append(row)
            continue
        kept.append({**c, "verified_kind": art.get("kind")})

    required = set(dispute.get("required_evidence") or [])
    covered = {c["verified_kind"] for c in kept}
    missing = sorted(required - covered)

    n = len(claims)
    fabricated = sum(1 for s in stripped if s["reason"] in (EXISTS, KIND, VALUE))

    return {
        "kept": kept,
        "stripped": stripped,
        "missing_evidence": missing,
        "blocked": bool(missing),
        "n_claims": n,
        "n_stripped": len(stripped),
        "n_fabricated": fabricated,
        "n_value_mismatch": sum(1 for s in stripped if s["reason"] == VALUE),
        "n_unverifiable": sum(1 for s in stripped if s["reason"] == UNVERIFIABLE),
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