"""Transaction substrate and cost model for the dispute generator.

SUBSTRATE: fitted to IEEE-CIS Fraud Detection (Kaggle/Vesta), 590,540 real
e-commerce transactions. See generator/profile_ieee.py and
rulebook/ieee_profile.json.

COST MODEL: four constants, none of them measured. See the block at the bottom.
"""
import json
import os

# ---------------------------------------------------------------------------
# Real-data profile: hour-of-day and day-of-week cycles.
#
# TransactionDT in the source is seconds from an unspecified origin, so these
# hour indices are offsets from an unknown reference, not clock hours. The
# SHAPE of the daily cycle is real (~17x peak to trough); its phase is
# arbitrary. We adopt the shape as-is and say so rather than rotating it to
# look like clock time.
# ---------------------------------------------------------------------------

_PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "rulebook", "ieee_profile.json")

with open(_PROFILE_PATH, encoding="utf-8") as _fh:
    _P = json.load(_fh)

HOUR_WEIGHTS = _P["hour_weights"]      # fitted: 24 weights
DOW_WEIGHTS = _P["day_of_week_weights"]  # fitted: 7 weights

_HOURS = list(range(24))
_DAYS = list(range(7))


# ---------------------------------------------------------------------------
# AMOUNTS: empirical resampling, not a parametric fit.
#
# The first version fitted a log-normal to sigma=0.954 and drew from it. The
# overlay chart showed why that was not good enough: real p99/median is 15.28,
# the fitted log-normal gave 8.71. IEEE-CIS has a skew of 14.37 and a maximum
# at 464x the median -- no log-normal reproduces that. Real amounts are also
# not smooth: they cluster at price points ($30, $50, $100), which a parametric
# draw cannot produce either.
#
# So we resample real amounts directly and rescale. The generated distribution
# then inherits the true shape exactly -- the tail, the skew, and the price
# clustering. The only thing we choose is the median.
#
# Jitter of +/-3% is applied so that 3,000 draws from a 20,000-sample pool do
# not produce visible duplicate amounts. Small enough not to disturb the
# distribution, large enough to avoid an artificial-looking dataset.
# ---------------------------------------------------------------------------

_SAMPLE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "ieee_amount_sample.json")

with open(_SAMPLE_PATH, encoding="utf-8") as _fh:
    _REAL_AMOUNTS = sorted(float(v) for v in json.load(_fh) if float(v) > 0)

_REAL_MEDIAN = _REAL_AMOUNTS[len(_REAL_AMOUNTS) // 2]

# Median order value in INR. SET, not fitted, and swept in agent/cost_sweep.py
# so the headline does not depend on this choice.
#
# Chosen at Rs 1,500 between two published figures: Indian e-commerce AOV of
# US$59 (ECDB, 2024, ~Rs 5,000) and quick-commerce AOV of Rs 500 (Economic
# Times). Both are MEANS; the empirical mean/median ratio in IEEE-CIS is 1.94,
# implying medians of ~Rs 2,580 and ~Rs 258 respectively. Rs 1,500 sits between
# them and reflects Razorpay's base being dominated by small e-commerce
# merchants rather than the big-ticket categories that pull the national AOV up.
AMOUNT_MEDIAN = 1500.0


def draw_amount(rng):
    """Amount in INR: a real transaction amount, rescaled.

    Scale is computed per call so that sweeping AMOUNT_MEDIAN at runtime takes
    effect. Clipped at Rs 50 at the bottom only -- the top is left uncapped,
    because the extreme tail is exactly what a parametric fit was losing and it
    is what makes expected-value triage matter.
    """
    scale = AMOUNT_MEDIAN / _REAL_MEDIAN
    v = rng.choice(_REAL_AMOUNTS) * scale
    v *= 1.0 + rng.uniform(-0.03, 0.03)
    return round(max(v, 50.0), 2)


def draw_hour(rng):
    """Hour index, weighted by the real daily cycle. Index, not clock time."""
    return rng.choices(_HOURS, weights=HOUR_WEIGHTS)[0]


def draw_day_of_week(rng):
    """Day index, weighted by the real weekly cycle."""
    return rng.choices(_DAYS, weights=DOW_WEIGHTS)[0]


# ---------------------------------------------------------------------------
# Cost model. ALL FOUR ARE ASSUMPTIONS -- no public figure exists for any of
# them in an Indian context. Swept in agent/cost_sweep.py; see
# data/cost_sweep_results.txt.
#
# An escalated (verifier-blocked) case is reviewed by a person who can repair
# the packet but cannot change the underlying facts. Conservative by design:
# the human gets no skill bonus, only the ability to unblock.
# ---------------------------------------------------------------------------
CONTEST_COST = 250.0          # INR to assemble and submit one packet
HUMAN_REVIEW_COST = 800.0     # INR per escalated case, analyst time
NET_RECOVERY_FRACTION = 0.85  # share of the disputed amount recovered on a win
HUMAN_RESOLVE_RATE = 0.80     # share of escalated cases a human can fix