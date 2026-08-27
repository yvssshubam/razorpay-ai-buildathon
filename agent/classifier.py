"""Stage 1: calibrated win-probability model.

Trains on data/train.jsonl ONLY. Never opens holdout.jsonl -- the harness does
that, once, at scoring time.

Reports expected calibration error and a reliability plot alongside AUC, because
the EV rule consumes the probability as a number, not as a ranking.
"""
import argparse
import json
import os
import pickle
import sys

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(HERE, "..", "models", "p_win.pkl")

LABEL_CANDIDATES = ("label_won","won", "is_won", "outcome_won", "true_outcome",
                    "outcome", "label", "result")
WIN_TOKENS = {"win", "won", "true", "1", "yes", "merchant_win"}


def load_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def find_label_field(records):
    for key in LABEL_CANDIDATES:
        if key in records[0]:
            return key
    raise SystemExit(
        "Could not find the win/lose label. Keys present on record 0:\n  "
        + ", ".join(sorted(records[0].keys()))
        + "\nAdd the right name to LABEL_CANDIDATES at the top of this file."
    )


def to_binary(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v > 0)
    return int(str(v).strip().lower() in WIN_TOKENS)


def expected_calibration_error(y, p, bins=10):
    """ECE: average gap between confidence and observed frequency, weighted by
    bin population. 0.0 is perfect. Anything over ~0.10 means the EV rule is
    being fed numbers it should not trust."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    ece, rows = 0.0, []
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        conf, freq, w = p[m].mean(), y[m].mean(), m.mean()
        ece += w * abs(conf - freq)
        rows.append((edges[b], edges[b + 1], int(m.sum()), conf, freq))
    return ece, rows


def reliability_plot(rows, path, ece):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [(lo + hi) / 2 for lo, hi, _, _, _ in rows]
    conf = [c for _, _, _, c, _ in rows]
    freq = [f for _, _, _, _, f in rows]

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="grey", lw=1, label="perfect")
    ax.plot(conf, freq, "o-", color="#2563eb", label="model")
    ax.set_xlabel("predicted p(win)")
    ax.set_ylabel("observed win rate")
    ax.set_title(f"Reliability  (ECE = {ece:.3f})")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, dpi=140)
    print(f"wrote {path}")


def train(train_path, out_path, chart_path=None, seed=7):
    recs = load_jsonl(train_path)
    label_key = find_label_field(recs)
    print(f"label field: '{label_key}'   n = {len(recs)}")

    vocab = F.build_vocab(recs)
    names = F.feature_names(vocab)

    X = np.array([F.vectorise(r, vocab) for r in recs], dtype=float)
    y = np.array([to_binary(r[label_key]) for r in recs], dtype=int)
    print(f"features: {X.shape[1]}   base win rate: {y.mean():.3f}")

    # Isotonic needs data. Under ~1000 rows it overfits the calibration curve,
    # so fall back to Platt scaling and say which was used.
    method = "isotonic" if len(recs) >= 1000 else "sigmoid"
    print(f"calibration: {method}")

    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.25, random_state=seed, stratify=y)

    base = HistGradientBoostingClassifier(
        max_depth=4, max_iter=250, learning_rate=0.06,
        min_samples_leaf=15, random_state=seed)
    model = CalibratedClassifierCV(base, method=method, cv=5)
    model.fit(Xtr, ytr)

    p = model.predict_proba(Xte)[:, 1]
    auc = roc_auc_score(yte, p)
    brier = brier_score_loss(yte, p)
    ece, rows = expected_calibration_error(yte, p)

    print("\n-- internal validation split (NOT the holdout) --")
    print(f"AUC   {auc:.3f}")
    print(f"Brier {brier:.4f}")
    print(f"ECE   {ece:.4f}")
    print(f"{'bin':>12} {'n':>5} {'pred':>7} {'actual':>7}")
    for lo, hi, n, conf, freq in rows:
        print(f"  {lo:.1f}-{hi:.1f} {n:5d} {conf:7.3f} {freq:7.3f}")

    if chart_path:
        reliability_plot(rows, chart_path, ece)

    # Refit on everything for the model that ships.
    final = CalibratedClassifierCV(
        HistGradientBoostingClassifier(
            max_depth=4, max_iter=250, learning_rate=0.06,
            min_samples_leaf=15, random_state=seed),
        method=method, cv=5)
    final.fit(X, y)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as fh:
        pickle.dump({
            "model": final, "vocab": vocab, "feature_names": names,
            "label_field": label_key, "calibration": method,
            "n_train": len(recs), "seed": seed,
            "validation": {"auc": auc, "brier": brier, "ece": ece},
        }, fh)
    print(f"\nwrote {out_path}")


_CACHE = None


def _load(path=None):
    global _CACHE
    if _CACHE is None:
        with open(path or DEFAULT_MODEL, "rb") as fh:
            _CACHE = pickle.load(fh)
    return _CACHE


def predict_p_win(dispute, path=None):
    """Drop-in for baselines._estimate_p_win. Raises if no model is on disk."""
    b = _load(path)
    x = np.array([F.vectorise(dispute, b["vocab"])], dtype=float)
    return float(b["model"].predict_proba(x)[0, 1])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default=os.path.join(HERE, "..", "data", "train.jsonl"))
    ap.add_argument("--out", default=DEFAULT_MODEL)
    ap.add_argument("--chart", default=os.path.join(HERE, "..", "data", "reliability.png"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    train(a.train, a.out, a.chart, a.seed)