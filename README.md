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
| contest everything | ₹293,402 | 484 / 0 / 316 | 0.39 / 1.00 | 0.67 / 1.00 |
| contest nothing | ₹0 | 0 / 800 / 0 | 0.00 / 0.00 | 0.00 / 0.00 |
| **agent** | **₹526,279** | 392 / 370 / 38 | 0.54 / 0.74 | **0.93** / 0.75 |

The agent recovers **₹232,877 more than contesting everything** — 1.79× the
return on the same 800 disputes — while submitting fewer packets (392 vs 484)
and sending **one eighth** as many to a human (38 vs 316).

**Where completeness and hallucination are measured.** The policy scorer in
`eval/baselines.py` assembles packets deterministically rather than calling
Stages 3 and 4, so those two metrics belong to the verifier section below, where
they are measured on the real drafting path. Both are also structurally pinned
here: a packet is submitted only when it is not blocked, which means it is
already complete, and unsupported claims are stripped before submission. Neither
figure could be anything but 1.0 and 0.0 in this table.

**Two precision numbers, deliberately.** *Winnable* precision asks whether we
would have won. *EV* precision asks whether contesting was worth attempting at
₹250 a go. They disagree, and the disagreement is the product thesis: a ₹450
case we would win 80% of the time returns ₹306 in expected recovery against a
₹250 cost — a miss under the first definition and a correct decline under the
second. The agent scores 0.54 on the first and 0.93 on the second. It is not
trying to win every dispute. It is trying to spend well.

### Where the money is, by difficulty tier

| tier | n | P/R (winnable) | P/R (EV) | net ₹ |
|---|---:|---|---|---:|
| A — documentary wins | 135 | 0.85 / 0.96 | 1.00 / 0.99 | 234,598 |
| B — winnable with the right packet | 109 | 0.63 / 0.93 | 0.99 / 0.99 | 161,428 |
| C — the ambiguous middle | 287 | 0.39 / 0.48 | 0.97 / 0.54 | 94,424 |
| D — very difficult | 151 | 0.13 / 0.45 | 0.63 / 0.70 | 38,979 |
| E — structurally unwinnable | 118 | 0.00 / 0.00 | 1.00 / 0.27 | −3,150 |

Tier E is the point of the project. The agent wins **nothing** there — winnable
precision and recall are both zero — and it has learned to mostly stop trying:
EV recall of 0.27 means it declines nearly three quarters of the cases a naive
expected-value reading would contest. Industry data puts the representment win
rate for true fraud chargebacks at 9.27%; for a class of disputes that wins
roughly one time in eleven, at a cost per attempt, the correct action is to
accept immediately and stop spending. The agent reaches that from observable
features alone — it never sees the tier. The EV precision of 1.00 in that row is
not a contradiction: every Tier E case the agent did contest was
positive-expected-value at the time of the decision. Correct by the rule, and
still a loss.

The residual −₹3,150 is honest and worth stating: with a heavy-tailed amount
distribution, a 5% chance on a ₹80,000 dispute clears a ₹250 threshold on
expected value and still loses four times in five. Expected value is a long-run
rule; losing individual bets is how it works. That loss is 0.6% of the total.

### The verifier (Stage 4)

Hallucination is treated as a compliance failure, not a known limitation. A
fabricated delivery timestamp in a representment packet is false evidence
submitted to a card network, by a merchant the aggregator is responsible for.

The verifier is a hard gate. To test it, faults are injected at a known rate and
the measured rate compared:

| injected fault rate | measured | packets blocked | mean completeness |
|---:|---:|---:|---:|
| 0.00 | 0.000 | 0.34 | 0.844 |
| 0.05 | 0.049 | 0.48 | 0.800 |
| 0.10 | 0.108 | 0.66 | 0.751 |
| 0.20 | 0.197 | 0.78 | 0.674 |
| 0.40 | 0.390 | 0.94 | 0.511 |

Detection tracks injection across an eightfold range.

