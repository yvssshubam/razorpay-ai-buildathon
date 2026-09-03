"""Disputes have deadlines, so triage is a sequential problem, not a single shot.

WHY #2 AND #4 ARE ONE MODULE. A deadline on its own changes nothing measurable.
If no evidence ever arrives, deciding on day 0 and deciding on day 29 produce
the same decision from the same inputs, and a state machine that waits and then
decides identically has cost a lot of code to do nothing. The deadline only
acquires value when something can arrive before it expires, which means a
response model, which is item 4. Built separately they are a feature with no
result and a result with no feature.

WHAT IS ASSUMED, AND HOW IT IS HANDLED. Razorpay's documentation states the
issuing bank returns a verdict in 15 to 30 days; it does not publish the
merchant's evidence window, and no reliable figure for Indian merchant response
behaviour is publicly available. So two numbers here are chosen rather than
measured:

    RESPONSE_WINDOW_DAYS   how long the merchant has
    response rate          how often a prompted merchant actually answers

Neither is asserted as a point estimate. Both are swept, and results are
reported as curves, for the same reason the four cost constants are swept: a
conclusion that survives every value of an unmeasured parameter does not depend
on guessing it. Quoting a single number here would be inventing the input and
then reporting the output as a finding.

THE LINK TO INGESTION IS MULTIPLICATIVE, AND THAT IS THE INTERESTING PART. A
merchant "responding" means attaching a document, and a document only becomes an
artifact if agent/ingest.py extracts a reference from it. So the effective
response rate is the merchant's willingness times extraction recovery. On the
current measurements that is a large discount: rendered documents recover at
42.7% with the deterministic router, so a merchant population that answers 60%
of prompts delivers usable evidence on roughly 26% of them. Ingestion accuracy
is not a side quest to this feature, it is a multiplier on it.

WHAT THE STATE MACHINE MAY NOT DO. Wait past expiry. A dispute that reaches its
deadline is decided on what exists, because an undecided dispute at expiry is an
automatic loss, which is strictly worse than the accept the EV rule would have
chosen on day 0. The terminal transition is not optional and is asserted rather
than trusted.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import baselines                    # noqa: E402
import distributions_ref as dist    # noqa: E402
import metrics                      # noqa: E402

# Derived from Razorpay's published 15-to-30-day verdict window: the merchant's
# evidence has to be in well before the bank rules, so the window is modelled as
# the short end of that range. Swept from 3 to 30 below, and no result in this
# module depends on the default.
RESPONSE_WINDOW_DAYS = 15

# States. Deliberately few: every extra state is a transition that has to be
# justified, and this problem has one real question -- wait or decide.
OPEN, PROMPTED, RESPONDED, EXPIRED, DECIDED = (
    "open", "prompted", "responded", "expired", "decided")


class DisputeClock:
    """The lifecycle of one dispute under a deadline.

    Deliberately not a general workflow engine. Four transitions, each one
    corresponding to something that actually happens to a chargeback.
    """

    def __init__(self, dispute, window=RESPONSE_WINDOW_DAYS):
        self.d = dispute
        self.window = window
        self.opened = dispute.get("dispute_day", 0)
        self.state = OPEN
        self.day = 0
        self.log = []

    @property
    def days_left(self):
        return self.window - self.day

    def _note(self, event, **kw):
        self.log.append({"day": self.day, "state": self.state,
                         "event": event, **kw})

    def prompt(self):
        """Ask the merchant for the missing records. Costs nothing to send."""
        if self.state != OPEN:
            return False
        self.state = PROMPTED
        self._note("prompted", days_left=self.days_left)
        return True

    def respond(self, artifacts):
        """The merchant supplies records, already through ingestion."""
        if self.state != PROMPTED:
            return False
        self.state = RESPONDED
        self._note("responded", records=len(artifacts))
        return True

    def tick(self, days=1):
        self.day += days
        if self.state == PROMPTED and self.days_left <= 0:
            self.state = EXPIRED
            self._note("expired")
        return self.state

    def must_decide(self):
        """True when waiting is no longer an option.

        An undecided dispute at expiry is an automatic loss, which is strictly
        worse than the accept the EV rule would have chosen on day 0. So this
        is a hard boundary, not a preference.
        """
        return self.state in (RESPONDED, EXPIRED) or self.days_left <= 0


def simulate(disputes, evidence_fn, response_rate, window=RESPONSE_WINDOW_DAYS,
             contest_cost=None, seed=11):
    """Run the queue to completion and return net rupees plus a state census.

    evidence_fn(dispute) returns the records a responding merchant would supply,
    or None if there is nothing to ask for. It is injected rather than imported
    so this module does not depend on the serve layer, and so a caller can pass
    an ingestion-discounted version of it.

    response_rate is the probability a prompted merchant answers in time. It is
    the parameter, not a constant: every caller sweeps it.
    """
    import random as _r

    cost = dist.CONTEST_COST if contest_cost is None else contest_cost
    rng = _r.Random(seed)

    census = {OPEN: 0, PROMPTED: 0, RESPONDED: 0, EXPIRED: 0}
    decisions, records = [], []

    for d in disputes:
        clock = DisputeClock(d, window)
        supplied = None

        ask = evidence_fn(d)
        if ask:
            clock.prompt()
            if rng.random() < response_rate:
                # Responded on some day inside the window. The exact day does
                # not change the decision, only whether it arrived at all, so
                # it is not modelled: adding a response-time distribution would
                # be a second invented parameter buying no extra fidelity.
                clock.respond(ask)
                supplied = ask
            else:
                clock.tick(window)      # ran out the clock

        census[clock.state if clock.state != DECIDED else EXPIRED] += 1

        subject = _with_records(d, supplied) if supplied else d
        decisions.append(baselines.agent(subject, cost))
        records.append(subject)

    return {
        "net_rupees": metrics.net_rupee_impact(records, decisions, cost),
        "response_rate": response_rate,
        "window": window,
        "census": census,
        "prompted": census[PROMPTED] + census[RESPONDED] + census[EXPIRED],
        "responded": census[RESPONDED],
    }


def _with_records(dispute, artifacts):
    """A copy of the dispute with supplied records folded in.

    Dated one day before the dispute for the same reason serve/evidence.py does
    it: a record dated on or after the dispute is stale and cannot satisfy the
    rulebook, so a merchant cannot fix a late document by sending it now.
    """
    import copy

    out = copy.deepcopy(dispute)
    arts = out.setdefault("artifacts", {})
    present = out.setdefault("present_evidence", [])
    dday = out.get("dispute_day", 0)

    for i, a in enumerate(artifacts):
        kind = a["kind"]
        aid = f"resp_{kind[:12]}_{i}"
        arts[aid] = {"artifact_id": aid, "kind": kind,
                     "api_field": a.get("api_field"),
                     "created_day": dday - 1, "present": True,
                     "value": a.get("value") or f"{kind}:supplied",
                     "provenance": "merchant"}
        if kind not in present:
            present.append(kind)
    return out