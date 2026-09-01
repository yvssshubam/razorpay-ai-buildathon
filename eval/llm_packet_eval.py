"""Completeness and hallucination, measured on the LLM path.

WHY THIS FILE EXISTS
--------------------
run_eval.py reports both label-free metrics off baselines._build_packet, which
is deterministic. That makes them tautologies:

  packet_completeness  _build_packet sets submitted only when
                       required <= kept_kinds, and the metric then checks
                       req.issubset(got) on exactly those packets. It cannot
                       return anything but 1.0.

  hallucination_rate   claims come from a builder that only ever cites
                       artifacts it just read off the record. Nothing can be
                       fabricated, so the rate is 0.0 by construction.

Both numbers are true. Neither is evidence. The stage that can actually
fabricate is Stage 3, and it is never exercised by the scorecard.

This harness runs the real thing -- draft_claims -> verify -- over the holdout
and reports what the verifier catches, at a range of injected fault rates.

BLOCK ATTRIBUTION
-----------------
A blocked packet is not automatically a model failure. Two causes, and they
carry opposite implications:

  structural   the record genuinely has no fresh artifact of a required kind.
               A perfect drafter blocks here too. This is the evidence-gap
               rate of the data, and it is the floor.

  model        every required kind WAS available to cite, and the packet still
               came up short: the drafter fabricated, mislabelled, or omitted.

Reporting one number for both would let a high structural rate masquerade as
model error, or let model error hide behind "the data was incomplete".

    python eval/llm_packet_eval.py                    # sweep 0.00-0.40, mock
    python eval/llm_packet_eval.py --rates 0.15       # single point
    CB_PROVIDER=gemini python eval/llm_packet_eval.py --rates 0 --n 40
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for sub in ("eval", "agent"):
    p = os.path.join(REPO, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import baselines            # noqa: E402
import llm as _llm          # noqa: E402
from draft import draft_claims, retrieve   # noqa: E402
from verify import verify, EXISTS, KIND, TEMPORAL  # noqa: E402


def citable_kinds(dispute):
    """Kinds a flawless drafter could legitimately cite: retrieved, present,
    and predating the dispute. Same support test the verifier applies."""
    dday = dispute.get("dispute_day", 0)
    return {a["kind"] for a in retrieve(dispute).values()
            if a.get("created_day", 0) < dday}


def attribute_block(dispute, result):
    """structural | model | None."""
    if not result["blocked"]:
        return None
    required = set(dispute.get("required_evidence") or [])
    unreachable = required - citable_kinds(dispute)
    # Blocked only on kinds that were never citable -> nobody could have done
    # better. Blocked on anything that WAS available -> the drafter lost it.
    return "structural" if set(result["missing_evidence"]) <= unreachable else "model"


def run(disputes, provider, policy_name="agent"):
    policy = baselines.POLICIES[policy_name]

    agg = {
        "policy": policy_name,
        "n_disputes": 0, "n_claims": 0,
        "fabricated": 0, "kind_errors": 0, "stale": 0,
        "value_errors": 0, "unverifiable": 0,
        "blocked": 0, "blocked_structural": 0, "blocked_model": 0,
        "completeness_sum": 0.0,
        "draft_errors": 0,
        "submitted_clean": 0,
    }
    rows = []

    for i, d in enumerate(disputes):
        # Only cases the policy would actually take forward reach Stage 3.
        dec = policy(d)
        if not dec["contest"]:
            continue

        claims, err = draft_claims(d, provider, seed=i)
        if err:
            agg["draft_errors"] += 1
        if type(provider).__name__ == "GeminiProvider":
            import time
            time.sleep(4.5)

        r = verify(d, claims)
        cause = attribute_block(d, r)

        agg["n_disputes"] += 1
        agg["n_claims"] += r["n_claims"]
        agg["fabricated"] += r["n_fabricated"]
        agg["kind_errors"] += sum(1 for s in r["stripped"] if s["reason"] == KIND)
        agg["stale"] += sum(1 for s in r["stripped"] if s["reason"] == TEMPORAL)
        agg["value_errors"] += r.get("n_value_mismatch", 0)
        agg["unverifiable"] += r.get("n_unverifiable", 0)
        agg["completeness_sum"] += r["completeness"]
        if r["blocked"]:
            agg["blocked"] += 1
            agg["blocked_" + cause] += 1
        else:
            agg["submitted_clean"] += 1

        rows.append({
            "dispute_id": d.get("dispute_id"),
            "reason_code": d.get("reason_code"),
            "n_claims": r["n_claims"],
            "fabricated": r["n_fabricated"],
            "blocked": r["blocked"],
            "cause": cause,
            "completeness": round(r["completeness"], 3),
        })

    n = max(agg["n_disputes"], 1)
    c = max(agg["n_claims"], 1)
    agg.update({
        "hallucination_rate": round(agg["fabricated"] / c, 4),
        "stale_rate": round(agg["stale"] / c, 4),
        "value_error_rate": round(agg["value_errors"] / c, 4),
        "unverifiable_rate": round(agg["unverifiable"] / c, 4),
        "block_rate": round(agg["blocked"] / n, 4),
        "structural_block_rate": round(agg["blocked_structural"] / n, 4),
        "model_block_rate": round(agg["blocked_model"] / n, 4),
        "mean_completeness": round(agg["completeness_sum"] / n, 4),
        # The number that matters: fabrications that reached a submitted packet.
        "fabrications_submitted": 0,
    })

    # A fabricated claim can only ship if its packet was NOT blocked. The gate
    # strips before the completeness check, so this should be zero at every
    # fault rate. If it is ever non-zero the gate has a hole.
    for row, d in zip(rows, [x for x in disputes if policy(x)["contest"]]):
        if not row["blocked"] and row["fabricated"]:
            agg["fabrications_submitted"] += row["fabricated"]

    del agg["completeness_sum"]
    return agg, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(REPO, "data", "holdout.jsonl"))
    ap.add_argument("--rates", nargs="*", type=float,
                    default=[0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40])
    ap.add_argument("--n", type=int, default=0, help="cap disputes (0 = all)")
    ap.add_argument("--policy", default="agent", choices=list(baselines.POLICIES))
    ap.add_argument("--out", default=os.path.join(REPO, "data", "llm_packet_eval.json"))
    a = ap.parse_args()

    with open(a.data, encoding="utf-8") as fh:
        disputes = [json.loads(l) for l in fh if l.strip()]
    if a.n:
        disputes = disputes[:a.n]

    provider_name = os.environ.get("CB_PROVIDER", "mock")
    results = []

    print(f"provider={provider_name}  policy={a.policy}  n={len(disputes)}\n")
    hdr = (f"{'fault':>6} {'claims':>7} {'halluc':>8} {'value':>7} {'unver':>7} {'stale':>7} "
           f"{'block':>7} {'struct':>7} {'model':>7} {'complete':>9} {'shipped':>8}")
    print(hdr)
    print("-" * len(hdr))

    for rate in a.rates:
        if provider_name == "mock":
            os.environ["CB_FAULT_RATE"] = str(rate)
            provider = _llm.MockProvider(fault_rate=rate)
        else:
            provider = _llm.get_provider(provider_name)
        agg, _ = run(disputes, provider, a.policy)
        agg["fault_rate"] = rate
        agg["provider"] = type(provider).__name__
        results.append(agg)
        print(f"{rate:>6.2f} {agg['n_claims']:>7} {agg['hallucination_rate']:>8.3f} "
              f"{agg['value_error_rate']:>7.3f} {agg['unverifiable_rate']:>7.3f} "
              f"{agg['stale_rate']:>7.3f} {agg['block_rate']:>7.3f} "
              f"{agg['structural_block_rate']:>7.3f} {agg['model_block_rate']:>7.3f} "
              f"{agg['mean_completeness']:>9.3f} {agg['fabrications_submitted']:>8}")
        if provider_name != "mock":
            break

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)
    print(f"\nwrote {a.out}")

    shipped = sum(r["fabrications_submitted"] for r in results)
    base = results[0]
    print(f"\nfabrications reaching a submitted packet, all fault rates: {shipped}")
    print(f"structural block floor at fault_rate=0: "
          f"{base['structural_block_rate']:.3f} "
          f"({base['blocked_structural']}/{base['n_disputes']} packets)")
    print("That floor is the evidence-gap rate of the data. A flawless drafter "
          "blocks there too.")


if __name__ == "__main__":
    main()