# Chargeback Triage and Evidence Agent

**Razorpay AI Buildathon — Track 02: AI Risk Manager**

Most merchants either fight every chargeback or fight none. Both are wrong. This
agent decides which disputes are worth contesting, assembles a network-compliant
evidence packet for those, and refuses to submit any claim it cannot trace back
to a source record.

Every number below is measured on a held-out set of 800 disputes the model never
saw, against two mandatory baselines. A metric without a baseline is decoration.

---

## 1. Results

### The decision (Stage 1)

| policy | net rupees | submitted / accepted / escalated | P/R (winnable) | P/R (EV) |
|---|---:|---|---|---|
| contest everything | ₹294,315 | 520 / 0 / 280 | 0.42 / 1.00 | 0.64 / 1.00 |
| contest nothing | ₹0 | 0 / 800 / 0 | 0.00 / 0.00 | 0.00 / 0.00 |
| **agent** | **₹517,048** | 404 / 356 / 40 | 0.54 / 0.72 | **0.95** / 0.82 |

The agent recovers **₹222,732 more than contesting everything**, while submitting
fewer packets (404 vs 520) and sending one seventh as many to a human (40 vs 280).

**Two precision numbers, deliberately.** *Winnable* precision asks whether we
would have won. *EV* precision asks whether contesting was worth attempting at
₹250 a go. They disagree, and the disagreement is the product thesis: a ₹450
case we would win 80% of the time is a miss under the first definition and a
correct decline under the second. The agent scores 0.54 on the first and 0.95 on
the second. It is not trying to win every dispute. It is trying to spend well.

### Where the money is, by difficulty tier

| tier | n | P/R (winnable) | P/R (EV) | net ₹ |
|---|---:|---|---|---:|
| A — documentary wins | 140 | 0.89 / 0.92 | 1.00 / 0.99 | 241,367 |
| B — winnable with the right packet | 132 | 0.57 / 0.83 | 0.99 / 0.97 | 129,810 |
| C — the ambiguous middle | 260 | 0.35 / 0.46 | 1.00 / 0.67 | 118,091 |
| D — very difficult | 152 | 0.23 / 0.61 | 0.73 / 0.75 | 29,880 |
| E — structurally unwinnable | 116 | 0.00 / 0.00 | 0.00 / 0.00 | −2,100 |

Tier E is the point of the project. The agent contested **nothing** in the
unwinnable tier. The −₹2,100 is the cost of accepting those disputes, not money
burned trying to win them. Industry data puts the representment win rate for
true fraud chargebacks at 9.27%; for a class of disputes that wins roughly one
time in eleven, at a cost per attempt, the correct action is to accept
immediately and stop spending. The agent learned to do that from observable
features alone — it never sees the tier.

### The verifier (Stage 4)

Hallucination is treated as a compliance failure, not a known limitation. A
fabricated delivery timestamp in a representment packet is false evidence
submitted to a card network, by a merchant the aggregator is responsible for.

The verifier is a hard gate. To test it, faults are injected at a known rate and
the measured rate compared:

| injected fault rate | measured | packets blocked | mean completeness |
|---:|---:|---:|---:|
| 0.00 | 0.000 | 0.30 | 0.844 |
| 0.05 | 0.053 | 0.44 | 0.804 |
| 0.10 | 0.115 | 0.62 | 0.752 |
| 0.20 | 0.211 | 0.76 | 0.662 |
| 0.40 | 0.401 | 0.96 | 0.493 |

Detection tracks injection across an eightfold range.

**The intercept is the more interesting number.** At *zero* model error, 30% of
packets still block — on evidence timestamped after the dispute, and on required
documents that never existed. That share of the human queue is structural. No
improvement in drafting removes it. The bottleneck is evidence assembly, not
generation.

### Robustness: the constants were chosen, not measured

