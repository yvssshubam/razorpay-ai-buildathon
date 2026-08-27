"""The case taxonomy: 24 patterns across five tiers.

This is the latent structure. The generator samples a CASE first, then builds a
transaction and evidence set to fit it. The MODEL never sees `tier` or `pattern_id`
-- it sees only reason code, amount, evidence-presence flags, address match,
device/history signals, and timestamps, and must infer the rest.

Fields per pattern:
  pattern_id : stable label, e.g. "A1"
  tier       : A..E
  reason_code: which rulebook code this dispute is filed under
  p_win      : (lo, hi) true win-probability band the outcome is drawn from
  evidence   : how the required artifacts behave -> drives Stage 4 and completeness
                 "full"     all required artifacts present and consistent
                 "partial"  some required artifacts missing
                 "gap"      a required artifact never existed
                 "stale"    artifacts exist but timestamped AFTER the dispute
  notes      : one-line human description
  holdout_only: if True, this pattern appears ONLY in the held-out set
"""

CASES = [
    # ---- Tier A: documentary wins (~80-95%) ----
    dict(pattern_id="A1", tier="A", reason_code="RZP01", p_win=(0.85, 0.95),
         evidence="full", notes="Duplicate processing: two auth records, one fulfilment"),
    dict(pattern_id="A2", tier="A", reason_code="13.6", p_win=(0.85, 0.95),
         evidence="full", notes="Credit not processed: refund issued before the dispute"),
    dict(pattern_id="A3", tier="A", reason_code="1062", p_win=(0.80, 0.92),
         evidence="full", notes="Incorrect amount: auth vs settlement mismatch on record"),
    dict(pattern_id="A4", tier="A", reason_code="RZP03", p_win=(0.80, 0.92),
         evidence="full", notes="Paid by other means: alternate payment proof exists"),
    dict(pattern_id="A5", tier="A", reason_code="13.2", p_win=(0.80, 0.90),
         evidence="full", notes="Cancelled recurring: no cancellation request on record"),

    # ---- Tier B: winnable with the right packet (~50-70%) ----
    dict(pattern_id="B1", tier="B", reason_code="13.1", p_win=(0.55, 0.70),
         evidence="full", notes="Non-delivery rebutted: signed POD + tracking + AVS"),
    dict(pattern_id="B2", tier="B", reason_code="10.4", p_win=(0.50, 0.68),
         evidence="full", notes="Digital goods: login/device/IP match prior undisputed use"),
    dict(pattern_id="B3", tier="B", reason_code="13.3", p_win=(0.50, 0.65),
         evidence="full", notes="Not-as-described: policy displayed and accepted at checkout"),
    dict(pattern_id="B4", tier="B", reason_code="4841", p_win=(0.52, 0.68),
         evidence="full", notes="Post-trial billing: terms-acceptance timestamp present"),

    # ---- Tier C: the ambiguous middle (~30-50%) ----
    dict(pattern_id="C1", tier="C", reason_code="13.1", p_win=(0.30, 0.50),
         evidence="full", notes="Delivered, but shipping address != billing address"),
    dict(pattern_id="C2", tier="C", reason_code="4853", p_win=(0.30, 0.48),
         evidence="partial", notes="Delivered with photo POD only, no signature"),
    dict(pattern_id="C3", tier="C", reason_code="13.6", p_win=(0.32, 0.50),
         evidence="partial", notes="Partial refund issued, full amount disputed"),
    dict(pattern_id="C4", tier="C", reason_code="4853", p_win=(0.30, 0.46),
         evidence="full", notes="Support ticket raised first and left unresolved"),
    dict(pattern_id="C5", tier="C", reason_code="13.1", p_win=(0.28, 0.45),
         evidence="stale", notes="Evidence exists but timestamped after the dispute",
         holdout_only=True),
    dict(pattern_id="C6", tier="C", reason_code="10.4", p_win=(0.30, 0.48),
         evidence="full", notes="Guest checkout, first-time buyer, high value, no history"),

    # ---- Tier D: very difficult (~10-25%) ----
    dict(pattern_id="D1", tier="D", reason_code="10.4", p_win=(0.08, 0.18),
         evidence="full", notes="True third-party fraud: AVS mismatch, new device"),
    dict(pattern_id="D2", tier="D", reason_code="1064", p_win=(0.10, 0.22),
         evidence="full", notes="Account takeover: every signal matches the real account"),
    dict(pattern_id="D3", tier="D", reason_code="13.1", p_win=(0.10, 0.20),
         evidence="partial", notes="Friendly fraud, own address, no signature captured"),
    dict(pattern_id="D4", tier="D", reason_code="4853", p_win=(0.10, 0.22),
         evidence="full", notes="Authorised-user / family misuse: merchant did nothing wrong"),

    # ---- Tier E: structurally unwinnable (<10%) -> accept immediately ----
    dict(pattern_id="E1", tier="E", reason_code="1064", p_win=(0.02, 0.08),
         evidence="gap", notes="Authentication non-compliant or bypassed"),
    dict(pattern_id="E2", tier="E", reason_code="13.1", p_win=(0.02, 0.08),
         evidence="gap", notes="Evidence gap: required artifact never existed"),
    dict(pattern_id="E3", tier="E", reason_code="13.3", p_win=(0.01, 0.06),
         evidence="gap", notes="Window expired before response could be prepared"),
    dict(pattern_id="E4", tier="E", reason_code="RZP01", p_win=(0.02, 0.07),
         evidence="gap", notes="Double-dip: already refunded and also charged back"),
    dict(pattern_id="E5", tier="E", reason_code="13.1", p_win=(0.02, 0.08),
         evidence="gap", notes="Confirmed RTO / genuine non-delivery"),
]

# Sampling weights per tier (share of disputes). Tier C is the largest single
# tier, per the brief. These are the training mix; holdout shifts them (see generate.py).
TIER_WEIGHTS = {"A": 0.20, "B": 0.15, "C": 0.33, "D": 0.17, "E": 0.15}


def cases_for(profile):
    """Return the case list for a data profile. holdout_only patterns are
    excluded from training and included in holdout."""
    if profile == "train":
        return [c for c in CASES if not c.get("holdout_only")]
    return list(CASES)  # holdout sees everything, including the unseen pattern


def by_tier(cases):
    out = {}
    for c in cases:
        out.setdefault(c["tier"], []).append(c)
    return out
