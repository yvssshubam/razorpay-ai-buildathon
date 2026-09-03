"""Predicted p(win) against realised outcomes, split by packet disposition.

WHY THIS FILE EXISTS. The README asserted a calibration gap on blocked
packets and cited a section that does not exist. A number with no command
behind it is not a measurement. This prints the gap under a definition
anyone can read: mean predicted p(win) against the observed win rate, on
the subpopulation the agent blocks.

ONLY THE AGENT IS REPORTED. contest_all does not consult the classifier,
so its decisions carry no p_win and there is nothing to calibrate. A
figure computed on the 316 disputes it escalates would be a calibration
of predictions that policy never made.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "agent"))

import baselines  # noqa: E402


def split(disputes, decisions):
    groups = {"blocked": [], "submitted": [], "all": []}
    for d, x in zip(disputes, decisions):
        if x.get("p_win") is None:
            continue
        row = (x["p_win"], 1.0 if d["label_won"] else 0.0)
        groups["all"].append(row)
        if x.get("blocked"):
            groups["blocked"].append(row)
        if x.get("submitted"):
            groups["submitted"].append(row)
    return groups


def report(label, groups):
    print(f"\n  {label}")
    print(f"    {'subset':<12}{'n':>6}{'mean p_win':>13}"
          f"{'observed win':>15}{'gap':>10}")
    print("    " + "-" * 56)
    for name in ("blocked", "submitted", "all"):
        rows = groups[name]
        if not rows:
            print(f"    {name:<12}{0:>6}{'--':>13}{'--':>15}{'--':>10}")
            continue
        n = len(rows)
        pred = sum(p for p, _ in rows) / n
        obs = sum(w for _, w in rows) / n
        print(f"    {name:<12}{n:>6}{pred:>13.3f}{obs:>15.3f}"
              f"{pred - obs:>+10.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "holdout.jsonl"))
    ap.add_argument("--contest-cost", type=float, default=250.0)
    a = ap.parse_args()

    disputes = [json.loads(l) for l in open(a.data, encoding="utf-8")]
    print(f"\n  Subpopulation calibration · n={len(disputes)} · "
          f"contest_cost=Rs {a.contest_cost:,.0f}")
    dec = [baselines.POLICIES["agent"](d, a.contest_cost) for d in disputes]
    report("policy = agent", split(disputes, dec))
    print()