Four numbers underpin every rupee figure: contest cost, human review cost, net
recovery fraction, and the rate at which a human can rescue a blocked packet. No
public figure exists for any of them. Each was swept one at a time
(`data/cost_sweep_results.txt`):

| constant | range | agent | contest-all |
|---|---|---|---|
| contest cost | ₹100 → ₹900 (9×) | 591,869 → 294,555 | 414,315 → **−225,685** |
| human review cost | ₹300 → ₹2,500 (8×) | 523,529 → 503,703 (−3.8%) | 434,315 → **−181,685** |
| net recovery | 0.5 → 1.0 | 258,220 → 628,103 | −1,462 → 421,077 |
| human resolve rate | 0.2 → 0.8 | 505,799 → 517,048 (+2.2%) | 223,494 → 294,315 (+31.7%) |

The agent wins at every value tested. More usefully, it is far *less sensitive*:
across an 8× change in review cost it moves 3.8%, while contest-all turns
negative. Contest-all goes negative in three of the four sweeps; the agent never
does. Where the true values are unknown, that stability is itself the argument.

### A negative result: confidence thresholds do not help

An obvious alternative to expected value is a confidence floor — never contest
below some p(win), whatever the amount. Swept from 0.00 to 0.30:

```
floor   net rupees
0.00     517,048      <- peak
0.10     517,298
0.20     496,823
0.30     451,682      <- costs ₹65,616
```

The floor buys nothing and costs ₹65,616 at 0.30. Correct cost accounting has
already declined everything a threshold would catch (Tier E sits at zero
contests at *every* floor value), so the floor only starts destroying the
high-amount low-probability cases that expected value says are worth an attempt.
A ₹2,00,000 dispute at 20% odds is worth an analyst's hour; a floor at 0.25
throws it away.

Reported because it did not work. `data/floor_curve.png`.

---

## 2. The pipeline

Input is a dispute. Output is a decision, a verified packet, and a log line.

**Stage 1 — Triage.** A calibrated gradient-boosted classifier scores p(win)
from reason code, amount, evidence completeness, address match, prior disputes,
device signals and artifact timestamps. An expected-value rule converts that
into a decision.

The EV rule prices against the branch the case will *actually* take. The packet
is built *before* the decision, because a case whose packet will be blocked does
not cost ₹250 — it costs ₹800 and only pays out on the fraction a human can
resolve. Pricing every contest identically overspends on exactly the cases least
able to repay it. Fixing this was worth ₹72,850 on its own, with no change to
the model.

**Stage 2 — Retrieval. No model.** Look up the reason code in the rulebook, pull
exactly those artifacts. A dictionary lookup and a filter. Routing this through
an LLM would add latency, cost, and a failure mode, in exchange for nothing.

**Stage 3 — Drafting.** A language model produces a structured claims list, not
prose: each claim carries the ID of the artifact supporting it and the evidence
kind it asserts. The model sees *only* what Stage 2 retrieved, so it cannot cite
something that was never pulled — one whole class of fabrication removed by
construction rather than by instruction.

**Stage 4 — The verifier.** Four deterministic checks per claim: the artifact
exists, its kind matches what the claim asserts, it predates the dispute, and
after stripping, the survivors still satisfy the reason code's requirement.
Nothing here uses a model to check a model; that just moves the trust problem.
Failing the first three strips a claim. Failing the fourth blocks the packet and
routes it to a human.

**Stage 5 — Audit and stopping rules.** Every dispute produces a durable record:
decision, p(win), the EV calculation, artifacts used, verifier result. No
submission of a packet that failed verification. A drafting failure returns zero
claims, which the verifier treats as incomplete — a failed API call can never
become a submission.

### Model quality

Trained on 3,000 disputes, evaluated on an internal split (not the holdout):

```
AUC    0.783
Brier  0.1854   (base rate Brier 0.242 → skill score 0.23)
ECE    0.067
```

