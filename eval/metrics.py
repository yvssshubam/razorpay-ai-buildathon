"""The six metrics. Three need no labels; three do.

TWO DEFINITIONS OF "SHOULD HAVE CONTESTED"
------------------------------------------
`_winnable`  : we would have won it. Pure winnability.
`_ev`        : contesting it had positive expected value at this contest cost.

These disagree, and the disagreement is the product thesis. A Rs 450 case we'd
win 80% of the time is a MISS under _winnable and a CORRECT DECLINE under _ev.
Report both. The gap between them is the money triage saves.

THREE-STATE OUTCOMES
--------------------
submitted / accepted / escalated. Escalated cases cost HUMAN_REVIEW_COST and are
resolved at HUMAN_RESOLVE_RATE; unresolved ones forfeit like an accept.
"""
import distributions_ref as dist


# ---------------------------------------------------------------- no labels

def packet_completeness(disputes, decisions):
    """For each SUBMITTED packet, did it contain every evidence type the reason
    code requires? Escalated packets are excluded -- they were never submitted."""
    subs = [(d, x) for d, x in zip(disputes, decisions) if x["submitted"]]
    if not subs:
        return None  # None, not 1.0: 'no packets' is not 'perfect packets'
    scores = []
    for d, x in subs:
        req = set(d["required_evidence"])
        got = set(x.get("packet_present", []))
        scores.append(1.0 if req.issubset(got) else len(req & got) / max(len(req), 1))
    return sum(scores) / len(scores)


def hallucination_rate(decisions):
    """Fraction of claims citing evidence absent from the source records.
    Counted only on SUBMITTED packets -- what actually reached the network."""
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
    if definition == "winnable":
        return dispute["label_won"]
    # ev: would contesting have been positive expected value, knowing the truth?
    ev = dispute["_true_p_win"] * dispute["amount"] * dist.NET_RECOVERY_FRACTION
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
    winnable cases. The false-positive cost the track explicitly asks for."""
    paid_to_lose = left_behind = 0.0
    for d, x in zip(disputes, decisions):
        if x["submitted"] and not d["label_won"]:
            paid_to_lose += contest_cost
        if x["blocked"] and not d["label_won"]:
            paid_to_lose += contest_cost + dist.HUMAN_REVIEW_COST
        if x["outcome"] == "accepted" and d["label_won"]:
            left_behind += d["amount"] * dist.NET_RECOVERY_FRACTION
    return dict(paid_to_lose=round(paid_to_lose, 2),
                left_behind=round(left_behind, 2),
                total=round(paid_to_lose + left_behind, 2))


def net_rupee_impact(disputes, decisions, contest_cost):
    """Recovered, minus contest costs, minus human review costs.
    Escalated cases: human pays review cost, resolves HUMAN_RESOLVE_RATE of them,
    and those then win at the case's true rate."""
    recovered = costs = 0.0
    for d, x in zip(disputes, decisions):
        net = d["amount"] * dist.NET_RECOVERY_FRACTION
        if x["submitted"]:
            costs += contest_cost
            if d["label_won"]:
                recovered += net
        elif x["blocked"]:
            costs += contest_cost + dist.HUMAN_REVIEW_COST
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
