"""Do the decision path and the scoring path agree on the cost constants?

generator/distributions.py drives baselines (the DECISION).
eval/distributions_ref.py drives metrics (the SCORING).

If these two ever disagree, the agent decides using one set of costs and gets
scored using another, and every rupee figure is internally inconsistent.
"""
import sys

sys.path.insert(0, "eval")
sys.path.insert(0, "generator")

import distributions as gen
import distributions_ref as ref

KEYS = ("CONTEST_COST", "HUMAN_REVIEW_COST",
        "NET_RECOVERY_FRACTION", "HUMAN_RESOLVE_RATE")

bad = []
for k in KEYS:
    g = getattr(gen, k, None)
    r = getattr(ref, k, None)
    same = g == r
    if not same:
        bad.append(k)
    print(f"{k:24} gen={g!r:>8}  ref={r!r:>8}  {'' if same else '<-- DIFFERS'}")

print()
print("consistent" if not bad else f"MISMATCH on: {', '.join(bad)}")