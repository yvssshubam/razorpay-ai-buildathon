"""Feature extraction for the Stage 1 triage classifier.

ONE extractor, used by both training and inference. If they ever diverge you get
train/serve skew: a model that scores well in the notebook and badly in the
harness.

LEAK GUARD: the generator writes latent fields into each record (_tier,
_pattern_id, _true_p_win). Rule 2 of the data design says the model must infer
the tier from observable features, not read it off a column. assert_no_leaks()
fails loudly if one is ever touched, so the claim is enforced by code rather
than by good intentions.
"""
import math

LEAK_FIELDS = ("_tier", "_pattern_id", "_true_p_win", "_case_type")

NUMERIC = [
    "log_amount",
    "completeness",
    "n_required",
    "n_present",
    "n_missing",
    "n_artifacts",
    "frac_stale",
    "dispute_age_days",
    "prior_disputes",
    "address_match",
    "new_device",
    "packet_blocked",
]


def assert_no_leaks(names):
    bad = [n for n in names if any(n.startswith(f) for f in LEAK_FIELDS)]
    if bad:
        raise ValueError(f"leaked latent field(s) into features: {bad}")


def _artifacts(d):
    a = d.get("artifacts") or {}
    if isinstance(a, list):
        a = {x.get("id", str(i)): x for i, x in enumerate(a)}
    return a


def _packet_blocked(d):
    """Mirrors eval/baselines.py::_build_packet. A claim is supported iff its
    artifact exists AND predates the dispute. Duplicated deliberately so this
    module has no import dependency on the eval package."""
    arts = _artifacts(d)
    dday = d.get("dispute_day", 0)
    kept = {a.get("kind") for a in arts.values()
            if a.get("present") and a.get("created_day", 0) < dday}
    return not set(d.get("required_evidence") or []).issubset(kept)


def base_features(d):
    req = set(d.get("required_evidence") or [])
    pres = set(d.get("present_evidence") or [])
    arts = _artifacts(d)
    dday = d.get("dispute_day", 0)
    txn_day = d.get("transaction_day", d.get("txn_day", dday))

    n_art = len(arts)
    stale = sum(1 for a in arts.values()
                if a.get("present") and a.get("created_day", 0) >= dday)

    amount = float(d.get("amount") or 0.0)

    return {
        "log_amount": math.log1p(max(amount, 0.0)),
        "completeness": len(pres & req) / max(len(req), 1),
        "n_required": float(len(req)),
        "n_present": float(len(pres)),
        "n_missing": float(len(req - pres)),
        "n_artifacts": float(n_art),
        "frac_stale": stale / max(n_art, 1),
        "dispute_age_days": float(dday - txn_day),
        "prior_disputes": float(d.get("prior_disputes") or 0),
        "address_match": 1.0 if d.get("address_match") else 0.0,
        "new_device": 1.0 if d.get("new_device") else 0.0,
        "packet_blocked": 1.0 if _packet_blocked(d) else 0.0,
    }


def build_vocab(records):
    return sorted({str(r.get("reason_code")) for r in records})


def feature_names(vocab):
    names = NUMERIC + [f"rc={c}" for c in vocab]
    assert_no_leaks(names)
    return names


def vectorise(d, vocab):
    b = base_features(d)
    row = [b[k] for k in NUMERIC]
    rc = str(d.get("reason_code"))
    row += [1.0 if rc == c else 0.0 for c in vocab]
    return row