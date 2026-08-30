"""Two charts from llm_packet_eval.py output.

LEFT   what the drafter produced vs what reached the network. The gap is the
       verifier. The zero line is the claim being made.
RIGHT  block attribution under triage vs contest-everything. Shows that triage
       cuts the structural block floor as a side effect of declining the cases
       whose evidence was never there.

    python eval/verifier_chart.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(REPO, "data")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, ACCENT, BAD, GOOD, WARN = "#101828", "#4338ca", "#a4231a", "#0d6b4f", "#a35408"


def load(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        sys.exit(f"missing {path}. Run eval/llm_packet_eval.py first.")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    agent = load("llm_packet_eval.json")
    allp = load("llm_packet_eval_contestall.json")

    x = [r["fault_rate"] for r in agent]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    # ---- left: drafted vs shipped -------------------------------------
    ax1.plot(x, [r["hallucination_rate"] for r in agent], "o-", color=BAD,
             lw=1.8, ms=5, label="fabricated by the drafter")
    ax1.plot(x, [r["fabrications_submitted"] for r in agent], "s-", color=GOOD,
             lw=2.2, ms=5, label="reaching a submitted packet")
    ax1.plot(x, x, "--", color="#98a2b3", lw=1, label="injected fault rate")
    ax1.set_xlabel("injected fault rate")
    ax1.set_ylabel("rate")
    ax1.set_title("The verifier is a gate, not a filter", fontsize=11, color=INK)
    ax1.set_ylim(-0.02, 0.5)
    ax1.legend(frameon=False, fontsize=8.5, loc="upper left")
    ax1.spines[["top", "right"]].set_visible(False)
    ax1.annotate("zero, at every fault rate", xy=(0.20, 0), xytext=(0.16, 0.10),
                 fontsize=8.5, color=GOOD,
                 arrowprops=dict(arrowstyle="->", color=GOOD, lw=1))

    # ---- right: block composition under triage ------------------------
    # Stacked, not grouped. Only the fault_rate=0 column is a clean structural
    # reading: once the drafter also drops a citable kind, that packet's block
    # is attributed to the model, so the structural band shrinks by
    # reclassification rather than by improvement. Stacking makes the total
    # block rate the visible quantity and the composition the secondary one,
    # which is the honest reading.
    struct = [r["structural_block_rate"] for r in agent]
    model = [r["model_block_rate"] for r in agent]
    ax2.bar(x, struct, width=0.03, color=WARN, label="evidence was never there")
    ax2.bar(x, model, width=0.03, bottom=struct, color=BAD,
            label="drafter lost a citable artifact")
    ax2.axhline(allp[0]["structural_block_rate"], ls="--", lw=1.2, color="#98a2b3")
    ax2.text(0.20, allp[0]["structural_block_rate"] + 0.025,
             f"contest-everything structural floor "
             f"({allp[0]['structural_block_rate']:.0%})",
             fontsize=8, color="#667085", ha="center",
             bbox=dict(fc="white", ec="none", pad=1.5))
    ax2.annotate(f"triage floor {agent[0]['structural_block_rate']:.1%}",
                 xy=(0.012, agent[0]["structural_block_rate"]), xytext=(0.09, 0.20),
                 fontsize=8.5, color=WARN,
                 arrowprops=dict(arrowstyle="->", color=WARN, lw=1))
    ax2.set_xlabel("injected fault rate")
    ax2.set_ylabel("share of contested packets blocked")
    ax2.set_title("Why packets get blocked", fontsize=11, color=INK)
    ax2.legend(frameon=False, fontsize=8.5, loc="lower right")
    ax2.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    out = os.path.join(DATA, "verifier_gate.png")
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()