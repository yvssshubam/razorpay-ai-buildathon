"""The six metrics. Three need no labels; three do.

TWO DEFINITIONS OF "SHOULD HAVE CONTESTED"
------------------------------------------
`_winnable`  : we would have won it. Pure winnability.
`_ev`        : contesting it had positive expected value at this contest cost.

These disagree, and the disagreement is the product thesis. Holdout case D00187:
Rs 35,535 at a true win probability of 0.18 returns Rs 6,245 expected against a
Rs 250 cost (at the standard domestic recovery of 0.9764; was Rs 5,431 under
the old, invented 0.85). Contesting is correct and it loses roughly four times
in five, so it is a MISS under _winnable and a HIT under _ev. Both are right.
170 of the agent's 196 contested losses are of this shape -- RE-MEASURE this
count after the recovery-fraction change.

The declines run the other way and are bounded by the arithmetic: at p = 0.8 a
case must be under Rs 320 to be a correct decline (0.8 * A * 0.9764 > 250
gives A > 320.1; was Rs 368 under the old 0.85). Amex sits at 0.9646 and so
has a slightly higher threshold. Any worked example above that amount
contests -- check the sign before writing one down.

Report both. The gap between them is the money triage saves.

THREE-STATE OUTCOMES
--------------------
submitted / accepted / escalated. Escalated cases cost the full assembly plus
human review and are resolved at HUMAN_RESOLVE_RATE; unresolved ones forfeit
like an accept.

ONE SOURCE OF TRUTH FOR THE ESCALATION COST
-------------------------------------------
`escalation_cost()` below is the only place that says what a blocked packet
costs. eval/baselines.py and serve/adapter.py must both call it rather than
recomputing the sum. They previously did recompute it, and drifted: the decision
priced an escalation at HUMAN_REVIEW_COST while the scorer charged
CONTEST_COST + HUMAN_REVIEW_COST, so the agent escalated cases it was then
penalised for. Do not reintroduce a second copy of this arithmetic.
"""
import distributions_ref as dist


def escalation_cost(contest_cost):
    """What a packet that reaches the human queue costs, end to end.

    The packet was assembled before it was found to be short, so the assembly
    cost is already spent. A person then has to pick it up.

    THE SINGLE DEFINITION. Import this; do not re-add the two terms by hand.
    """
    return contest_cost + dist.HUMAN_REVIEW_COST


# ---------------------------------------------------------------- no labels

def packet_completeness(disputes, decisions):
    """For each SUBMITTED packet, did it contain every evidence type the reason
    code requires? Escalated packets are excluded -- they were never submitted.

    NOTE ON THE CEILING. A packet is submitted only when it is NOT blocked, and
    a packet is blocked precisely when the surviving claims fail to cover the
    reason code's requirement. So on the submitted set this function cannot
    return anything below 1.0. That is a property of the pipeline, not a result.
    The completeness figure worth reporting is the one measured across ALL
    packets in the verifier harness (agent/verify.py), which includes the
    blocked ones.
    """
    subs = [(d, x) for d, x in zip(disputes, decisions) if x["submitted"]]
    if not subs:
        return None  # None, not 1.0: 'no packets' is not 'perfect packets'
    scores = []
    for d, x in subs:
        req = set(d["required_evidence"])
        got = set(x.get("packet_present", []))
        scores.append(len(req & got) / max(len(req), 1))
    return sum(scores) / len(scores)


def hallucination_rate(decisions):
    """Fraction of claims citing evidence absent from the source records.
    Counted only on SUBMITTED packets -- what actually reached the network.

    NOTE ON THE FLOOR. Two things hold this at zero and neither is a finding.
    Unsupported claims are stripped before submission, and the generator applies
    staleness per CASE rather than per artifact, so a case with stale evidence
    has all of it stale, always blocks, and never reaches this function. The
    mixed packet that would produce a non-zero rate is never generated.

    The hallucination rate worth reporting is the one measured on the real
    drafting path with injected faults (agent/verify.py), not this one.
    """
    total = unsupported = 0
    for x in decisions:
        if not x["submitted"]:
            continue
        for c in x.get("claims", []):
            total += 1
            if not c.get("supported", False):
                unsupported += 1
    return (unsupported / total) if total else None


def human_queue_load(decisions):
    return sum(1 for x in decisions if x["blocked"])


