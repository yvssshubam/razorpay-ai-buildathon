"""Is the merchant memory wrong, or just starved?

WHY THIS EXISTS. eval/sequential_eval.py found that selective asking never beats
asking everyone, at any prompt cost. That result has two very different possible
causes and the sweep cannot tell them apart:

  STARVED   the memory is sound and has too little data. The median merchant
            appears in 4 disputes, and a Beta posterior updated four times sits
            almost exactly on its prior, so the policy is effectively asking
            with no knowledge at all.

  MISPRICED the memory is irrelevant. The policy over-values information because
            ev_if_supplied is computed from the model's p(win), and the model is
            over-confident by 21 points on precisely the blocked disputes it
            wants to ask about. Perfect merchant knowledge would not help.

The distinction matters because the fixes are opposite. Starved says gather more
history or use better priors. Mispriced says no decision layer built on this
classifier can be trusted here, and merchant memory was never the problem.

HOW IT SEPARATES THEM. Run the same policy with an ORACLE memory that reads the
latent _true_response_rate directly. That is a leak, deliberately, and it can
never ship -- agent/sequential.py asserts it does not do this. As an ablation it
is the right instrument, for the same reason the heuristic p(win) ablation is:
it answers "how much of the failure is estimation error" by removing estimation
error entirely.

If oracle VOI still loses, the memory is exonerated and the calibration defect
is the whole story. If oracle VOI wins, the memory is sound and starved.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "agent"), os.path.join(HERE, "..", "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sequential as S             # noqa: E402
import distributions_ref as dist   # noqa: E402
from sequential_eval import run    # noqa: E402
from enrich_v3 import enrich       # noqa: E402


class OracleMemory(S.MerchantMemory):
    """Perfect knowledge of merchant behaviour. NEVER SHIPPABLE.

    Reads _true_response_rate, which agent/sequential.py's leak guard forbids.
    It lives here, in an eval file, so the guard on the policy module stays
    honest: the shipped policy still cannot see this, and the only thing that
    can is a harness whose entire purpose is to measure what the policy is
    missing.
    """

    def __init__(self, disputes):
        super().__init__()
        self._rate = {}
        self._days = {}
        for d in disputes:
            mid = d.get("merchant_id")
            if mid is not None:
                self._rate[mid] = d.get("_true_response_rate")
                self._days[mid] = d.get("_true_response_days")

    def response_rate(self, merchant_id):
        r = self._rate.get(merchant_id)
        return super().response_rate(merchant_id) if r is None else r

    def response_days(self, merchant_id):
        d = self._days.get(merchant_id)
        return super().response_days(merchant_id) if d is None else d


def convergence(disputes, memory):
    """How close did the learned rate get, bucketed by history length?

    The question is whether four observations are enough to move a Beta
    posterior off its prior. If the error is flat across buckets, the memory
    never learned anything and the sweep was measuring the prior.
    """
    buckets = {}
    for d in disputes:
        mid = d.get("merchant_id")
        true = d.get("_true_response_rate")
        if mid is None or true is None:
            continue
        n = memory.seen(mid)
        b = "0" if n == 0 else "1-2" if n <= 2 else "3-5" if n <= 5 else \
            "6-15" if n <= 15 else "16+"
        buckets.setdefault(b, []).append(abs(memory.response_rate(mid) - true))

    order = ["0", "1-2", "3-5", "6-15", "16+"]
    print("\n  Memory convergence: |learned - true| response rate\n")
    print(f"  {'asks seen':>10}{'merchants':>12}{'mean error':>13}")
    print("  " + "-" * 35)
    for b in order:
        v = buckets.get(b)
        if v:
            print(f"  {b:>10}{len(v):>12}{sum(v) / len(v):>13.3f}")
    return {b: sum(v) / len(v) for b, v in buckets.items()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "..", "data", "holdout.jsonl"))
    ap.add_argument("--seed", type=int, default=97)
    ap.add_argument("--contest-cost", type=float, default=dist.CONTEST_COST)
    ap.add_argument("--prompt-costs", type=float, nargs="*",
                    default=[15.0, 150.0, 400.0])
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    D = [json.loads(l) for l in open(a.data, encoding="utf-8")]
    enrich(D, a.seed)      # same overlay, same seed, as sequential_eval
    print(f"\n  Oracle ablation · n={len(D)}")

    out = {}
    for pc in a.prompt_costs:
        learned = run(D, "voi", a.contest_cost, prompt_cost=pc)
        oracle = run(D, "voi", a.contest_cost, prompt_cost=pc,
                     memory=OracleMemory(D))
        always = run(D, "always", a.contest_cost, prompt_cost=pc)
        never = run(D, "never", a.contest_cost, prompt_cost=pc)

        print(f"\n  prompt cost Rs {pc:,.0f}")
        print(f"    never                {never['net']:>12,.0f}")
        print(f"    always               {always['net']:>12,.0f}")
        print(f"    voi, learned memory  {learned['net']:>12,.0f}"
              f"   prompts {learned['prompts']}")
        print(f"    voi, ORACLE memory   {oracle['net']:>12,.0f}"
              f"   prompts {oracle['prompts']}")
        gap = oracle["net"] - learned["net"]
        print(f"    perfect knowledge is worth {gap:+,.0f}")
        out[str(pc)] = dict(never=never["net"], always=always["net"],
                            learned=learned["net"],
                            oracle=oracle["net"], gap=gap)

    conv = convergence(D, run(D, "voi", a.contest_cost)["memory"])
    out["convergence"] = conv

    if a.json_out:
        json.dump(out, open(a.json_out, "w"), indent=2, default=str)
        print(f"\n  wrote {a.json_out}")