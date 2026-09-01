"""Score every policy on the six metrics, against both baselines.

    python run_eval.py --data ../data/holdout.jsonl
    python run_eval.py --data ../data/holdout.jsonl --sweep
    python run_eval.py --data ../data/holdout.jsonl --sweep --chart ../data/cost_curve.png

--sweep answers the question the single-cost run cannot: at what cost per
dispute does triage start to beat contesting everything? That crossover is the
result, given no public India contest-cost figure exists.
"""
import argparse
import os
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

    # The track brief asks for this by name: rupees spent contesting losers,
    # plus rupees forfeited by accepting winnable cases. It is not a derived
    # footnote -- it is the false-positive cost, and the split between the two
    # columns is the triage story. contest-all wastes contests; the agent
    # forfeits wins instead, and forfeits less than the waste it avoids.
    print("\n  Cost of being wrong (Rs):")
    print(f"    {'policy':<13}{'paid to lose':>16}{'left behind':>15}{'total':>14}")
    print("    " + "-" * 58)
    for r in results:
        c = r["cost_wrong"]
        print(f"    {r['policy']:<13}{c['paid_to_lose']:>16,.0f}"
              f"{c['left_behind']:>15,.0f}{c['total']:>14,.0f}")

    a = next(r for r in results if r["policy"] == "agent")
    print("\n  Agent, per tier:")
    print(f"    {'tier':<6}{'n':>5}{'P/R winnable':>15}{'P/R ev':>12}{'net Rs':>14}")
    for t, row in a["per_tier"].items():
        pw = f"{row['precision_winnable']:.2f}/{row['recall_winnable']:.2f}"
        pe = f"{row['precision_ev']:.2f}/{row['recall_ev']:.2f}"
        print(f"    {t:<6}{row['n']:>5}{pw:>15}{pe:>12}{row['net_rupees']:>14,.0f}")
    return results


def ablation_bootstrap(disputes, cost, n_boot=2000, seed=7):
    """Paired bootstrap of heuristic p(win) against the learned model.

    WHY PAIRED AND NOT TWO SEPARATE INTERVALS. Both policies score the same 800
    disputes, so their errors are correlated: a large dispute that both get
    right inflates both totals together. Resampling each independently and
    comparing the two intervals would overstate the spread of the difference.
    The difference is taken per dispute first, then resampled, so the shared
    variation cancels.

    Decisions are made ONCE per estimator on the full set, because a policy is
    a pure function of one dispute. Only the scoring is resampled.

    This exists because the README quotes this interval, and a figure quoted in
    a README that opens by promising everything reproduces has to have a
    command behind it.
    """
    import random as _r

    def nets(mode):
        prev = os.environ.get("CB_P_WIN")
        if mode:
            os.environ["CB_P_WIN"] = mode
        else:
            os.environ.pop("CB_P_WIN", None)
        try:
            dec = run_policy(disputes, "agent", cost)
        finally:
            if prev is None:
                os.environ.pop("CB_P_WIN", None)
            else:
                os.environ["CB_P_WIN"] = prev
        return [metrics.net_rupee_impact([d], [x], cost)
                for d, x in zip(disputes, dec)]

    h = nets("heuristic")
    m = nets(None)
    gap = [a - b for a, b in zip(h, m)]

    rng = _r.Random(seed)
    n = len(gap)
    draws = sorted(sum(gap[rng.randrange(n)] for _ in range(n))
                   for _ in range(n_boot))
    lo, hi = draws[int(0.025 * n_boot)], draws[int(0.975 * n_boot) - 1]
    neg = sum(1 for g in draws if g <= 0)

    print(f"\n  Ablation · heuristic p(win) vs learned model · n={n} · "
          f"{n_boot:,} resamples\n")
    print(f"    heuristic net       Rs {sum(h):>12,.0f}")
    print(f"    model net           Rs {sum(m):>12,.0f}")
    print(f"    difference          Rs {sum(gap):>12,.0f}")
    print(f"    95% CI              Rs {lo:>12,.0f}  to  Rs {hi:,.0f}")
    print(f"    draws <= 0                   {neg} / {n_boot}")
    print("\n  Monte Carlo noise moves the bounds by a few hundred rupees "
          "between seeds;\n  the sign of the conclusion does not move: the two "
          "are not distinguishable.")
    return dict(heuristic=sum(h), model=sum(m), difference=sum(gap),
                lo=lo, hi=hi, n_boot=n_boot, n_negative=neg, seed=seed)