def outcome_mix(decisions):
    mix = {"submitted": 0, "accepted": 0, "escalated": 0}
    for x in decisions:
        mix[x["outcome"]] += 1
    return mix


# ------------------------------------------------------------- needs labels

def _should_contest(dispute, contest_cost, definition):
    """Ground truth for the two definitions.

    KNOWN ASYMMETRY, stated rather than silently carried. The "ev" definition
    prices every dispute at contest_cost, including cases whose packet would be
    blocked and which the agent therefore prices at escalation_cost(). So the
    label is more permissive than the policy: it asks "was this worth contesting
    if the packet were free to assemble", not "was it worth contesting given
    what it would actually have cost".

    That is deliberate -- the label should describe the dispute, not the
    policy's own cost model, or the two would be circular. But it means EV
    recall understates the agent on blocked cases, and EV precision overstates
    it. Tier E is where this shows up most.
    """
    if definition == "winnable":
        return dispute["label_won"]
    ev = (dispute["_true_p_win"] * dispute["amount"]
          * dist.net_recovery(dispute.get("network")))
    return ev > contest_cost


def precision_recall(disputes, decisions, contest_cost, definition="winnable"):
    tp = fp = fn = 0
    for d, x in zip(disputes, decisions):
        should = _should_contest(d, contest_cost, definition)
        did = x["contest"]
        if did and should:
            tp += 1
        elif did and not should:
            fp += 1
        elif not did and should:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return precision, recall


def cost_of_being_wrong(disputes, decisions, contest_cost):
    """Rupees spent contesting losers, plus rupees forfeited by accepting
    winnable cases. The false-positive cost the track explicitly asks for.

    `left_behind` nets off the contest cost: winning a case you accepted would
    have required spending contest_cost to get there, so the money actually
    forfeited is the recovery MINUS what the attempt would have cost. The
    earlier version counted the gross recovery and overstated the loss by
    contest_cost per case.
    """
    paid_to_lose = left_behind = 0.0
    for d, x in zip(disputes, decisions):
        if x["submitted"] and not d["label_won"]:
            paid_to_lose += contest_cost
        if x["blocked"] and not d["label_won"]:
            paid_to_lose += escalation_cost(contest_cost)
        if x["outcome"] == "accepted" and d["label_won"]:
            forfeited = (d["amount"] * dist.net_recovery(d.get("network"))
                         - contest_cost)
            left_behind += max(forfeited, 0.0)
    return dict(paid_to_lose=round(paid_to_lose, 2),
                left_behind=round(left_behind, 2),
                total=round(paid_to_lose + left_behind, 2))


def net_rupee_impact(disputes, decisions, contest_cost):
    """Recovered, minus contest costs, minus human review costs.

    Escalated cases: the packet was already assembled, a person picks it up,
    and they can rescue HUMAN_RESOLVE_RATE of them. The recovery is therefore
    an expectation per case rather than a simulated draw -- deliberate, so the
    figure does not move between runs on the same data.

    Accepted cases contribute nothing, which is what makes contest_none score
    exactly zero. All figures are gains relative to accepting everything.
    """
    recovered = costs = 0.0
    for d, x in zip(disputes, decisions):
        net = d["amount"] * dist.net_recovery(d.get("network"))
        if x["submitted"]:
            costs += contest_cost
            if d["label_won"]:
                recovered += net
        elif x["blocked"]:
            costs += escalation_cost(contest_cost)
            if d["label_won"]:
                recovered += net * dist.HUMAN_RESOLVE_RATE
    return round(recovered - costs, 2)


def per_tier_breakdown(disputes, decisions, contest_cost):
    out = {}
    for t in "ABCDE":
        idx = [i for i, d in enumerate(disputes) if d["_tier"] == t]
        if not idx:
            continue
        ds = [disputes[i] for i in idx]
        de = [decisions[i] for i in idx]
        pw, rw = precision_recall(ds, de, contest_cost, "winnable")
        pe, re_ = precision_recall(ds, de, contest_cost, "ev")
        out[t] = dict(n=len(idx),
                      precision_winnable=round(pw, 3), recall_winnable=round(rw, 3),
                      precision_ev=round(pe, 3), recall_ev=round(re_, 3),
                      net_rupees=net_rupee_impact(ds, de, contest_cost))
    return out