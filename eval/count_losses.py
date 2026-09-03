"""Recompute the contested-loss figures quoted in eval/metrics.py's docstring.

Run from the eval/ directory:

    python count_losses.py ../data/holdout.jsonl

The docstring claims "N of the agent's M contested losses are of this shape",
where "this shape" means: the agent contested it, it lost, and contesting was
nevertheless the CORRECT call under expected value. That is the whole dual-
precision thesis in one number, so it should not be quoted from an old run.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "generator"))

import baselines
import distributions_ref as dist

path = sys.argv[1] if len(sys.argv) > 1 else "../data/holdout.jsonl"
disputes = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

cc = dist.CONTEST_COST

contested = contested_lost = ev_positive_losses = 0
worst = None

for d in disputes:
    x = baselines.agent(d)
    if not x["contest"]:
        continue
    contested += 1
    if d["label_won"]:
        continue
    contested_lost += 1

    # Was contesting correct under EV, despite the loss?
    ev = d["_true_p_win"] * d["amount"] * dist.net_recovery(d.get("network"))
    if ev > cc:
        ev_positive_losses += 1
        # Track the largest such case, for a worked example in the docstring.
        if worst is None or d["amount"] > worst["amount"]:
            worst = {"id": d.get("dispute_id") or d.get("id"),
                     "amount": d["amount"], "p": d["_true_p_win"],
                     "net": d.get("network"), "ev": ev}

print(f"agent contested        : {contested}")
print(f"  of which lost        : {contested_lost}")
print(f"  losses that were EV-correct : {ev_positive_losses}")
print()
print(f"DOCSTRING LINE: {ev_positive_losses} of the agent's "
      f"{contested_lost} contested losses are of this shape.")

if worst:
    print()
    print("Largest EV-correct loss (candidate worked example):")
    print(f"  {worst['id']}  Rs {worst['amount']:,.0f}  "
          f"p={worst['p']:.2f}  network={worst['net']}  "
          f"EV=Rs {worst['ev']:,.0f}")