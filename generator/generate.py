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

v2 (2026-08-27): rulebook corrected against Razorpay's published docs. The
evidence vocabulary is now DERIVED from the rulebook rather than hardcoded
here. v1 carried a hardcoded ALL_ARTIFACTS list that nothing read, so the
generator and the rulebook could drift apart silently -- and did. Deriving the
vocabulary means they cannot disagree, and validate_against_rulebook() fails
the run if the case taxonomy cites a code the rulebook does not define.

Usage:
  python -m generator.generate --profile train   --n 3000 --seed 11 --out data/train.jsonl
  python -m generator.generate --profile holdout --n 800  --seed 97 --out data/holdout.jsonl
"""

import argparse
import json
import random

from rulebook_loader import load_rulebook
from cases import cases_for, validate_against_rulebook, TIER_WEIGHTS
import distributions as dist


def evidence_vocabulary(rulebook):
    """Every artifact kind any code can ask for, derived from the rulebook.
    Single source of truth: if a kind is not in the rulebook, it cannot be
    generated, and vice versa."""
    kinds = set()
    for rc in rulebook["codes"].values():
        kinds.update(rc.get("required_evidence") or {})
    return sorted(kinds)


def _mk_artifact(kind, aid, api_field, rng, stale=False, dispute_day=20):
    """Build one evidence artifact with a concrete, checkable payload.

    api_field records which slot of Razorpay's contest API this artifact would
    be submitted under. Carrying it here means the assembled packet maps onto a
    real submission payload rather than an invented schema.
    """
    # A day offset; stale artifacts land AFTER the dispute (higher day).
    day = (rng.randint(dispute_day + 1, dispute_day + 5) if stale
           else rng.randint(0, dispute_day - 1))
    return {
        "artifact_id": aid,
        "kind": kind,
        "api_field": api_field,
        "created_day": day,
        "present": True,
        "value": f"{kind}:{rng.randint(1000, 9999)}",
    }


def build_evidence(case, required, rng, dispute_day):
    """Return (artifacts, present_kinds) honouring the case's evidence mode.

    `required` is the rulebook's {kind: api_field} mapping for this code.
    """
    mode = case["evidence"]
    kinds = list(required)
    artifacts = {}
    present = set()

    if mode == "full":
        keep = kinds
    elif mode == "partial":
        # drop one required artifact at random
        keep = list(kinds)
        if len(keep) > 1:
            keep.remove(rng.choice(keep))
    elif mode == "gap":
        # a required artifact never existed: drop ~half, always at least one
        keep = [a for a in kinds if rng.random() > 0.5]
        if set(keep) == set(kinds) and kinds:
            keep = keep[:-1]
    elif mode == "stale":
        keep = kinds  # present, but timestamped after the dispute
    else:
        keep = kinds

    for kind in keep:
        # Kind names are long and share prefixes now, so use a wider slug to
        # keep artifact ids readable and collision-free.
        aid = f"{kind[:12]}_{rng.randint(1000, 9999)}"
        artifacts[aid] = _mk_artifact(
            kind, aid, required[kind], rng,
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
    rc = rulebook["codes"][code]
    required = rc["required_evidence"]          # {kind: api_field}

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
        "category": rc.get("category"),
        "amount": amount,
        "hour": dist.draw_hour(rng),
        "day_of_week": dist.draw_day_of_week(rng),
        "address_match": address_match,
        "prior_disputes": prior_disputes,
        "new_device": new_device,
        "dispute_day": dispute_day,
        "required_evidence": sorted(required),
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

    # Hard gate: the taxonomy must not cite a code the rulebook lacks.
    validate_against_rulebook(rulebook)
    vocab = evidence_vocabulary(rulebook)
    print(f"[rulebook] {len(rulebook['codes'])} codes, "
          f"{len(vocab)} distinct evidence kinds")

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

    print(f"wrote {args.n} disputes -> {args.out} "
          f"(profile={args.profile}, seed={args.seed})")


if __name__ == "__main__":
    main()