Calibration matters more than ranking here, because the EV rule multiplies
p(win) by rupees. A model that says 0.9 when it is right 0.6 of the time
overspends systematically, and AUC will not catch it. `data/reliability.png`.

Two honest notes on this. The model is mildly overconfident above p=0.5, which
biases toward contesting and makes the net rupee figure a slight
*under*estimate. And the ECE is inflated by a bin holding 3 samples — isotonic
regression on bins that thin is unreliable. Excluding it, ECE is roughly 0.045.

**A finding worth stating plainly: the weaker classifier made more money.** After
correcting the rulebook, AUC fell from 0.812 to 0.783 while net rupees rose 17%.
Ranking accuracy and rupee outcome are not the same objective. The EV rule is
what converts one into the other.

---

## 3. Data and its limits

The most important section in this README. Everything that is real, everything
that is generated, and what would change with production data.

### What is real

**The rulebook.** `rulebook/reason_codes.yaml` — 42 reason codes across UPI,
Visa, Mastercard, RuPay, American Express and Razorpay's own RZP codes, each
mapped to its evidence requirements and to the field of Razorpay's contest API
that evidence would be submitted under. Verified against Razorpay's published
documentation on 27 August 2026.

**The submission schema.** Packets are keyed to the real API fields
(`shipping_proof`, `billing_proof`, `proof_of_service`, `access_activity_log`,
and so on) rather than an invented taxonomy. A packet this agent assembles maps
onto an actual `PATCH /v1/disputes/:id/contest` payload.

### What is generated

Dispute outcome data does not exist publicly, least of all for Indian merchants.
Razorpay legally cannot share it — RBI-regulated aggregator, PCI-DSS. Every
applicant hits the same wall.

Generated: which transactions get disputed and under which code; the evidence
artifacts; and the win/lose outcome per dispute. A 24-pattern case taxonomy
across five difficulty tiers, with true win-probability bands per pattern.

Five rules keep it honest:

1. **The generator was frozen before the model was written.** Committed and
   dated; the repo is public, so the ordering is provable.
2. **The model is not handed the structure it must find.** Tier, pattern ID and
   true win probability are written into each record with a leading underscore
   and are excluded by a guard in `agent/features.py` that fails the run if one
   is ever read as a feature.
3. **The holdout is generated differently** — different seed, shifted tier
   weights, and one dispute pattern (C5, evidence timestamped after the dispute)
   that appears *only* in the holdout.
4. **Unwinnable cases exist by design.** Tier E has no tell to find. The ceiling
   is not 100% and the project is not a one-line conditional.
5. **Calibrated against a real substrate** — *not done.* See below.

### What is not real, and what it costs

**The transaction substrate is synthetic.** The plan was to fit amount and
time-of-day distributions to IEEE-CIS (≈590k labelled real e-commerce
transactions) and publish an overlay chart. That was not completed. Amounts and
timestamps come from distributions chosen to be plausible, not fitted. This is
the one rule of the five that is not shipped, and it means the rupee figures are
denominated in invented rupees. The *policy comparison* is unaffected — every
policy sees the same amounts — but the absolute totals should be read as scale-
free.

**The four cost constants were chosen, not measured.** Contest cost ₹250, human
review ₹800, net recovery 0.85, human resolve rate 0.80. No public figure exists
for any of them in an Indian context. This is why they are swept (§1).

**The human-queue model is deliberately conservative.** An escalated case is
assumed to reach a person who can repair the packet but cannot change the facts
— the human gets no skill bonus, only the ability to unblock.

**The benchmarks quoted are US or global, not Indian.** The 41% overall
representment win rate, 9.27% for true fraud, and 12–18% net recovery are
vendor-published and survey-based, predominantly US. No reliable India-specific
chargeback benchmark is publicly available. Applying them to Indian merchants is
an assumption, and it is labelled as one wherever it appears.

