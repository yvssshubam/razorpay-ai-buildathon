"""Transaction substrate and cost model for the dispute generator.

SUBSTRATE: resampled from IEEE-CIS Fraud Detection (Kaggle/Vesta), 590,540 real
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

HOUR_WEIGHTS = _P["hour_weights"]         # fitted: 24 weights
DOW_WEIGHTS = _P["day_of_week_weights"]   # fitted: 7 weights

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
# inherits the true shape -- the tail, the skew, and the price clustering.
# The only thing we choose is the median.
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

# Median order value in INR. SET, not fitted.
#
# NOT SWEPT. Unlike the four cost constants below, varying this requires
# regenerating the datasets and retraining, not just rescoring, so it is not in
# agent/cost_sweep.py. It is disclosed as a stated assumption in the README
# instead. (An earlier version of this comment claimed it was swept. It was
# not.)
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

    Scale is computed per call so that changing AMOUNT_MEDIAN at runtime takes
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
# COST MODEL
#
# THREE of the four are assumptions with no public Indian figure. The fourth,
# NET_RECOVERY_FRACTION, is SOURCED from Razorpay's published platform-fee
# schedule -- an earlier version of this header said all four were invented,
# which was true when it was written and is no longer.
#
# All four are still swept one at a time in agent/cost_sweep.py; see
# data/cost_sweep_results.txt for the ranges over which the headline holds. A
# sourced point estimate is not the same as a measured distribution, so the
# sweep stays.
#
# WHAT EACH ONE COVERS -- stated because the two money terms could otherwise be
# read as overlapping, and double-counting a fee would bias every decision:
#
#   CONTEST_COST           Merchant-side effort only: locating the artifacts
#                          across the order, delivery, support and payment
#                          systems, assembling the packet, and submitting it.
#                          It does NOT include any network or acquirer fee.
#
#   NET_RECOVERY_FRACTION  The share of the disputed amount that comes back
#                          GIVEN a win. SOURCED, unlike the other three, and
#                          VARIES BY INSTRUMENT -- read net_recovery() below
#                          rather than this scalar. Disjoint from CONTEST_COST.
#
#                          A previous version used 0.85 (a 15% haircut). That
#                          was invented and wrong by ~4-6x. Razorpay's
#                          published platform fee is 2% + 18% GST for standard
#                          domestic instruments (Credit/Debit Cards, UPI,
#                          Netbanking, Wallets) = 2.36% effective, and 3% + GST
#                          for premium instruments (Amex/Diners, Corporate
#                          Cards, EMI, Pay Later) and international cards =
#                          3.54% effective. GST applies to the fee, not the
#                          transaction amount. The fee is a single blended
#                          charge covering processing AND technology
#                          (reconciliation, routing, fraud tooling), which is
#                          why it is modelled as one fraction per instrument
#                          rather than separable components.
#
#                          NOTE ON UPI: UPI carries 0% interchange MDR by
#                          government mandate, but Razorpay still charges its
#                          platform fee on UPI at the standard domestic rate.
#                          UPI therefore sits at 0.9764, NOT at 1.0. An earlier
#                          draft of this model put it at 1.0 and was wrong.
#
#                          MODELLING NOTE -- THE REMAINING GAP. This captures
#                          the platform fee only. It does NOT capture
#                          Razorpay's separate FLAT per-dispute fee (~Rs
#                          200-750) or representment fee (~Rs 750-1,500), which
#                          do not scale with amount and have no line item in
#                          this model. At the Rs 1,500 median dispute that
#                          missing flat fee EXCEEDS the proportional fee
#                          captured here, so the cost of contesting small
#                          disputes is still understated. There is also a
#                          category question: the platform fee is charged at
#                          the time of sale and is sunk whether or not a
#                          dispute occurs, so treating it as a haircut on
#                          recovery is a simplification. Both are stated in the
#                          README under "Data and its limits" rather than
#                          modelled, because adding a flat fee term changes the
#                          EV rule's shape and there is no published Razorpay
#                          figure to pin it to.
#
#   HUMAN_REVIEW_COST      Analyst time on a packet the verifier blocked. Paid
#                          ON TOP of CONTEST_COST, because the packet was
#                          already assembled before it was found to be short.
#                          The single definition of that sum lives in
#                          eval/metrics.py::escalation_cost -- import it rather
#                          than re-adding the two terms.
#
#   HUMAN_RESOLVE_RATE     Share of blocked packets a person can complete. The
#                          human can repair the packet; they cannot change the
#                          underlying facts, so they get no skill bonus on the
#                          win rate. Conservative by design.
# ---------------------------------------------------------------------------
CONTEST_COST = 250.0          # INR, merchant effort to assemble and submit
HUMAN_REVIEW_COST = 800.0     # INR, analyst time on an escalated packet
NET_RECOVERY_FRACTION = 0.9764  # BASE: standard domestic, 2% + 18% GST = 2.36%
HUMAN_RESOLVE_RATE = 0.80     # share of escalated packets a human can fix

# Instruments charged at the premium 3% + GST rate (= 3.54% effective) rather
# than the standard domestic 2% + GST. Of the six networks this generator
# emits, only Amex falls here: Razorpay groups Amex/Diners with Corporate
# Cards, EMI and Pay Later at the premium rate. Visa, Mastercard, RuPay, UPI
# and the RZP codes are standard domestic.
#
# International cards also sit at 3% + GST, but this dataset carries no
# domestic/international flag, so cross-border volume on Visa/Mastercard is
# priced at the domestic rate here. That understates the fee on an unknown
# share of disputes -- stated in the README, not silently absorbed.
PREMIUM_NETWORKS = frozenset({"amex"})

# Expressed as a DELTA off the base, not as absolute values, so that
# agent/cost_sweep.py patching NET_RECOVERY_FRACTION still moves every
# instrument. Hardcoding absolutes here would make the sweep patch the scalar
# while the call sites read the dict -- the exact silent-no-op failure the
# sweep's own "NOT SWEPT" detector exists to catch.
PREMIUM_DELTA = 0.9646 - 0.9764   # -0.0118


def net_recovery(network=None):
    """Share of the disputed amount recovered on a win, for this instrument.

    THE SINGLE DEFINITION. Call this rather than reading
    NET_RECOVERY_FRACTION directly, so that the decision path and the scoring
    path cannot drift apart on instrument handling.

    Unknown or missing network falls back to the standard domestic base, which
    is the conservative direction: it under-charges the fee rather than
    over-charging it, so a mislabelled dispute looks slightly MORE contestable
    rather than less. Failing the other way would silently suppress contests.
    """
    base = NET_RECOVERY_FRACTION
    if (network or "").strip().lower() in PREMIUM_NETWORKS:
        return base + PREMIUM_DELTA
    return base