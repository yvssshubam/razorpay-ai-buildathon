"""Transaction substrate and cost model for the dispute generator.

SUBSTRATE: fitted to IEEE-CIS Fraud Detection (Kaggle/Vesta), 590,540 real
e-commerce transactions. See generator/profile_ieee.py and
rulebook/ieee_profile.json.

COST MODEL: four constants, none of them measured. See the block at the bottom.
"""
import json
import os
_PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "rulebook", "ieee_profile.json")

with open(_PROFILE_PATH, encoding="utf-8") as _fh:
    _P = json.load(_fh)

HOUR_WEIGHTS = _P["hour_weights"]      # fitted: 24 weights
DOW_WEIGHTS = _P["day_of_week_weights"]  # fitted: 7 weights

_HOURS = list(range(24))
_DAYS = list(range(7))

_SAMPLE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "ieee_amount_sample.json")

with open(_SAMPLE_PATH, encoding="utf-8") as _fh:
    _REAL_AMOUNTS = sorted(float(v) for v in json.load(_fh) if float(v) > 0)

_REAL_MEDIAN = _REAL_AMOUNTS[len(_REAL_AMOUNTS) // 2]

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