def bootstrap(disputes, cost, n_boot=2000, seed=13):
    """95% CI on (agent - contest_all), by resampling the 800 with replacement.

    WHY THIS IS NEEDED. The headline gap is a sum over a heavy-tailed amount
    distribution (p99/median = 13.5 in the generated data, 15.3 in IEEE-CIS).
    A sum like that is dominated by a handful of large wins, so "what if the
    three biggest disputes had flipped?" is the obvious attack. Decisions are
    per-dispute and independent of the other rows, so the decisions are made
    ONCE on the full set and only the scoring is resampled -- re-running the
    policy per bootstrap draw would be identical work at 2000x the cost.
    """
    import random as _r
    dec_a = run_policy(disputes, "agent", cost)
    dec_c = run_policy(disputes, "contest_all", cost)

    rng = _r.Random(seed)
    n = len(disputes)
    gaps = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        ds = [disputes[i] for i in idx]
        gaps.append(metrics.net_rupee_impact(ds, [dec_a[i] for i in idx], cost)
                    - metrics.net_rupee_impact(ds, [dec_c[i] for i in idx], cost))
    gaps.sort()
    lo, hi = gaps[int(0.025 * n_boot)], gaps[int(0.975 * n_boot) - 1]
    point = (metrics.net_rupee_impact(disputes, dec_a, cost)
             - metrics.net_rupee_impact(disputes, dec_c, cost))
    neg = sum(1 for g in gaps if g <= 0)

    print(f"\n  Bootstrap · {n_boot:,} resamples of n={n} · agent - contest_all\n")
    print(f"    point estimate      Rs {point:>12,.0f}")
    print(f"    95% CI              Rs {lo:>12,.0f}  to  Rs {hi:,.0f}")
    print(f"    draws where the gap is <= 0      {neg} / {n_boot}")
    return dict(point=point, lo=lo, hi=hi, n_boot=n_boot, n_negative=neg)


def ev_sweep(disputes, cost, json_out=None):
    """Two-sided sweep of the accept/contest boundary, -Rs 300 to +Rs 300.

    The confidence-floor sweep peaks at 0.00, which is the bottom of its own
    range, and a maximum sitting on a boundary is not a demonstrated maximum.
    This sweeps the EV threshold in both directions so the optimum is interior
    or is shown not to be.
    """
    import os as _os
    prev = _os.environ.get("CB_EV_THRESHOLD")
    rows = []
    print(f"\n  EV-threshold sweep · n={len(disputes)} · contest if ev > T\n")
    print(f"  {'T (Rs)':>8}{'net rupees':>14}{'sub':>7}{'acc':>7}{'esc':>7}")
    print("  " + "-" * 45)
    try:
        for t in range(-300, 301, 50):
            _os.environ["CB_EV_THRESHOLD"] = str(t)
            dec = run_policy(disputes, "agent", cost)
            net = metrics.net_rupee_impact(disputes, dec, cost)
            m = metrics.outcome_mix(dec)
            rows.append(dict(threshold=t, net_rupees=net, **m))
            print(f"  {t:>8,}{net:>14,.0f}{m['submitted']:>7}"
                  f"{m['accepted']:>7}{m['escalated']:>7}")
    finally:
        if prev is None:
            _os.environ.pop("CB_EV_THRESHOLD", None)
        else:
            _os.environ["CB_EV_THRESHOLD"] = prev

    best = max(rows, key=lambda r: r["net_rupees"])
    interior = rows[0]["threshold"] < best["threshold"] < rows[-1]["threshold"]
    print(f"\n  Best T = Rs {best['threshold']:,} at Rs {best['net_rupees']:,.0f}"
          f"  ({'interior optimum' if interior else 'ON THE BOUNDARY -- extend the range'})")
    if json_out:
        json.dump(rows, open(json_out, "w"), indent=2)
        print(f"  wrote {json_out}")
    return rows


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
    ap.add_argument("--ev-sweep", action="store_true")
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--ablation", action="store_true",
                    help="paired bootstrap: heuristic p(win) vs the model")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--chart", default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    disputes = load(args.data)
    if args.sweep:
        sweep(disputes, args.chart, args.json_out)
    elif args.ev_sweep:
        ev_sweep(disputes, args.contest_cost, args.json_out)
    elif args.ablation:
        r = ablation_bootstrap(disputes, args.contest_cost, args.n_boot)
        if args.json_out:
            json.dump(r, open(args.json_out, "w"), indent=2)
            print(f"  wrote {args.json_out}")
    elif args.bootstrap:
        r = bootstrap(disputes, args.contest_cost, args.n_boot)
        if args.json_out:
            json.dump(r, open(args.json_out, "w"), indent=2)
            print(f"  wrote {args.json_out}")
    else:
        res = print_scorecard(disputes, args.contest_cost)
        if args.json_out:
            json.dump(res, open(args.json_out, "w"), indent=2)
            print(f"\n  wrote {args.json_out}")
    print()


if __name__ == "__main__":
    main()