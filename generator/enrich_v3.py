"""v3 overlay: merchants, deadlines, and response behaviour.

WHAT THIS ADDS. Three things the v1 generator has no notion of, each needed by
a capability the pipeline cannot currently express:

  merchant_id + traits   who the dispute belongs to, and how that merchant
                         behaves: how often they answer an evidence request,
                         and how complete their records tend to be
  deadline_day           the day the response window shuts, after which the
                         dispute is lost by default
  day_received           when the dispute landed, so "days remaining" is a
                         real quantity rather than a constant

WHY IT IS A SEPARATE FILE WITH A SEPARATE RNG, AND WHY THAT IS NOT FUSSINESS.
Every published figure in this project was measured on data produced by
generate.py. If new fields were drawn from the same random stream, every
subsequent draw would shift, and the amounts, tiers, evidence sets and outcomes
of every dispute would change. The scorecard, the calibration tables, the
bootstrap, the sweeps and the fault curves would all silently become numbers
about a different dataset while looking exactly the same.

So this module draws from `random.Random(seed ^ SALT)`, touched by nothing
else, and only ever ADDS keys. Run generate.py with the same seed before and
after and every existing field is byte-identical. That is asserted in
`verify_additive()` and checked in the test at the bottom of this file, because
"I was careful" is not a guarantee and this is exactly the kind of change that
looks harmless and moves everything.

WHAT IS INVENTED HERE, STATED PLAINLY. Response rates, evidence habits and
window lengths are assumptions, not measurements. No public dataset carries
them. They are structured to be *plausible and varied* rather than tuned:
merchants differ, so a policy that reasons about them has something to reason
about, but nothing here was fitted to make any downstream policy look good.
Anything measured on these fields is a statement about the mechanism, not about
Indian merchants, and belongs in the README under the same label as the rest of
the synthetic layer.
"""
from __future__ import annotations

import random

# XOR salt: derives an independent stream from the caller's seed, so v3 is
# reproducible from the same --seed without consuming from the v1 stream.
SALT = 0x5A17

# Merchant response window. SOURCED, not invented: Razorpay's own blog states
# "Banks generally provide a window of 3 Business days to represent the
# chargebacks" (razorpay.com/blog/chargebacks/), and its international-payments
# blog independently gives the same figure for cross-border disputes. This
# replaces an earlier version of this file that used invented per-network
# values (15-45 days) with no source; those were wrong by 5-15x.
#
# No network-specific split is published, so all networks use the same base.
# The 15-30 day figure elsewhere in the docs/README is the ISSUING BANK'S
# verdict window after representment -- a different, later stage. Do not
# conflate the two.
#
# "Business days" vs the calendar-day counters used elsewhere in this
# generator: we approximate 3 business days as 4 calendar days (accounts for
# one weekend) rather than modelling a weekday calendar, since nothing else in
# this pipeline tracks day-of-week for scheduling purposes.
BASE_WINDOW_DAYS = 4
WINDOW_DAYS = {
    "visa": BASE_WINDOW_DAYS, "mastercard": BASE_WINDOW_DAYS,
    "rupay": BASE_WINDOW_DAYS, "amex": BASE_WINDOW_DAYS,
    "upi": BASE_WINDOW_DAYS, "razorpay": BASE_WINDOW_DAYS,
}
DEFAULT_WINDOW = BASE_WINDOW_DAYS

# Merchant archetypes. The point is spread, not realism: a policy that decides
# whether to wait for a merchant needs merchants who differ in whether waiting
# is worth it.
ARCHETYPES = [
    # name,             response_rate, median_response_days, weight
    ("responsive",      0.85, 2,  0.25),
    ("slow_but_willing", 0.65, 9,  0.30),
    ("unreliable",      0.30, 6,  0.30),
    ("absent",          0.05, 20, 0.15),
]


def _merchant_pool(rng, n_merchants):
    """A fixed cast of merchants, so disputes repeat across the same ones.

    Continuity is the whole point: without repeat merchants there is no
    history to remember and merchant-level state is meaningless.
    """
    names = [a[0] for a in ARCHETYPES]
    weights = [a[3] for a in ARCHETYPES]
    pool = []
    for i in range(n_merchants):
        arch = rng.choices(names, weights=weights)[0]
        rate, days = next((a[1], a[2]) for a in ARCHETYPES if a[0] == arch)
        pool.append({
            "merchant_id": f"M{i:04d}",
            "archetype": arch,
            # Jitter around the archetype so merchants are not four values.
            "response_rate": round(min(0.98, max(0.02,
                             rate + rng.uniform(-0.12, 0.12))), 3),
            "median_response_days": max(1, int(days + rng.randint(-2, 3))),
        })
    return pool


