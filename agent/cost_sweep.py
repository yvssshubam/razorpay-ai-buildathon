"""Sweep the invented cost constants.

Every rupee figure in this project is a function of four numbers that were
chosen, not measured:

    CONTEST_COST          what it costs to assemble and submit a packet
    HUMAN_REVIEW_COST     what it costs when a blocked packet reaches a person
    NET_RECOVERY_FRACTION share of the disputed amount actually recovered on a win
    HUMAN_RESOLVE_RATE    share of escalated packets a human can rescue

The headline (agent beats contest-all by ~Rs 223k) is only a RESULT if it
survives plausible variation in all four. If it flips, it is a CLAIM about the
constants, not a finding about the policy. This script varies one at a time,
holding the rest at their defaults, and reports where the ordering breaks.

Runs the eval in-process rather than shelling out, so no CLI flags are needed
on run_eval.py.
"""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.path.insert(0, os.path.join(ROOT, "generator"))

HOLDOUT = os.path.join(ROOT, "data", "holdout.jsonl")

# One-at-a-time ranges. Defaults are whatever distributions.py already sets.
SWEEPS = {
    "CONTEST_COST":          [100, 175, 250, 400, 600, 900],
    "HUMAN_REVIEW_COST":     [300, 500, 800, 1200, 1800, 2500],
    # Sourced range. Razorpay platform fee: 2%+GST standard domestic
    # (= 0.9764, the default) and 3%+GST premium/international (= 0.9646).
    # Wider bounds either side for robustness. NOTE: this sweeps the BASE;
    # dist.net_recovery() applies PREMIUM_DELTA on top, so Amex moves with it.
    "NET_RECOVERY_FRACTION": [0.90, 0.95, 0.9646, 0.9764, 1.00],
    "HUMAN_RESOLVE_RATE":    [0.20, 0.35, 0.50, 0.65, 0.80],
}


def load_disputes():
    with open(HOLDOUT, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def net_for(policy_name, disputes, metrics, baselines, contest_cost):
    """Run one policy and return its net rupees.

    contest_cost is passed explicitly because the scorer takes it as an
    argument rather than reading distributions. Patching the module constant
    alone would have changed the DECISION but not the SCORING, which would
    have quietly produced wrong numbers rather than an error.
    """
    decisions = [baselines.POLICIES[policy_name](d) for d in disputes]
    out = metrics.net_rupee_impact(disputes, decisions, contest_cost)
    if isinstance(out, (int, float)):
        return out
    for k in ("net_rupees", "net", "net_rs", "net_impact"):
        if isinstance(out, dict) and k in out:
            return out[k]
    raise SystemExit(
        f"net_rupee_impact returned {type(out).__name__}: {out!r}")

def _patch(const, value):
    """Set the constant on BOTH modules.

    generator/distributions.py drives the DECISION (baselines).
    eval/distributions_ref.py drives the SCORING (metrics).
    They are separate modules holding the same constants. Patching one and not
    the other produces a sweep that runs cleanly and measures nothing, which is
    what the first version of this script did.
    """
    import distributions
    import distributions_ref
    setattr(distributions, const, value)
    setattr(distributions_ref, const, value)
def run_once(disputes):
    import distributions
    import baselines
    import metrics
    importlib.reload(baselines)
    cc = distributions.CONTEST_COST
    return (net_for("agent", disputes, metrics, baselines, cc),
            net_for("contest_all", disputes, metrics, baselines, cc))

def main():
    import distributions
    disputes = load_disputes()
    defaults = {k: getattr(distributions, k) for k in SWEEPS}
    print("defaults:", {k: v for k, v in defaults.items()})

    flips, dead = [], []
    for const, values in SWEEPS.items():
        print(f"\n=== {const} (default {defaults[const]}) ===")
        print(f"{'value':>10} {'agent':>12} {'contest_all':>12} {'margin':>12}")
        seen = set()
        for v in values:
            _patch(const, v)
            agent_net, all_net = run_once(disputes)
            margin = agent_net - all_net
            seen.add((round(agent_net, 2), round(all_net, 2)))
            flag = "  <-- AGENT LOSES" if margin <= 0 else ""
            print(f"{v:>10} {agent_net:12,.0f} {all_net:12,.0f} "
                  f"{margin:12,.0f}{flag}")
            if margin <= 0:
                flips.append((const, v, margin))
        if len(seen) == 1:
            dead.append(const)
            print("  !! NOT SWEPT: every value gave identical output. This "
                  "constant never reached the scorer, so the rows above "
                  "measure nothing.")
        _patch(const, defaults[const])

    print("\n" + "=" * 60)
    if dead:
        print(f"BROKEN SWEEPS ({len(dead)}/{len(SWEEPS)}): {', '.join(dead)}")
        print("Do not report robustness for these. They were not varied.")
    swept = [c for c in SWEEPS if c not in dead]
    if flips:
        print("ORDERING BREAKS AT:")
        for c, v, m in flips:
            print(f"  {c} = {v}  (margin {m:,.0f})")
        print("Report these as the boundary conditions of the headline.")
    elif swept:
        print("Agent beats contest-all across every value tested for: "
              f"{', '.join(swept)}")


if __name__ == "__main__":
    main()