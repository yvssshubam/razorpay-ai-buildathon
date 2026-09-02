from __future__ import annotations
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import llm as _llm            # noqa: E402
from draft import build_context, draft_claims, parse_claims, retrieve  # noqa: E402
from verify import EXISTS, KIND, TEMPORAL, UNVERIFIABLE, VALUE, verify  # noqa: E402

# What to tell the drafter about each rejection. Phrased as the correction to
# make, not as a scolding: the second attempt is a fresh generation, and the
# only useful content in this string is what would make it right.
FEEDBACK = {
    EXISTS: "cited artifact {aid}, which is not in the retrieved set. "
            "Use only the IDs given to you.",
    KIND: "described artifact {aid} as a {claimed}. It is a {actual}. "
          "Never upgrade or reinterpret a kind.",
    TEMPORAL: "cited artifact {aid}, which is dated after the dispute and "
              "cannot support it. Do not cite it again.",
    VALUE: "stated {field}={claimed} for artifact {aid}. The record says "
           "{actual}. Copy the field exactly.",
    UNVERIFIABLE: "gave no checkable field for artifact {aid}. Every claim "
                  "needs asserts_field and asserts_value copied from the record.",
}


def _feedback_lines(dispute, result):
    """One correction per rejected claim, plus what the packet still needs."""
    retrieved = retrieve(dispute)
    lines = []
    for c in result["stripped"]:
        aid = c.get("artifact_id")
        art = retrieved.get(aid) or {}
        lines.append("- You " + FEEDBACK[c["reason"]].format(
            aid=aid,
            claimed=c.get("asserts_kind") or c.get("asserts_value"),
            actual=c.get("actual_kind") or c.get("actual_value") or art.get("kind"),
            field=c.get("asserts_field"),
        ))
    if result["missing_evidence"]:
        lines.append("- The packet still needs: "
                     + ", ".join(result["missing_evidence"])
                     + ". If no retrieved record supports one of these, omit it "
                       "rather than inventing a claim; an incomplete packet is "
                       "correct and a fabricated one is not.")
    return "\n".join(lines)


def draft_and_verify(dispute, provider=None, seed=0, max_attempts=2):
   
    provider = provider or _llm.get_provider()
    trace = []

    claims, err = draft_claims(dispute, provider, seed=seed)
    result = verify(dispute, claims)
    trace.append({"attempt": 1, "drafted": len(claims), "kept": len(result["kept"]),
                  "stripped": len(result["stripped"]), "blocked": result["blocked"],
                  "error": err})

    attempt = 1
    while result["blocked"] and attempt < max_attempts:
        correctable = [c for c in result["stripped"]
                       if c["reason"] in (EXISTS, KIND, VALUE, UNVERIFIABLE)]
        if not correctable:
            trace.append({"attempt": attempt + 1,
                          "skipped": "no correctable strip; the gap is in the "
                                     "evidence, not the drafting"})
            break

        attempt += 1
        corrections = _feedback_lines(dispute, result)
        retrieved = retrieve(dispute)
        context = build_context(dispute, retrieved)
        retry_system = (
            "Your previous draft was rejected by a verifier. Correct it.\n\n"
            + corrections
            + "\n\nDraft the claims again from scratch, applying every correction "
              "above. Same JSON format, same rules."
        )
        try:
            raw = provider.draft(retry_system, context, seed=seed + 1000 * attempt)
        except _llm.LLMError as e:
            trace.append({"attempt": attempt, "error": f"provider: {e}"})
            break

        claims2, err2 = parse_claims(raw)
        result2 = verify(dispute, claims2)
        trace.append({"attempt": attempt, "drafted": len(claims2),
                      "kept": len(result2["kept"]), "stripped": len(result2["stripped"]),
                      "blocked": result2["blocked"], "error": err2})

        if not result2["blocked"] or len(result2["kept"]) > len(result["kept"]):
            result = result2
        else:
            trace[-1]["discarded"] = "no improvement on the first attempt"

    result["attempts"] = attempt
    result["trace"] = trace
    result["recovered"] = attempt > 1 and not result["blocked"]
    return result, trace


if __name__ == "__main__":
    import json

    HERE = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "..", "data", "holdout.jsonl")
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 800

    disputes = [json.loads(l) for l in open(path, encoding="utf-8")][:n]
    provider = _llm.get_provider()
    rate = os.environ.get("CB_FAULT_RATE", "unset")

    one_shot = loop = recovered = retries = 0
    for i, d in enumerate(disputes):
        claims, _ = draft_claims(d, provider, seed=i)   # seed=i: see llm.py
        one_shot += verify(d, claims)["blocked"]
        r, trace = draft_and_verify(d, provider, seed=i, max_attempts=2)
        loop += r["blocked"]
        recovered += r["recovered"]
        retries += sum(1 for t in trace if t.get("attempt", 0) > 1 and "drafted" in t)

    print(f"\n  Redraft loop · n={len(disputes)} · provider={_llm.get_provider().__class__.__name__}"
          f" · CB_FAULT_RATE={rate}\n")
    print(f"    blocked, single draft   {one_shot}")
    print(f"    blocked, with the loop  {loop}")
    print(f"    recovered               {recovered}")
    print(f"    retry calls made        {retries}")
    if retries:
        print(f"    hit rate                {recovered / retries:.0%}")
    else:
        print("    hit rate                -- (no retry was worth making)")