**On the real model.** `gemini-3.1-flash-lite` was run over the same 50
disputes: **zero fabrications across 223 claims**, block rate 0.340, mean
completeness 0.844. Those last two figures are identical to the mock's
zero-fault row above, on the same disputes — so every block came from the
evidence itself, not from how the mock constructs claims. Two independent runs
agreeing is what makes the intercept below a property of the data rather than an
artifact of the harness.

A zero fabrication rate does not make the gate redundant; it means this model
did not test it. The injected-fault curve is what demonstrates the gate works
when a model does fabricate. Both claims are needed and neither substitutes for
the other.

**The intercept is the more interesting number.** At *zero* model error, about a
third of packets still block — on evidence timestamped after the dispute, and on
required documents that never existed at all. One holdout case (D00003, Visa
13.1) blocks on a single missing item, `service_completion_records`, with no
claim stripped and no model error anywhere in the chain. That share of the human
queue is structural. No improvement in drafting removes it. **The bottleneck is
evidence assembly, not generation.**

### Robustness: the constants were chosen, not measured

Four numbers underpin every rupee figure: contest cost, human review cost, net
recovery fraction, and the rate at which a human can rescue a blocked packet. No
public figure exists for any of them in an Indian context. Each was swept one at
a time (`data/cost_sweep_results.txt`):

| constant | range | agent | contest-all |
|---|---|---|---|
| contest cost | ₹100 → ₹900 (9×) | 605,729 → 335,964 | 413,402 → **−226,598** |
| human review cost | ₹300 → ₹2,500 (8×) | 549,581 → 511,300 (−7.0%) | 451,402 → **−243,798** |
| net recovery | 0.5 → 1.0 | 265,658 → 650,516 | **−13,858** → 425,085 |
| human resolve rate | 0.2 → 0.8 | 508,338 → 526,279 (+3.5%) | 203,586 → 293,402 (+44%) |

The agent wins at every value tested. More usefully, it is far *less sensitive*:
across an 8× change in review cost it moves 7.0%, while contest-all turns
negative. Contest-all goes negative in three of the four sweeps; the agent never
does, and its worst value anywhere is ₹265,658.

The mechanism is simple. The agent escalates 38 packets; contest-all escalates
316. Where the true cost of human review is unknown — and it is — that
difference in exposure is itself the argument.

A fifth constant, the ₹1,500 median order value, is **not** swept: varying it
requires regenerating the datasets and retraining rather than rescoring. It is
disclosed as a stated assumption in §3.

### A negative result: confidence thresholds do not help

An obvious alternative to expected value is a confidence floor: never contest
below some p(win), whatever the amount. Swept from 0.00 to 0.30 on the holdout,
it peaks at zero and loses **₹28,154 at the very first step above it**.

```
floor   net rupees
0.00     526,279   <- peak
0.05     498,125
0.10     493,547
0.15     478,932
0.20     479,143
0.25     483,193
0.30     479,385
```

Tier D collapses from ₹38,979 to ₹10,825 at a floor of 0.05 and turns negative
by 0.15. The floor kills exactly the high-amount low-probability cases that
expected value says are worth attempting — a ₹2,00,000 dispute at 20% odds is
worth an analyst's hour, and a floor at 0.25 throws it away. It cannot
distinguish "low probability because unwinnable" from "low probability but a
large amount", and the second is where triage earns its keep.

**This result took three runs to get right, which is itself worth reporting.**
On an earlier, invented amount distribution the floor cost ₹65,616. On resampled
real amounts, with the escalation branch still mispriced, it appeared to *gain*
₹10,250 at a floor of 0.20 — a gain that did not replicate on a second dataset,
and that vanished entirely once the escalation cost was corrected (§3). The
floor was compensating for an accounting error, not adding anything.

---

## 2. The pipeline

Input is a dispute. Output is a decision, a verified packet, and a log line.

![Pipeline architecture](docs/architecture.svg)

**Stage 1 — Triage.** A calibrated gradient-boosted classifier scores p(win)
from reason code, amount, evidence completeness, address match, prior disputes,
device signals and artifact timestamps. An expected-value rule converts that
into a decision.

