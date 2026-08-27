"""Distribution overlay: generated amounts against the real substrate.

The chart that answers "did you invent your data". Two panels:

  LEFT   Amount densities on a log axis. The generated distribution should sit
         on top of the real one in SHAPE while sitting elsewhere in SCALE --
         that difference is the point, not a flaw. IEEE-CIS is USD; Indian
         e-commerce order values are not US order values converted at an
         exchange rate. Sigma is fitted, the median is set. See
         generator/distributions.py.

  RIGHT  The same two distributions with the generated amounts divided by
         (median_generated / median_real), i.e. rescaled to a common median.
         If the shape was really transplanted, these two curves lie on top of
         each other. This is the honest version of the claim: not "our amounts
         are real" but "our amounts have the shape of real ones".

Reads data/ieee_amount_sample.json (20k real amounts, saved by
generator/profile_ieee.py) so the 683MB source CSV is not needed to redraw.
"""
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "generator"))

REAL = os.path.join(ROOT, "data", "ieee_amount_sample.json")
GEN = os.path.join(ROOT, "data", "train.jsonl")
OUT = os.path.join(ROOT, "data", "amount_overlay.png")

REAL_C = "#64748b"
GEN_C = "#2563eb"


def load():
    with open(REAL, encoding="utf-8") as fh:
        real = np.array(json.load(fh), dtype=float)
    gen = []
    with open(GEN, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                gen.append(json.loads(line)["amount"])
    return real[real > 0], np.array(gen, dtype=float)


def stats(x):
    return dict(
        n=len(x), median=np.median(x), mean=x.mean(),
        p90=np.percentile(x, 90), p99=np.percentile(x, 99),
        sigma=float(np.log(x).std(ddof=1)),
    )


def density(ax, x, colour, label, bins):
    ax.hist(np.log10(x), bins=bins, density=True, histtype="step",
            lw=2, color=colour, label=label)


def main():
    real, gen = load()
    rs, gs = stats(real), stats(gen)

    print(f"{'':12} {'n':>7} {'median':>10} {'mean':>10} {'p90':>10} "
          f"{'p99':>10} {'log sigma':>10}")
    for name, s in (("IEEE-CIS", rs), ("generated", gs)):
        print(f"{name:12} {s['n']:7,} {s['median']:10,.0f} {s['mean']:10,.0f} "
              f"{s['p90']:10,.0f} {s['p99']:10,.0f} {s['sigma']:10.4f}")

    scale = gs["median"] / rs["median"]
    print(f"\nmedian ratio (generated / real): {scale:.1f}x")
    print(f"sigma difference: {abs(gs['sigma'] - rs['sigma']):.4f}")
    print("\nRatios to median (the shape claim):")
    print(f"{'':12} {'p90/med':>9} {'p99/med':>9} {'mean/med':>9}")
    for name, s in (("IEEE-CIS", rs), ("generated", gs)):
        print(f"{name:12} {s['p90']/s['median']:9.2f} "
              f"{s['p99']/s['median']:9.2f} {s['mean']/s['median']:9.2f}")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6))
    bins = np.linspace(-0.5, 5.5, 70)

    density(ax1, real, REAL_C, f"IEEE-CIS, USD (n={rs['n']:,})", bins)
    density(ax1, gen, GEN_C, f"generated, INR (n={gs['n']:,})", bins)
    ax1.set_xlabel("amount (log₁₀)")
    ax1.set_ylabel("density")
    ax1.set_title("As-is: same shape, different scale")
    ax1.legend(frameon=False, fontsize=8)

    density(ax2, real, REAL_C, "IEEE-CIS", bins)
    density(ax2, gen / scale, GEN_C, "generated, rescaled", bins)
    ax2.set_xlabel("amount (log₁₀, common median)")
    ax2.set_ylabel("density")
    ax2.set_title(f"Rescaled to a common median\n"
                  f"σ real {rs['sigma']:.3f} vs generated {gs['sigma']:.3f}")
    ax2.legend(frameon=False, fontsize=8)

    fig.suptitle("Amount distribution: shape fitted to real data, scale set for India",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT, dpi=140)
    print(f"\nwrote {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()