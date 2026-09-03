"""What the merchant loop is worth once responses are neither free nor certain.

The evidence loop's headline is Rs 476,247, and the README already labels it an
upper bound assuming every prompt is answered. This puts a number on the
discount, across the whole range of the two parameters nobody can measure.

TWO CURVES, NOT TWO NUMBERS. Response rate and ingestion recovery are both
unknown, so neither is asserted. The sweep reports what the loop returns at
every combination, and the conclusion to draw is the shape, not a cell.

THE INGESTION MULTIPLIER IS THE POINT OF RUNNING THEM TOGETHER. A merchant
"responding" means attaching a document, and a document is only evidence if
extraction recovers a reference from it. Effective rate = willingness x
recovery. At the measured deterministic recovery of 0.427, a merchant
population answering 60% of prompts delivers usable records on 26% of them, and
the loop returns a quarter of what the upper bound implies. That is the honest
reading of Rs 476,247.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "agent"), os.path.join(HERE, "..", "serve")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import baselines                    # noqa: E402
import distributions_ref as dist    # noqa: E402
import metrics                      # noqa: E402
import timeline as T                # noqa: E402


def _gap_fn(disputes):
    """What a responding merchant would supply: the required kinds not covered.

    Computed from the rulebook and the record, not from serve/evidence.py, so
    this harness has no dependency on the web layer.
    """
    def fn(d):
        req = set(d.get("required_evidence") or [])
        arts = (d.get("artifacts") or {}).values()
        dday = d.get("dispute_day", 0)
        ok = {a["kind"] for a in arts
              if a.get("present") and a.get("created_day", 0) < dday}
        missing = sorted(req - ok)
        return [{"kind": k, "value": f"{k}:supplied"} for k in missing] or None
    return fn


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "..", "data", "holdout.jsonl"))
    ap.add_argument("--recovery", type=float, default=0.427,
                    help="ingestion recovery rate; 1.0 for typed references")
    ap.add_argument("--window", type=int, default=T.RESPONSE_WINDOW_DAYS)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    D = [json.loads(l) for l in open(a.data, encoding="utf-8")]
    fn = _gap_fn(D)
    cost = dist.CONTEST_COST

    base = metrics.net_rupee_impact(D, [baselines.agent(d, cost) for d in D], cost)
    ceiling = T.simulate(D, fn, response_rate=1.0, window=a.window)

    print(f"\n  Merchant loop under response uncertainty · n={len(D)} · "
          f"window={a.window}d\n")
    print(f"    no prompts at all            Rs {base:>12,.0f}")
    print(f"    every prompt answered        Rs {ceiling['net_rupees']:>12,.0f}"
          f"   (+Rs {ceiling['net_rupees'] - base:,.0f})")
    print(f"    prompts sent                 {ceiling['prompted']}\n")

    print(f"  {'willingness':>12}{'typed refs':>14}{'via ingestion':>16}"
          f"{'gain (typed)':>15}{'gain (ingested)':>17}")
    print("  " + "-" * 74)

    # Averaged over seeds. Which merchants respond is a coin flip per dispute,
    # so a single draw puts several hundred thousand rupees of amount variance
    # into a curve that is supposed to show a trend. One seed produced a curve
    # where 60% willingness returned less than 40%, which is sampling noise
    # presented as a finding.
    SEEDS = (11, 29, 47, 83, 101)

    def avg(rate):
        runs = [T.simulate(D, fn, response_rate=rate, window=a.window, seed=s)
                for s in SEEDS]
        return (sum(r["net_rupees"] for r in runs) / len(runs),
                sum(r["responded"] for r in runs) / len(runs))

    rows = []
    for rate in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        tn, tr = avg(rate)
        ino, inr = avg(rate * a.recovery)
        typed = {"net_rupees": tn, "responded": tr}
        ingested = {"net_rupees": ino, "responded": inr}
        print(f"  {rate:>12.0%}{typed['net_rupees']:>14,.0f}"
              f"{ingested['net_rupees']:>16,.0f}"
              f"{typed['net_rupees'] - base:>15,.0f}"
              f"{ingested['net_rupees'] - base:>17,.0f}")
        rows.append(dict(willingness=rate, typed=typed["net_rupees"],
                         ingested=ingested["net_rupees"],
                         responded_typed=typed["responded"],
                         responded_ingested=ingested["responded"]))

    # Do not name a router here. The recovery figure is whatever the caller
    # passed, and the two routers measured very differently (42.7% for the
    # deterministic one against a mock that cannot read prose, 100% for
    # qwen3:8b on 20 documents). Hard-coding an attribution printed the wrong
    # source whenever the flag was used.
    print(f"\n  Ingestion recovery applied: {a.recovery:.1%} "
          f"(passed via --recovery; see eval/ingest_eval.py).")
    print("  Effective response rate is willingness x recovery, so the right"
          "-hand\n  column is what the loop returns when merchants attach "
          "documents rather\n  than typing references by hand.")

    if a.json_out:
        json.dump({"base": base, "ceiling": ceiling["net_rupees"], "rows": rows},
                  open(a.json_out, "w"), indent=2, default=str)
        print(f"\n  wrote {a.json_out}")