The EV rule prices against the branch the case will *actually* take. The packet
is built *before* the decision, because a case whose packet will be blocked does
not cost ₹250 — the packet was already assembled, so it costs ₹250 plus ₹800 of
analyst time, and it pays out only on the fraction a human can resolve. Pricing
every contest identically overspends on exactly the cases least able to repay
it. Building the packet first was worth ₹72,850; pricing the blocked branch
correctly cut the human queue by a further 24%.

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

A merchant-facing dashboard over the same pipeline lives in `webapp/` (Vite +
React + TypeScript) with a FastAPI backend in `serve/`. Every scored field it
displays comes from the modules above; the API routes and serialises, it does
not decide anything.

### Model quality

Trained on 3,000 disputes, evaluated on an internal split (not the holdout):

```
AUC    0.800
Brier  0.1760   (base-rate Brier 0.2458 -> skill score 0.284)
ECE    0.0285
```

Calibration matters more than ranking here, because the EV rule multiplies
p(win) by rupees. A model that says 0.9 when it is right 0.6 of the time
overspends systematically, and AUC will not catch it. `data/reliability.png`.

Two honest notes. The model is mildly overconfident in the 0.6–0.7 band
(predicted 0.638, observed 0.548) on 31 samples, and mildly underconfident from
0.7 to 0.9. Neither is worth correcting; both are within what 3,000 rows
supports.

**A finding worth stating plainly: better data made a better model, not better
tuning.** AUC rose from 0.783 to 0.800 and ECE fell from 0.067 to 0.0285 purely
from replacing the amount distribution with resampled real transactions. Same
features, same algorithm, no hyperparameter changes.

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

**The transaction substrate.** Amounts are drawn from the empirical distribution
of IEEE-CIS Fraud Detection (Kaggle/Vesta) — 590,540 real e-commerce
transactions — and rescaled. Hour-of-day and day-of-week cycles are taken from
the same source. `data/amount_overlay.png`.

This is a resampling, not a parametric fit. An earlier version fitted a
log-normal to the real sigma of 0.954, and the overlay chart showed why that was
not good enough: real p99/median is 15.28 and the fitted distribution gave 8.71.
IEEE-CIS has a skew of 14.37 and a maximum 464× its median — no log-normal
reproduces that, and real amounts additionally cluster at price points. Drawing
real values directly and rescaling gives p90/median 3.75 against the real 3.91,
and p99/median 13.52 against 15.28. The residual gap is the sampling pool being
20,000 of the 590,540 transactions.

**The scale is set, not fitted.** IEEE-CIS is in USD, and converting US order
sizes at an exchange rate would give a ~₹5,700 median, which is not what Indian
e-commerce looks like. The median is set to ₹1,500, between two published
figures: Indian e-commerce AOV of US$59 (ECDB, 2024, ~₹5,000) and quick-commerce
AOV of ₹500 (Economic Times). Both are means; the empirical mean/median ratio in
IEEE-CIS is 1.94, implying medians of ~₹2,580 and ~₹258. ₹1,500 sits between
them and reflects Razorpay's base being dominated by small e-commerce merchants
rather than the big-ticket categories that pull the national AOV upward. It is
not swept, because varying it requires regenerating the datasets rather than
rescoring.

**The honest description of the dataset is: real transaction substrate,
generated dispute layer.**

### What is generated

Dispute outcome data does not exist publicly, least of all for Indian merchants.
Razorpay legally cannot share it — RBI-regulated aggregator, PCI-DSS. Every
applicant hits the same wall, and Track 4 of this buildathon specifies synthetic
data outright.

Generated: which transactions get disputed and under which code; the evidence
artifacts; and the win/lose outcome per dispute. A 24-pattern case taxonomy
across five difficulty tiers, with true win-probability bands per pattern.

Five rules keep it honest:

1. **The generator was written and frozen before any model code.** The evidence
   for this is structural rather than chronological: the generator has no
   knowledge of the model, and the model reads its features through a guard
   (rule 2) that fails the run on contact with any latent field. The repository
   was initialised late in the build, so the commit history does not
   independently attest the ordering.
