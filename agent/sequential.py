"""Ask, wait, or decide: the sequential layer.

WHAT THIS IS. The shipped policy decides every dispute instantly and, where
evidence is missing, asks the merchant once with no notion of whether the ask
is worth making. That is fine when time is free. It is not: a dispute has a
deadline, a prompt costs something, and a merchant who has ignored the last
four requests will probably ignore the fifth.

Perception, memory, action selection under a deadline, all with the arithmetic
visible.

WHAT IS INVENTED. Response rates and response delays are structural
assumptions from generator/enrich_v3.py, not measurements. Nothing here was
fitted to make the policy look good.
"""
from __future__ import annotations

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "eval"), os.path.join(HERE, "..", "serve")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import distributions_ref as dist   # noqa: E402
import metrics                     # noqa: E402

# Cost of sending one evidence request. Not the contest fee: an email and a
# dashboard notification are close to free, but not free, and pricing it at
# zero would make "ask about everything" trivially optimal.
PROMPT_COST = 15.0

# Beta prior on the response rate. Weak on purpose: 2 successes and 3 failures
# is worth about five observations, so a merchant with four disputes is still
# mostly prior. Starting near the population rate rather than at 0.5 would bake
# in a number this project has no basis for.
PRIOR_ALPHA, PRIOR_BETA = 2.0, 3.0

# Assumed days until a response arrives, for merchants with no history. Used
# only to ask "is the window long enough to be worth waiting", never to
# estimate whether they will answer.
#
# 7 is close to the population mean implied by the enrich_v3 archetype mix
# (0.25*2 + 0.30*9 + 0.30*6 + 0.15*20 = 8.0 days), so it is a fair cold-start
# guess. It is NOT a measurement: no public figure for Indian merchant
# response latency exists.
#
# NOTE: this value exceeds the entire response window (3 business days), which
# is why the timeliness term below MUST be a probability rather than a hard
# gate. See decide().
PRIOR_RESPONSE_DAYS = 7


class MerchantMemory:
    """Per-merchant state, updated only from observed outcomes.

    Deliberately tiny. The interesting question is not whether a richer model
    of a merchant helps, it is whether ANY memory changes the decision, and a
    two-counter posterior answers that without inviting the suspicion that the
    result came from an over-parameterised side model.
    """

    def __init__(self):
        self.asked: dict[str, int] = {}
        self.answered: dict[str, int] = {}
        self.delays: dict[str, list] = {}

    def response_rate(self, merchant_id):
        a = self.answered.get(merchant_id, 0)
        n = self.asked.get(merchant_id, 0)
        return (PRIOR_ALPHA + a) / (PRIOR_ALPHA + PRIOR_BETA + n)

    def response_days(self, merchant_id):
        d = self.delays.get(merchant_id) or []
        return sorted(d)[len(d) // 2] if d else PRIOR_RESPONSE_DAYS

    def observe(self, merchant_id, answered, days=None):
        self.asked[merchant_id] = self.asked.get(merchant_id, 0) + 1
        if answered:
            self.answered[merchant_id] = self.answered.get(merchant_id, 0) + 1
            if days is not None:
                self.delays.setdefault(merchant_id, []).append(days)

    def seen(self, merchant_id):
        return self.asked.get(merchant_id, 0)


def _ev(p_win, amount, blocked, cost, network=None):
    gross = p_win * amount * dist.net_recovery(network)
    if blocked:
        return gross * dist.HUMAN_RESOLVE_RATE - metrics.escalation_cost(cost)
    return gross - cost


def decide(dispute, p_win, blocked, p_win_if_supplied, memory, cost):
    """Choose ASK or DECIDE NOW, and return the arithmetic behind it.

    Returns a dict rather than a bare choice because an agent that acts on a
    calculation nobody can see is the thing this whole project argues against.
    """
    mid = dispute["merchant_id"]
    days_left = dispute["deadline_day"] - dispute["dispute_day"]

    ev_now = _ev(p_win, dispute["amount"], blocked, cost,
                 dispute.get("network"))
    ev_supplied = _ev(p_win_if_supplied, dispute["amount"], False, cost,
                      dispute.get("network"))

    p_answer = memory.response_rate(mid)
    expected_days = memory.response_days(mid)

    # An answer that lands after the deadline is worth nothing, but "will it
    # arrive in time" is a PROBABILITY, not a cliff.
    #
    # WHY THIS IS NOT A HARD GATE ANY MORE. It used to be
    # `in_time = days_left > expected_days`, which was harmless while the
    # response window was modelled at 15-45 days and became ABSORBING once the
    # window was corrected to Razorpay's published 3 business days. With
    # days_left in [1, 5] and PRIOR_RESPONSE_DAYS = 7, the gate shut on every
    # merchant with no history; p_useful was forced to zero; ev_ask collapsed
    # to ev_now - PROMPT_COST, which never wins; so the policy never asked,
    # never called memory.observe(), never accumulated delay history, and the
    # prior stayed at 7 forever. A closed loop that cannot open itself.
    #
    # That is a deadlock, not a decision. The "always" policy measured 33
    # in-time answers out of 316 prompts on the same data, so merchants who
    # CAN answer inside the window demonstrably exist -- the gated policy was
    # structurally unable to ever find them.
    #
    # Exponential survival with mean expected_days is the least-committed
    # replacement: it is monotone in both days_left and expected_days, it
    # never returns exactly zero, and it needs no parameter that is not
    # already here. It is a MODELLING CHOICE, not a measurement -- the
    # generator draws one fixed _true_response_days per merchant rather than a
    # distribution, so no functional form here is "correct". It is chosen for
    # keeping the learning loop open, and the sanity check is that at
    # days_left=2, expected_days=7 and the prior p_answer it yields ~0.10,
    # against the 10.4% in-time rate the "always" policy actually observed.
    p_in_time = 1.0 - math.exp(-days_left / max(expected_days, 1e-9))
    p_useful = p_answer * p_in_time

    ev_ask = p_useful * ev_supplied + (1 - p_useful) * ev_now - PROMPT_COST

    return {
        "action": "ask" if ev_ask > ev_now else "decide_now",
        "ev_now": round(ev_now, 2),
        "ev_ask": round(ev_ask, 2),
        "ev_if_supplied": round(ev_supplied, 2),
        "p_answer": round(p_answer, 3),
        "expected_days": expected_days,
        "days_left": days_left,
        "p_in_time": round(p_in_time, 3),
        "p_useful": round(p_useful, 4),
        "history": memory.seen(mid),
    }


LATENT = ("_true_response_rate", "_true_response_days", "_merchant_archetype",
          "_true_p_win", "_tier", "_pattern_id")


def assert_no_leaks():
    """Fail loudly if this module ever READS a latent field.

    Same guard as features.assert_no_leaks, same reason. The result of this
    experiment is only meaningful if the policy estimated response behaviour
    rather than being told it, and "I did not use it" is not a check.

    It looks for subscript and .get access, not bare mentions, because the
    documentation above has to be able to name the fields it promises not to
    touch. An earlier version matched any occurrence and tripped on its own
    docstring, which is a guard that cannot distinguish talking about a thing
    from doing it.
    """
    src = open(os.path.join(HERE, "sequential.py"), encoding="utf-8").read()
    bad = []
    for f in LATENT:
        for pattern in (f'["{f}"]', f"['{f}']", f'get("{f}"', f"get('{f}'"):
            if pattern in src:
                bad.append(f)
                break
    if bad:
        raise AssertionError(f"sequential policy reads latent fields: {bad}")
    return True


assert_no_leaks()