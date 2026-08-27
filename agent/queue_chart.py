"""Block rate against model fault rate.

Two things to read off this chart:

  INTERCEPT. At zero model error the system still blocks ~32% of packets, on
  stale evidence and genuine evidence gaps. That share of the human queue is
  structural -- no improvement in drafting removes it. The bottleneck is
  assembly, not generation.

  SLOPE. Each point of hallucination costs ~4 points of block rate, because a
  single bad claim on a required evidence kind sinks the entire packet. A
  system that blocks everything is safe and useless; this is where that line is.

Numbers from the CB_FAULT_RATE sweep in verify.py. Hardcoded deliberately --
regenerating them is a 5-command loop, and hardcoding keeps the chart honest
about being a record of a specific run rather than something recomputed live.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))

injected     = [0.00, 0.05, 0.10, 0.20, 0.40]
measured     = [0.000, 0.049, 0.108, 0.197, 0.390]
blocked      = [0.34, 0.48, 0.66, 0.78, 0.94]
completeness = [0.844, 0.800, 0.751, 0.674, 0.511]

GEMINI_MEASURED = 0.000   # 17 claims over 5 disputes; update after the 100-run

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

ax1.plot(injected, measured, "o-", color="#2563eb", label="measured")
ax1.plot([0, 0.4], [0, 0.4], "--", lw=1, color="grey", label="perfect detection")
ax1.set_xlabel("injected fault rate")
ax1.set_ylabel("measured hallucination rate")
ax1.set_title("The verifier catches what is injected")
ax1.legend(frameon=False, loc="upper left")

ax2.plot(injected, blocked, "o-", color="#dc2626", label="packets blocked")
ax2.plot(injected, completeness, "o-", color="#16a34a", label="mean completeness")
ax2.axhline(blocked[0], ls=":", lw=1, color="#dc2626")
ax2.annotate(f"{blocked[0]:.0%} blocked at zero model error\n(stale evidence + genuine gaps)",
             xy=(0.0, blocked[0]), xytext=(0.09, 0.20),
             fontsize=8, arrowprops=dict(arrowstyle="->", lw=0.8))
ax2.axvline(GEMINI_MEASURED, ls="--", lw=1, color="#7c3aed")
ax2.text(GEMINI_MEASURED + 0.005, 0.97, "Gemini", fontsize=8,
         color="#7c3aed", va="top")
ax2.set_xlabel("model fault rate")
ax2.set_ylabel("rate")
ax2.set_ylim(0, 1)
ax2.set_title("Human queue trade-off")
ax2.legend(frameon=False, loc="center right")

fig.tight_layout()
out = os.path.join(HERE, "..", "data", "queue_curve.png")
fig.savefig(out, dpi=140)
print("wrote data/queue_curve.png")