2. **The model is not handed the structure it must find.** Tier, pattern ID and
   true win probability are written into each record with a leading underscore
   and are excluded by a guard in `agent/features.py` that fails the run if one
   is ever read as a feature.
3. **The holdout is generated differently** — different seed, shifted tier
   weights, and one dispute pattern (C5, evidence timestamped after the dispute)
   that appears *only* in the holdout.
4. **Unwinnable cases exist by design.** Tier E has no tell to find. The ceiling
   is not 100% and the project is not a one-line conditional.
5. **Calibrated against a real substrate** — see above.

### What is still not real

**The four cost constants were chosen, not measured.** Contest cost ₹250, human
review ₹800, net recovery 0.85, human resolve rate 0.80. No public figure exists
for any of them in an Indian context. This is why they are swept (§1).

**Net recovery is modelled proportionally; real chargeback fees are flat.** The
0.85 treats the fee as a share of the amount, so it implies a ₹90 fee on a ₹600
dispute and a ₹3,300 fee on a ₹22,000 one. A flat ₹400 fee would leave the small
dispute with nothing worth recovering. The distortion is concentrated below about
₹5,000, which is the densest part of the distribution, and it biases toward
contesting small disputes. Stated rather than corrected, because changing it
means another full regeneration.

**The human-queue model is deliberately conservative.** An escalated case is
assumed to reach a person who can repair the packet but cannot change the facts
— the human gets no skill bonus, only the ability to unblock.

**Packet quality does not affect the win rate.** The outcome label is drawn from
the case pattern and does not depend on the packet the agent assembles, because
the counterfactual is unknowable. So Stages 3 and 4 contribute to the money only
through the block decision, never through better outcomes. A reader would
reasonably assume otherwise.

**The benchmarks quoted are US or global, not Indian.** The 41% overall
representment win rate, 9.27% for true fraud, and 12–18% net recovery are
vendor-published and survey-based, predominantly US. No reliable India-specific
chargeback benchmark is publicly available. Applying them to Indian merchants is
an assumption, and it is labelled as one wherever it appears. Note also that the
12–18% figure is *portfolio* net recovery, which already contains the win rate —
it is not comparable to the 0.85 constant above, which is the share recovered
given a win.

**Four rulebook entries are provisional.** Razorpay's evidence page groups codes
under four category tabs; only the Customer Dispute tab was retrievable. Visa
10.4, 12.5 and 12.6, and Mastercard 4837, are compiled from card-network
documentation via third-party references and are tagged
`provenance: network_docs` in the rulebook. The generator prints a warning
naming them on every run.

**"Suggested", not "required".** Razorpay labels these Suggested Documents. This
project treats the full suggested list as the completeness bar, because a
partial packet is the failure mode worth measuring. That is a modelling choice,
not a claim about what the networks mandate.

**The real-model hallucination measurement is one model on one dataset.**
`gemini-3.1-flash-lite` produced zero fabrications across 223 claims on 50
disputes (§1). That bounds the rate below roughly 1.3%, but it is a single model
on a single generated dataset, and the constrained retrieval is doing real work
— the model cannot cite an artifact it was never shown. A zero here means the
verifier was *untested* by this model, not that it is unnecessary; that is
exactly what the fault-injection curve is for.

**Training and holdout amounts come from the same sampling pool.** Other
parameters differ between the two sets by design; amounts do not, because both
are samples from the same real distribution.

### Four errors found and corrected during the build

All are in the git history rather than quietly fixed, because how a system fails
is part of what it is. Three of the four produced a *plausible number* rather
than a crash, which is the expensive kind.

**The rulebook was wrong.** v1 was transcribed from memory: RZP01 was modelled
as a duplicate-charge code when it is goods-not-provided, Visa 13.1 required an
`avs_result` that does not appear in the docs, and UPI 1064 required a
non-existent `ip_record`. Six patterns in the case taxonomy also filed the wrong
code for the scenario described — fraud cases under customer-dispute codes.
Everything was regenerated against the corrected rulebook. A validator now fails
the run if the taxonomy cites a code the rulebook does not define.
Pre-correction results are kept in `data/v1_pre_rulebook_fix/`.