**Four rulebook entries are provisional.** Razorpay's evidence page groups codes
under four category tabs; only the Customer Dispute tab was retrievable.
Visa 10.4 and 12.5/12.6, and Mastercard 4837, are compiled from card-network
documentation via third-party references and are tagged
`provenance: network_docs` in the rulebook. The generator prints a warning
naming them on every run.

**"Suggested", not "required".** Razorpay labels these Suggested Documents. This
project treats the full suggested list as the completeness bar, because a
partial packet is the failure mode worth measuring. That is a modelling choice,
not a claim about what the networks mandate.

**The hallucination rate reported against a real model is thin.** Gemini
produced zero fabrications across 17 claims on 5 disputes — too few claims to be
a rate. The verifier curve in §1 is the robust result; it measures the *gate*,
using injected faults, and holds across an eightfold range. These are two
different claims and are not interchangeable.

### Two errors found and corrected during the build

Both are in the git history rather than quietly fixed, because how a system
fails is part of what it is.

**The rulebook was wrong.** v1 was transcribed from memory: RZP01 was modelled
as a duplicate-charge code when it is goods-not-provided, Visa 13.1 required an
`avs_result` that does not appear in the docs, and UPI 1064 required a
non-existent `ip_record`. Six patterns in the case taxonomy also filed the wrong
code for the scenario described — fraud cases under customer-dispute codes.
Everything was regenerated against the corrected rulebook. A validator now fails
the run if the taxonomy cites a code the rulebook does not define. Pre-correction
results are kept in `data/v1_pre_rulebook_fix/` for comparison.

**The cost sweep was measuring nothing.** The first version patched the constant
on `generator/distributions.py`, which drives the decision, but not on
`eval/distributions_ref.py`, which drives the scoring. It ran cleanly and printed
"the headline is robust" while having varied one constant out of four. The tell
was identical output across an 8× range. The sweep now patches both modules and
refuses to report robustness for any constant whose values produce identical
results.

### What would change with production data

The outcome labels would be real, so precision and recall would mean something
about the world rather than about a generator. Packet completeness and
hallucination rate would not change definition at all — they are verified against
the input documents, not against a label, and do not care whether the disputes
are synthetic. That is the structural advantage of this design: only one third of
the scorecard depends on ground truth.

---

## 4. Running it

```bash
pip install scikit-learn pyyaml matplotlib

# generate (seeded; holdout uses different parameters and one unseen pattern)
cd generator
python generate.py --profile train   --n 3000 --seed 11 --out ../data/train.jsonl
python generate.py --profile holdout --n 800  --seed 97 --out ../data/holdout.jsonl

# train the calibrated classifier
cd ../agent
python classifier.py --train ../data/train.jsonl --chart ../data/reliability.png

# score all three policies
cd ../eval
python run_eval.py --data ../data/holdout.jsonl --json-out ../data/results_v2.json

# verifier fault injection
cd ../agent
CB_FAULT_RATE=0.10 python verify.py ../data/holdout.jsonl 50

# robustness
python cost_sweep.py
```

Drafting defaults to a deterministic mock provider with a configurable fault
rate — no API key, no network. Set `CB_LLM=gemini` and `GEMINI_API_KEY` in
`.env` for the real model.

---

## 5. On the existing product

Razorpay's Agent Studio already ships a chargeback agent that reviews cases,
verifies proof and submits evidence. The framing is "we fight your disputes for
you," and the scarce capability in that framing is drafting.

This project does not claim novelty. It claims a reframe and a measurement. The
data says the scarce capability is not writing the rebuttal — it is knowing
which disputes deserve one, and refusing to submit a claim that cannot be traced
to a record. Merchants do not lose disputes because they cannot write. They lose
because roughly two thirds have no dedicated chargeback owner, the evidence lives
across four systems, and reason-code requirements are specialist knowledge.

That reading is the same one Track 4 of this buildathon states as the 2026
builder consensus: verification capacity, not generation speed, is the
bottleneck. The 30% intercept in §1 is that claim, measured.

---

