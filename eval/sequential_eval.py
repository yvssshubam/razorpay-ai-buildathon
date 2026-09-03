"""Does deciding WHEN to ask beat asking always or never?

THE EXPERIMENT. Replay the queue in order. For each dispute with an evidence
gap, three policies choose differently:

    never    ask nobody. This is the shipped behaviour.
    always   ask every merchant with a gap.
    voi      ask when the expected value of the information exceeds the cost
             of the delay, using merchant history and the response window.

The merchant's actual reply is simulated from their latent response rate and
delay, which the policy never sees. `voi` estimates both from what it has
observed, so early in the replay it is mostly acting on a prior and late in the
replay it is acting on evidence. That ordering is the point: a policy with
memory should separate from one without it as the queue goes on, and if it does
not, memory is not earning its place.

WHAT WOULD MAKE THIS RESULT MEANINGLESS. If `always` wins, asking is simply
cheap and there is nothing to decide. If `voi` wins only because PROMPT_COST
was set high enough to punish `always`, the result is about a constant we
invented. Both are checked: the prompt cost is swept, and the split between
prompts sent and answers received is reported, so the mechanism is visible
rather than inferred from a single total.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "agent"),
           os.path.join(HERE, "..", "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import baselines                    # noqa: E402
import distributions_ref as dist    # noqa: E402
import metrics                      # noqa: E402
import sequential as SQ             # noqa: E402
from classifier import predict_p_win  # noqa: E402
from enrich_v3 import enrich        # noqa: E402


def _supplied_record(d):
    """The dispute as it would be with every missing record supplied.

    Built by the same injection the merchant panel uses: kinds present,
    artifacts dated before the dispute. Used to score EV-if-supplied, not to
    decide anything on its own.
    """
    out = copy.deepcopy(d)
    arts = out.setdefault("artifacts", {})
    present = out.setdefault("present_evidence", [])
    dday = out["dispute_day"]
    have = {a["kind"] for a in arts.values()
            if a.get("present") and a.get("created_day", 0) < dday}
    for kind in set(out.get("required_evidence") or []) - have:
        aid = f"supplied_{kind[:10]}_{len(arts)}"
        arts[aid] = {"artifact_id": aid, "kind": kind, "api_field": None,
                     "created_day": dday - 1, "present": True,
                     "value": f"{kind}:supplied", "provenance": "merchant"}
        if kind not in present:
            present.append(kind)
    return out


def run(disputes, policy, cost, seed=31, prompt_cost=None, memory=None):
    """`memory` is injectable so eval/oracle_ablation.py can substitute a
    perfect-knowledge version and measure how much of this policy's failure is
    estimation error. The default is the real thing; nothing in the shipped
    path passes anything else."""
    if prompt_cost is not None:
        SQ.PROMPT_COST = prompt_cost
    rng = random.Random(seed)
    memory = memory if memory is not None else SQ.MerchantMemory()

    decisions, prompts, answers, asked_ids = [], 0, 0, []

    for d in disputes:
        base = baselines.agent(d, cost)

        # THE POPULATION IS EVERY DISPUTE WITH AN EVIDENCE GAP, not only the
        # ones the agent escalated. An earlier version tested base["blocked"],
        # which is true only for contested-and-blocked cases and misses the
        # much larger set the agent ACCEPTED because the packet was
        # incomplete. Those are the disputes where supplied evidence changes
        # the decision rather than merely unblocking it, and excluding them
        # would have measured the wrong thing entirely: 38 disputes instead of
        # 316, and none of the 240 that flip.
        required = set(d.get("required_evidence") or [])
        covered = {a["kind"] for a in (d.get("artifacts") or {}).values()
                   if a.get("present") and a.get("created_day", 0) < d["dispute_day"]}
        gap = not required.issubset(covered)

        if not gap or policy == "never":
            decisions.append(base)
            continue

        rich = _supplied_record(d)
        p_supplied = predict_p_win(rich)

        if policy == "always":
            act = "ask"
            plan = None
        else:
            plan = SQ.decide(d, base["p_win"], True, p_supplied, memory, cost)
            act = plan["action"]

        if act != "ask":
            decisions.append(base)
            continue

        prompts += 1
        asked_ids.append(d["merchant_id"])

        # The world answers. Latent fields are read HERE, in the simulator,
        # never in the policy.
        answered = rng.random() < d["_true_response_rate"]
        delay = d["_true_response_days"]
        in_time = answered and delay <= (d["deadline_day"] - d["dispute_day"])
        memory.observe(d["merchant_id"], answered and in_time,
                       delay if answered else None)

        if in_time:
            answers += 1
            decisions.append(baselines.agent(rich, cost))
        else:
            decisions.append(base)

    net = metrics.net_rupee_impact(disputes, decisions, cost)
    net -= prompts * SQ.PROMPT_COST
    mix = metrics.outcome_mix(decisions)
    return dict(policy=policy, net=net, prompts=prompts, answers=answers,
                unique_merchants=len(set(asked_ids)), memory=memory, **mix)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "..", "data", "holdout.jsonl"))
    ap.add_argument("--seed", type=int, default=97)
    ap.add_argument("--contest-cost", type=float, default=dist.CONTEST_COST)
    ap.add_argument("--sweep-prompt-cost", action="store_true")
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    disputes = [json.loads(l) for l in open(a.data, encoding="utf-8")]
    enrich(disputes, a.seed)

    costs = [0, 15, 50, 150, 400] if a.sweep_prompt_cost else [SQ.PROMPT_COST]
    rows = []
    for pc in costs:
        print(f"\n  Sequential asking policy · n={len(disputes)} · "
              f"prompt cost Rs {pc}\n")
        print(f"  {'policy':<9}{'net rupees':>13}{'prompts':>10}{'answers':>10}"
              f"{'merchants':>11}{'sub/acc/esc':>16}")
        print("  " + "-" * 69)
        for pol in ("never", "always", "voi"):
            r = run(disputes, pol, a.contest_cost, prompt_cost=pc)
            rows.append({**r, "prompt_cost": pc})
            print(f"  {pol:<9}{r['net']:>13,.0f}{r['prompts']:>10}"
                  f"{r['answers']:>10}{r['unique_merchants']:>11}"
                  f"{r['submitted']:>6}/{r['accepted']}/{r['escalated']:>3}")

    if a.json_out:
        # Drop the live MerchantMemory object: it is returned for in-process
        # inspection, not for serialisation, and json.dump chokes on it.
        # Keep a scalar summary so the JSON still records how much history
        # the run actually accumulated.
        serialisable = []
        for r in rows:
            r = dict(r)
            mem = r.pop("memory", None)
            if mem is not None:
                r["merchants_observed"] = len(getattr(mem, "asked", {}) or {})
            serialisable.append(r)
        json.dump(serialisable, open(a.json_out, "w"), indent=2)
        print(f"\n  wrote {a.json_out}")


if __name__ == "__main__":
    main()