**The cost sweep was measuring nothing.** The first version patched the constant
on `generator/distributions.py`, which drives the decision, but not on
`eval/distributions_ref.py`, which drives the scoring. It ran cleanly and printed
"the headline is robust" while having varied one constant out of four. The tell
was identical output across an 8× range. The sweep now patches both modules and
refuses to report robustness for any constant whose values produce identical
results.

**The EV rule mispriced blocked packets, twice.** First it charged every contest
at `CONTEST_COST` and only discovered afterwards whether the packet would be
blocked; since assembly is deterministic and independent of the decision, it can
be done first. Correcting that was worth ₹72,850 and cut escalations by 72%.

Then a subtler version of the same split: `metrics.net_rupee_impact` charged
`CONTEST_COST + HUMAN_REVIEW_COST` for an escalation while the decision rule
charged `HUMAN_REVIEW_COST` alone. The agent escalated whenever gross recovery
cleared ₹1,000; the scorer only profited above ₹1,312.50. Every case in that band
was escalated by the policy and booked as a loss by the metric — the same
decision-versus-scoring drift as the cost sweep bug, one layer down. Correcting
it moved the headline from ₹529,555 to ₹526,279, cut the human queue from 50 to
38, and removed a spurious ₹10,250 result from the floor sweep. The escalation
cost now has a single definition in `metrics.escalation_cost` which both paths
import.

**The amount distribution was too smooth.** Fitting a log-normal gave a
p99/median of 8.71 when the real data has 15.28. Real transactions have a
heavier tail and cluster at price points, so amounts are now resampled directly
rather than approximated.

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
pip install scikit-learn pyyaml matplotlib pandas

# one-off: profile the real substrate (needs the Kaggle IEEE-CIS CSV)
cd generator
python profile_ieee.py /path/to/train_transaction.csv

# generate (seeded; holdout uses different parameters and one unseen pattern)
python generate.py --profile train   --n 3000 --seed 11 --out ../data/train.jsonl
python generate.py --profile holdout --n 800  --seed 97 --out ../data/holdout.jsonl

# train the calibrated classifier
cd ../agent
python classifier.py --train ../data/train.jsonl --chart ../data/reliability.png

# score all three policies
cd ../eval
python run_eval.py --data ../data/holdout.jsonl --json-out ../data/results.json

# verifier fault injection
cd ../agent
CB_FAULT_RATE=0.10 python verify.py ../data/holdout.jsonl 50

# robustness
python cost_sweep.py
```

Drafting defaults to a deterministic mock provider with a configurable fault
rate — no API key, no network. For the real model, set `GEMINI_API_KEY` and
`CB_LLM_MODEL=gemini-3.1-flash-lite` in `.env`, then `CB_LLM=gemini`. The
reported run used 50 disputes at 4.5s intervals to stay inside the free tier's
15 requests/minute.

The dashboard needs two terminals:

```bash
cd serve  && uvicorn app:app --reload --port 8000
cd webapp && npm install && npm run dev
```

The IEEE-CIS CSV is not in this repository (683MB, and not ours to
redistribute). `rulebook/ieee_profile.json` and `data/ieee_amount_sample.json`
are, so everything downstream reproduces without it.

---

## 5. On the existing product

Razorpay's Agent Studio already ships a chargeback agent that reviews cases,
verifies proof and submits evidence. The framing is "we fight your disputes for
you," and the scarce capability in that framing is drafting.

This project does not claim novelty. It claims a reframe and a measurement. The
data says the scarce capability is not writing the rebuttal — it is knowing which
disputes deserve one, and refusing to submit a claim that cannot be traced to a
record. Merchants do not lose disputes because they cannot write. They lose
because roughly two thirds have no dedicated chargeback owner, the evidence lives
across four systems, and reason-code requirements are specialist knowledge.

That reading is the same one Track 4 of this buildathon states as the 2026
builder consensus: verification capacity, not generation speed, is the
bottleneck. The one-third intercept in §1 is that claim, measured.