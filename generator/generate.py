"""Frozen dispute generator.

Order of operations (this order matters):
  1. sample a CASE (latent tier + pattern) using tier weights
  2. build a transaction to fit it (amount, time, address, device, history)
  3. build the evidence set according to the case's evidence behaviour
  4. draw the OUTCOME (won/lost) from the case's true win-probability band

The model later sees everything EXCEPT tier, pattern_id, and p_win. It must
recover the decision from observable features alone.

FREEZE DISCIPLINE: commit this file, then `git tag generator-frozen-v1` with a
dated message, and only then write agent/. The public tag makes the ordering
provable and pre-empts "the data was reverse-engineered from the model".

Usage:
  python -m generator.generate --profile train   --n 3000 --seed 11 --out data/train.jsonl
  python -m generator.generate --profile holdout --n 800  --seed 97 --out data/holdout.jsonl
"""

import argparse
import json
import random

from rulebook_loader import load_rulebook
from cases import cases_for, TIER_WEIGHTS
import distributions as dist

# Every artifact type the rulebook can ask for. The generator populates a subset.
ALL_ARTIFACTS = [
    "delivery_confirmation", "tracking_info", "signed_pod", "avs_result",
    "cancellation_policy", "no_cancellation_proof", "usage_logs", "terms_of_service",
    "item_description", "policy_displayed", "terms_acceptance", "refund_record",
    "refund_timestamp", "communication_log", "device_fingerprint", "ip_record",
    "prior_undisputed_history", "auth_record", "settlement_record", "duplicate_check",
    "alternate_payment_proof",
]


def _mk_artifact(kind, aid, rng, stale=False, dispute_day=20):
    """Build one evidence artifact with a concrete, checkable payload."""
    # A day offset; stale artifacts land AFTER the dispute (higher day).
    day = rng.randint(dispute_day + 1, dispute_day + 5) if stale else rng.randint(0, dispute_day - 1)
    return {
        "artifact_id": aid,
        "kind": kind,
        "created_day": day,
        # a couple of checkable fields the verifier can read
        "present": True,
        "value": f"{kind}:{rng.randint(1000, 9999)}",
    }


def build_evidence(case, required, rng, dispute_day):
    """Return (artifacts, present_kinds) honouring the case's evidence mode."""
    mode = case["evidence"]
    artifacts = {}
    present = set()

    if mode == "full":
        keep = required
    elif mode == "partial":
        # drop one required artifact at random
        keep = list(required)
        if len(keep) > 1:
            keep.remove(rng.choice(keep))
    elif mode == "gap":
        # a required artifact never existed: drop ~half, always missing at least one
        keep = [a for a in required if rng.random() > 0.5]
        if set(keep) == set(required) and required:
            keep = keep[:-1]
    elif mode == "stale":
        keep = required  # present, but timestamped after the dispute
    else:
        keep = required

    for i, kind in enumerate(keep):
        aid = f"{kind[:4]}_{rng.randint(1000, 9999)}"
        artifacts[aid] = _mk_artifact(
            kind, aid, rng,
            stale=(mode == "stale"),
            dispute_day=dispute_day,
        )
        present.add(kind)

    return artifacts, present


def sample_case(rng, cases):
    tiers = list(TIER_WEIGHTS.keys())
    weights = [TIER_WEIGHTS[t] for t in tiers]
    tier = rng.choices(tiers, weights=weights)[0]
    pool = [c for c in cases if c["tier"] == tier]
    return rng.choice(pool)


def make_dispute(idx, rng, cases, rulebook):
    case = sample_case(rng, cases)
    code = case["reason_code"]
    rc = rulebook["reason_codes"][code]
    required = rc["evidence"]

    amount = dist.draw_amount(rng)
    dispute_day = 20
    artifacts, present = build_evidence(case, required, rng, dispute_day)

    # observable signals (the model may use these)
    address_match = case["tier"] in ("A", "B") or rng.random() > 0.4
    if case["pattern_id"] in ("C1", "D1"):
        address_match = False
    prior_disputes = 0
    if case["tier"] in ("A", "B"):
        prior_disputes = rng.choices([0, 0, 1], weights=[6, 3, 1])[0]
    elif case["tier"] == "D":
        prior_disputes = rng.choices([0, 1, 2, 3], weights=[3, 3, 2, 2])[0]
    new_device = case["pattern_id"] in ("D1", "D2", "C6") or rng.random() > 0.8

    # outcome drawn from the TRUE band; this is the ground-truth label
    lo, hi = case["p_win"]
    true_p = rng.uniform(lo, hi)
    won = rng.random() < true_p

    return {
        "dispute_id": f"D{idx:05d}",
        "reason_code": code,
        "network": rc["network"],
        "amount": amount,
        "hour": dist.draw_hour(rng),
        "day_of_week": dist.draw_day_of_week(rng),
        "address_match": address_match,
        "prior_disputes": prior_disputes,
        "new_device": new_device,
        "dispute_day": dispute_day,
        "required_evidence": required,
        "present_evidence": sorted(present),
        "artifacts": artifacts,
        # ---- labels / latent: NOT to be fed to the model as features ----
        "_tier": case["tier"],
        "_pattern_id": case["pattern_id"],
        "_true_p_win": round(true_p, 4),
        "label_won": won,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["train", "holdout"], required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    rulebook = load_rulebook()
    cases = cases_for(args.profile)

    # holdout shifts the mix slightly so it measures generalisation, not memory
    if args.profile == "holdout":
        # nudge weights; keeps the unseen pattern (C5) reachable
        for t in TIER_WEIGHTS:
            TIER_WEIGHTS[t] = max(0.05, TIER_WEIGHTS[t] + rng.uniform(-0.03, 0.03))

    with open(args.out, "w") as f:
        for i in range(args.n):
            d = make_dispute(i, rng, cases, rulebook)
            f.write(json.dumps(d) + "\n")

    print(f"wrote {args.n} disputes -> {args.out} (profile={args.profile}, seed={args.seed})")


if __name__ == "__main__":
    main()