def enrich(records, seed, n_merchants=120):
    """Add v3 fields in place and return the merchant pool.

    Merchants are assigned with a heavy-tailed draw rather than uniformly,
    because dispute volume concentrates: a few merchants generate many
    disputes and most generate one or two. A uniform assignment would give
    every merchant the same history depth and make merchant memory look more
    informative than it is.
    """
    rng = random.Random(seed ^ SALT)
    pool = _merchant_pool(rng, n_merchants)

    # Zipf-ish weights over the pool.
    weights = [1.0 / (i + 1) ** 0.8 for i in range(len(pool))]

    for r in records:
        m = rng.choices(pool, weights=weights)[0]
        base_window = WINDOW_DAYS.get((r.get("network") or "").lower(), DEFAULT_WINDOW)
        # +/-1 day jitter, floor 2: all networks now share one sourced base
        # (see comment above), so jitter is what gives the queue varying
        # urgency instead of a fixed per-network split.
        window = max(2, base_window + rng.choice([-1, 0, 0, 1]))

        # dispute_day is a constant 20 in v1. Received day is drawn relative to
        # it so "days remaining" varies across the queue; a queue where every
        # dispute has the same urgency cannot exercise a deadline policy.
        #
        # The offset MUST be tied to the window. An earlier version hardcoded
        # rng.randint(0, 12), which was calibrated for the old 15-45 day
        # windows; against the corrected 4-day window it put 69% of disputes
        # past their deadline before the agent ever saw them. Drawing from
        # (0, window - 1) keeps days-remaining in [1, window] by construction.
        received = r["dispute_day"] - rng.randint(0, window - 1)

        r["merchant_id"] = m["merchant_id"]
        r["day_received"] = received
        r["deadline_day"] = received + window
        r["window_days"] = window
        # Latent, like _true_p_win: the POLICY must not read these directly.
        # It may estimate them from observed history, which is the point of
        # merchant memory. Prefixed with _ and excluded by the leak guard.
        r["_merchant_archetype"] = m["archetype"]
        r["_true_response_rate"] = m["response_rate"]
        r["_true_response_days"] = m["median_response_days"]

    return pool


V3_FIELDS = ("merchant_id", "day_received", "deadline_day", "window_days",
             "_merchant_archetype", "_true_response_rate", "_true_response_days")


def verify_additive(before, after):
    """Assert that enrichment added keys and changed nothing else.

    Called by the test below and worth calling again after any edit to this
    file. A regression here does not raise anywhere else; it silently
    republishes every headline figure as a number about different data.
    """
    assert len(before) == len(after), "record count changed"
    for b, a in zip(before, after):
        for k, v in b.items():
            assert k in a, f"{k} disappeared"
            assert a[k] == v, f"{k} changed: {v!r} -> {a[k]!r}"
        extra = set(a) - set(b)
        assert extra == set(V3_FIELDS), f"unexpected new keys: {extra - set(V3_FIELDS)}"
    return True


if __name__ == "__main__":
    import copy
    import json
    import os
    import sys

    HERE = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "..", "data", "holdout.jsonl")
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 97

    recs = [json.loads(l) for l in open(path, encoding="utf-8")]
    before = copy.deepcopy(recs)
    pool = enrich(recs, seed)
    verify_additive(before, recs)

    import collections
    arch = collections.Counter(r["_merchant_archetype"] for r in recs)
    per = collections.Counter(r["merchant_id"] for r in recs)
    left = [r["deadline_day"] - r["dispute_day"] for r in recs]

    print(f"enriched {len(recs)} disputes over {len(pool)} merchants")
    print(f"  additive check: PASSED (every v1 field byte-identical)")
    print(f"  archetypes: {dict(arch)}")
    print(f"  disputes per merchant: max {max(per.values())}, "
          f"median {sorted(per.values())[len(per)//2]}, "
          f"merchants with >1 dispute {sum(1 for v in per.values() if v > 1)}")
    print(f"  days remaining at decision time: min {min(left)}, "
          f"max {max(left)}, median {sorted(left)[len(left)//2]}")