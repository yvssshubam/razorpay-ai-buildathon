"""Statistical shape for synthetic transactions.

In the real build these constants come from profiling IEEE-CIS (amount skew,
hour-of-day, day-of-week). Here they are seeded with reasonable values and a
TODO to overwrite from the real dataset on day 1. The overlay chart in the
README compares THIS distribution against the real one -- that chart is what
pre-empts the "you invented your data" objection, so keep these honest.

Amounts are right-skewed: most orders small, a long tail of large ones. A
lognormal captures that. Contest cost is a flat per-dispute figure -- the single
most important business constant in the whole system. It is an ASSUMPTION;
label it as one and run a sensitivity sweep.
"""

import math
import random

# Amount distribution (INR). Lognormal: median ~ exp(MU).
# TODO(day1): refit MU, SIGMA to the real dataset's amount column (log-scaled).
AMOUNT_MU = 7.4        # exp(7.4) ~ 1636 INR median
AMOUNT_SIGMA = 1.05
AMOUNT_MIN = 50.0
AMOUNT_MAX = 500000.0

# Cost of contesting one dispute (INR). ASSUMPTION -- no public India figure.
# Every expected-value decision pivots on this. Sweep it in eval.
CONTEST_COST = 250.0

# Fraction of the contested amount that is recoverable on a win, net of
# non-refundable fees. A "win" is NOT the full face value.
NET_RECOVERY_FRACTION = 0.85


def draw_amount(rng: random.Random) -> float:
    a = math.exp(rng.gauss(AMOUNT_MU, AMOUNT_SIGMA))
    return round(min(max(a, AMOUNT_MIN), AMOUNT_MAX), 2)


def draw_hour(rng: random.Random) -> int:
    # Bimodal: lunchtime and evening peaks, quiet overnight.
    peak = rng.choice([13, 13, 21, 21, 21, 10, 16, 19, 20, 22])
    h = int(round(rng.gauss(peak, 2))) % 24
    return h


def draw_day_of_week(rng: random.Random) -> int:
    # Slight weekend lift.
    return rng.choices(range(7), weights=[1, 1, 1, 1, 1.2, 1.4, 1.3])[0]


# ---------------------------------------------------------------------------
# Human queue economics. BOTH ARE ASSUMPTIONS -- no public figure exists.
# An escalated (verifier-blocked) case is reviewed by a person who can repair
# the packet but cannot change the underlying facts. Conservative by design:
# the human gets no skill bonus, only the ability to unblock.
HUMAN_REVIEW_COST = 800.0   # INR per escalated case, analyst time
HUMAN_RESOLVE_RATE = 0.80   # fraction of escalated cases a human can actually fix
