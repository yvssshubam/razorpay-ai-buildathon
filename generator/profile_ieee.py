"""Profile the real transaction substrate: IEEE-CIS Fraud Detection.

Reads three columns from ~590k real e-commerce transactions and reports the
distributional facts the generator needs to match:

  - the amount distribution, as log-normal parameters (amounts are strongly
    right-skewed; the log is roughly normal, which is what we fit)
  - hour-of-day and day-of-week weights
  - the fraud rate, and whether fraudulent transactions carry different amounts

WHAT THIS DOES AND DOES NOT GIVE US. It gives the SHAPE of real payment traffic.
It gives no dispute outcomes -- IEEE-CIS labels fraud, not chargeback verdicts,
and no public dataset labels the latter. So the transaction substrate becomes
real and the dispute layer stays generated. Saying more than that would be
overclaiming.

TransactionDT is seconds from an unspecified reference point, not a timestamp.
The first value is 86400 (one day), so day 0 of the dataset is the reference.
Absolute dates are unknowable; hour-of-day and day-of-week cycles are not,
because they are periodic regardless of where the origin sits.

Usage:
  python profile_ieee.py "C:/Users/SHUBAM/Downloads/train_transaction.csv/train_transaction.csv"
"""
import argparse
import json
import math
import os

import numpy as np
import pandas as pd

COLS = ["TransactionAmt", "TransactionDT", "isFraud"]


def profile(path):
    print(f"reading 3 of 394 columns from {os.path.basename(path)} ...")
    df = pd.read_csv(path, usecols=COLS)
    n = len(df)
    print(f"{n:,} transactions\n")

    amt = df["TransactionAmt"].astype(float)
    amt = amt[amt > 0]

    # Log-normal fit. Amounts span orders of magnitude, so fit in log space.
    logs = np.log(amt.values)
    mu, sigma = float(logs.mean()), float(logs.std(ddof=1))

    qs = [0.01, 0.05, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 0.999]
    quantiles = {str(q): float(amt.quantile(q)) for q in qs}

    print("AMOUNT (USD)")
    print(f"  n              {len(amt):,}")
    print(f"  mean           {amt.mean():.2f}")
    print(f"  median         {amt.median():.2f}")
    print(f"  min / max      {amt.min():.2f} / {amt.max():,.2f}")
    print(f"  log-normal     mu={mu:.4f}  sigma={sigma:.4f}")
    print(f"  skew           {amt.skew():.2f}")
    for q in qs:
        print(f"  p{q*100:<6.1f}       {amt.quantile(q):>12,.2f}")

    # TransactionDT is seconds from an arbitrary origin.
    dt = df["TransactionDT"].astype("int64")
    hour = ((dt // 3600) % 24).astype(int)
    dow = ((dt // 86400) % 7).astype(int)

    hour_counts = hour.value_counts().sort_index()
    hour_w = (hour_counts / hour_counts.sum()).reindex(range(24), fill_value=0.0)

    dow_counts = dow.value_counts().sort_index()
    dow_w = (dow_counts / dow_counts.sum()).reindex(range(7), fill_value=0.0)

    print("\nHOUR OF DAY (share of transactions)")
    for h in range(24):
        bar = "#" * int(hour_w[h] * 400)
        print(f"  {h:02d}  {hour_w[h]:.4f}  {bar}")

    print("\nDAY OF WEEK (relative to dataset origin, not calendar)")
    for d in range(7):
        bar = "#" * int(dow_w[d] * 200)
        print(f"  {d}   {dow_w[d]:.4f}  {bar}")

    fraud_rate = float(df["isFraud"].mean())
    fa = amt[df["isFraud"] == 1]
    ca = amt[df["isFraud"] == 0]
    print(f"\nFRAUD")
    print(f"  rate                 {fraud_rate:.4f}")
    print(f"  median amount fraud  {fa.median():.2f}")
    print(f"  median amount clean  {ca.median():.2f}")
    print(f"  ratio                {fa.median() / ca.median():.2f}x")

    out = {
        "source": "IEEE-CIS Fraud Detection (Kaggle/Vesta), train_transaction.csv",
        "n_transactions": int(n),
        "currency": "USD",
        "amount": {
            "lognormal_mu": mu,
            "lognormal_sigma": sigma,
            "mean": float(amt.mean()),
            "median": float(amt.median()),
            "min": float(amt.min()),
            "max": float(amt.max()),
            "skew": float(amt.skew()),
            "quantiles": quantiles,
        },
        "hour_weights": [float(hour_w[h]) for h in range(24)],
        "day_of_week_weights": [float(dow_w[d]) for d in range(7)],
        "fraud": {
            "rate": fraud_rate,
            "median_amount_fraud": float(fa.median()),
            "median_amount_clean": float(ca.median()),
        },
        "caveats": [
            "Amounts are USD. The generator fits the SHAPE (log-normal sigma "
            "and the quantile structure) and rescales the location to Indian "
            "e-commerce order values. The distribution is real; the scale is set.",
            "TransactionDT is seconds from an unspecified origin, so day-of-week "
            "indices are relative to that origin and do not map to calendar days.",
            "isFraud labels fraud, not chargeback outcomes. No dispute verdicts "
            "are taken from this dataset.",
        ],
    }

    here = os.path.dirname(os.path.abspath(__file__))
    dest = os.path.join(here, "..", "rulebook", "ieee_profile.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nwrote {os.path.normpath(dest)}")

    # Keep a sample of real amounts for the overlay chart, so the chart can be
    # redrawn without the 683MB source file present.
    sample = amt.sample(n=20000, random_state=7).values
    sdest = os.path.join(here, "..", "data", "ieee_amount_sample.json")
    with open(sdest, "w", encoding="utf-8") as fh:
        json.dump([round(float(v), 2) for v in sample], fh)
    print(f"wrote {os.path.normpath(sdest)}  (20k amounts, for the overlay chart)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    a = ap.parse_args()
    profile(a.csv)