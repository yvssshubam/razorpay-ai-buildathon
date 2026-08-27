"""Score every policy on the six metrics, against both baselines.

    python run_eval.py --data ../data/holdout.jsonl
    python run_eval.py --data ../data/holdout.jsonl --sweep
    python run_eval.py --data ../data/holdout.jsonl --sweep --chart ../data/cost_curve.png

--sweep answers the question the single-cost run cannot: at what cost per
dispute does triage start to beat contesting everything? That crossover is the
result, given no public India contest-cost figure exists.
"""
import argparse
import json

import metrics
import baselines
import distributions_ref as dist

SWEEP_COSTS = [50, 100, 200, 350, 500, 750, 1000, 1500, 2000, 3000]


def load(path):
    return [json.loads(l) for l in open(path)]


def run_policy(disputes, name, contest_cost):
    fn = baselines.POLICIES[name]
    return [fn(d, contest_cost) for d in disputes]


def score(disputes, name, contest_cost):
    dec = run_policy(disputes, name, contest_cost)
    pw, rw = metrics.precision_recall(disputes, dec, contest_cost, "winnable")
    pe, re_ = metrics.precision_recall(disputes, dec, contest_cost, "ev")
    return dict(
        policy=name,
        contest_cost=contest_cost,
        completeness=metrics.packet_completeness(disputes, dec),
        hallucination=metrics.hallucination_rate(dec),
        precision_winnable=round(pw, 3), recall_winnable=round(rw, 3),
        precision_ev=round(pe, 3), recall_ev=round(re_, 3),
        cost_wrong=metrics.cost_of_being_wrong(disputes, dec, contest_cost),
        net_rupees=metrics.net_rupee_impact(disputes, dec, contest_cost),
        outcome_mix=metrics.outcome_mix(dec),
        human_queue=metrics.human_queue_load(dec),
        per_tier=metrics.per_tier_breakdown(disputes, dec, contest_cost),
    )


def _fmt(v, w=8):
    return f"{'--':>{w}}" if v is None else f"{v:>{w}.3f}"


def print_scorecard(disputes, cost):
    results = [score(disputes, n, cost) for n in
               ["contest_all", "contest_none", "agent"]]
    print(f"\n  Scorecard · n={len(disputes)} · contest_cost=Rs {cost:,.0f} · "
          f"human_review=Rs {dist.HUMAN_REVIEW_COST:,.0f}\n")
    print(f"  {'policy':<13}{'complete':>9}{'halluc':>9}{'P/R winnable':>16}"
          f"{'P/R ev':>14}{'net_rupees':>13}{'sub/acc/esc':>16}")
    print("  " + "-" * 88)
    for r in results:
        m = r["outcome_mix"]
        pr_w = f"{r['precision_winnable']:.2f}/{r['recall_winnable']:.2f}"
        pr_e = f"{r['precision_ev']:.2f}/{r['recall_ev']:.2f}"
        mix = f"{m['submitted']}/{m['accepted']}/{m['escalated']}"
        print(f"  {r['policy']:<13}{_fmt(r['completeness'], 9)}{_fmt(r['hallucination'], 9)}"
              f"{pr_w:>16}{pr_e:>14}{r['net_rupees']:>13,.0f}{mix:>16}")

    a = next(r for r in results if r["policy"] == "agent")
    print("\n  Agent, per tier:")
    print(f"    {'tier':<6}{'n':>5}{'P/R winnable':>15}{'P/R ev':>12}{'net Rs':>14}")
    for t, row in a["per_tier"].items():
        pw = f"{row['precision_winnable']:.2f}/{row['recall_winnable']:.2f}"
        pe = f"{row['precision_ev']:.2f}/{row['recall_ev']:.2f}"
        print(f"    {t:<6}{row['n']:>5}{pw:>15}{pe:>12}{row['net_rupees']:>14,.0f}")
    return results


def sweep(disputes, chart_path=None, json_out=None):
    rows = []
    print(f"\n  Cost sweep · n={len(disputes)} · net rupees by policy\n")
    print(f"  {'cost':>7}{'contest_all':>14}{'contest_none':>14}{'agent':>12}   winner")
    print("  " + "-" * 62)
    for c in SWEEP_COSTS:
        r = {n: score(disputes, n, c) for n in
             ["contest_all", "contest_none", "agent"]}
        nets = {n: r[n]["net_rupees"] for n in r}
        winner = max(nets, key=nets.get)
        rows.append(dict(cost=c, **nets, winner=winner))
        print(f"  {c:>7,}{nets['contest_all']:>14,.0f}"
              f"{nets['contest_none']:>14,.0f}{nets['agent']:>12,.0f}   {winner}")

    cross = next((r["cost"] for r in rows if r["winner"] == "agent"), None)
    if cross:
        print(f"\n  Crossover: the agent overtakes contesting everything at "
              f"roughly Rs {cross:,} per dispute.")
    neg = next((r["cost"] for r in rows if r["contest_all"] < 0), None)
    if neg:
        print(f"  Contesting everything turns net-negative at roughly Rs {neg:,}.")

    if json_out:
        json.dump(rows, open(json_out, "w"), indent=2)
        print(f"  wrote {json_out}")
    if chart_path:
        _chart(rows, chart_path)
        print(f"  wrote {chart_path}")
    return rows


def _chart(rows, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    costs = [r["cost"] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for key, label, style in [("contest_all", "Contest everything", "--"),
                              ("contest_none", "Contest nothing", ":"),
                              ("agent", "Agent (expected value)", "-")]:
        ax.plot(costs, [r[key] for r in rows], style, marker="o",
                markersize=3.5, label=label, linewidth=1.8)
    ax.axhline(0, color="#999", linewidth=0.8)
    ax.set_xlabel("Cost of contesting one dispute (INR) — ASSUMPTION, no public India figure")
    ax.set_ylabel("Net rupee impact")
    ax.set_title("Triage pays off as the cost of being wrong rises")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="../data/holdout.jsonl")
    ap.add_argument("--contest-cost", type=float, default=dist.CONTEST_COST)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--chart", default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    disputes = load(args.data)
    if args.sweep:
        sweep(disputes, args.chart, args.json_out)
    else:
        res = print_scorecard(disputes, args.contest_cost)
        if args.json_out:
            json.dump(res, open(args.json_out, "w"), indent=2)
            print(f"\n  wrote {args.json_out}")
    print()


if __name__ == "__main__":
    main()
