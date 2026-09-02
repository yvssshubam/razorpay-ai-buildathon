"""A bounded redraft loop: the one place this system iterates.

WHAT IT DOES. Draft, verify, and if the packet is blocked, tell the drafter
exactly which claims were rejected and why, then let it try once more. Re-verify.
Escalate if it still fails. Perception, action, observation, termination.

WHY IT IS BOUNDED AT ONE RETRY AND NOT N. Every attempt costs a model call and
adds latency to a decision that is already priced at Rs 250. An unbounded loop
in a money system is an unbounded bill, and the failure it is recovering from is
a drafting error the model already made once. If the second attempt fails, the
evidence for a third being better is thin and the case belongs with a person.
The cap is a policy choice, exposed as max_attempts, defaulting to 2 total.

WHY IT IS OFF BY DEFAULT. Every published figure in this project was measured
without it. Turning it on silently would invalidate the scorecard, the fault
curve and the bootstrap in one commit. It is opt-in, measured separately, and
reported as its own result.

WHAT IT CAN AND CANNOT RECOVER, MEASURED. A redraft can only fix a claim the
verifier rejected about an artifact that was actually usable: the record exists,
is present, and predates the dispute, and the drafter simply described it
wrongly. It cannot conjure a document that was never written. On the holdout:

    injected   blocked   blocked    recovered   retries   hit rate
      fault    1-shot   w/ loop
      0.00        316       316           0         0        --
      0.10        520       394         126       295       43%
      0.20        646       523         123       498       25%
      0.40        757       719          38       690        6%

AT ZERO MODEL ERROR THE LOOP MAKES ZERO EXTRA CALLS. That is the gate above:
retry only when at least one strip is a drafting error the model could fix.
Stale-artifact strips and structural gaps are skipped, because no rewrite makes
a record younger or conjures a document that was never written.

THE HIT RATE FALLS AS FAULTS RISE, AND THAT IS AN ARTEFACT OF THE MOCK, NOT A
PROPERTY OF THE LOOP. MockProvider ignores the system prompt entirely, so its
"retry" is a second independent sample at the same fault rate, not a corrected
draft. These numbers are therefore the NULL HYPOTHESIS: what a retry buys from a
provider that does not read the feedback. A real model reading the corrections
should sit above this curve, and the distance between the two is the actual
measurement of whether verifier feedback works.

ON REAL MODELS THE LOOP CORRECTLY DOES NOTHING, AND TWO OF THEM AGREE EXACTLY.
Over the first 10 holdout disputes:

    gemini-3.1-flash-lite   5 blocked, 0 retries
    qwen3:8b (local, q4)    5 blocked, 0 retries

Same count from a frontier API and an 8B running on one consumer GPU. That is
what you would expect if the blocks are properties of the evidence rather than
of the drafter, and it is worth more than either number alone: structural blocks
are model-independent, measured rather than argued.

Every block was structural or temporal. Four disputes drafted cleanly and
blocked anyway because a required document does not exist (D00007: one artifact,
one claim, kept, still short of the reason code's requirement). One drafted five
claims that were all stripped as stale, every record dated after the dispute.
The gate declined all five, saving five model calls out of fifteen.

AND THE 8B MATCHED THE FRONTIER MODEL ON THE DRAFTING ITSELF. That is not a
surprise, it is the architecture working: constrained retrieval hands the model
a handful of artifacts and a fixed schema, so there is very little for a drafter
to get wrong. It is direct evidence for the thesis that the scarce capability is
triage and verification rather than generation. It also means the loop has
nothing to recover on either model, which is the honest reason it stays off.

So the loop's cost on a model that drafts cleanly is zero, and so is its
benefit. Its value is a function of drafter quality, which makes it the
component to enable when serving this pipeline from a small local model rather
than a frontier API. Whether verifier feedback actually improves a second draft
remains untested; that needs a model that errs on its own, which means
CB_LLM=ollama, and is not a question this submission answers.

READ THAT TABLE BEFORE BUILDING ANYTHING ON TOP OF THIS. The loop's value is a
function of how bad the drafter is. At zero model error it recovers nothing,
because the only blocks remaining are structural: the evidence never existed.
`gemini-3.1-flash-lite` produced zero fabrications across 223 claims, so on the
model this project actually ships, this loop would fire and recover nothing.

That is the honest framing of agency here. The loop is an error-recovery
mechanism, not an intelligence one. It substitutes for drafter quality, which
makes it valuable exactly when you are running a cheap or local model and
worthless when you are not. It is the thing to build if you want to serve this
pipeline from a 7B model on a single GPU instead of a frontier API.
"""
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
    """Draft, verify, and retry once on a block. Returns (result, trace).

    The trace is the point as much as the result. An agent that retries without
    recording what it saw and what it changed is not auditable, and this system
    logs every other decision it makes.
    """
    provider = provider or _llm.get_provider()
    trace = []

    claims, err = draft_claims(dispute, provider, seed=seed)
    result = verify(dispute, claims)
    trace.append({"attempt": 1, "drafted": len(claims), "kept": len(result["kept"]),
                  "stripped": len(result["stripped"]), "blocked": result["blocked"],
                  "error": err})

    attempt = 1
    while result["blocked"] and attempt < max_attempts:
        # A block with nothing stripped is structural: the drafter did nothing
        # wrong and the required document does not exist. Retrying cannot help,
        # and at zero model error that is EVERY block -- 316 of them on the
        # holdout, which is 316 wasted model calls if this check is missing.
        # Measured before the check existed: 1,116 calls at fault 0.00 to
        # recover exactly nothing.
        # Only these are the drafter's to fix. A stale artifact is not a
        # drafting error in any way a rewrite can address: the record is dated
        # after the dispute and a second attempt cannot make it younger. At
        # fault 0.00 that was the entire retry population, 47 calls for zero
        # recoveries.
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

        # Keep the retry only if it is actually better. A second attempt that
        # strips more than the first is a regression, and silently accepting it
        # would make the loop look useful while making packets worse.
        if not result2["blocked"] or len(result2["kept"]) > len(result["kept"]):
            result = result2
        else:
            trace[-1]["discarded"] = "no improvement on the first attempt"

    result["attempts"] = attempt
    result["trace"] = trace
    result["recovered"] = attempt > 1 and not result["blocked"]
    return result, trace


if __name__ == "__main__":
    # The command behind the table above. Without this the numbers were
    # reproducible only by someone who already knew the seed=i convention,
    # which is exactly the reader who does not need to reproduce them.
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