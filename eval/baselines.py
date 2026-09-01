"""Policies. Each maps a dispute -> a decision dict.

OUTCOME IS THREE-STATE, not binary:
  "submitted"  the packet passed verification and went to the issuer
  "accepted"   we chose not to fight; money is forfeited
  "escalated"  the verifier blocked the packet; a human reviews it

Scoring an escalated case as an accept would penalise the agent for the verifier
doing its job. Instead we model the human explicitly with two ASSUMPTIONS
(see HUMAN_* in distributions.py), stated in the README:
  - a human resolves an escalated case and submits it at HUMAN_REVIEW_COST
  - the human's submission wins at the case's true rate, i.e. the human can fix
    the packet but cannot change the facts
That is deliberately conservative: it grants the human no skill bonus.

Two baselines are mandatory. `agent` is a DETERMINISTIC STUB -- an expected-value
rule over observable features, no trained model. The classifier replaces
`_estimate_p_win` on day 5; nothing else changes.
"""
import distributions_ref as dist
import metrics
import os, sys
SUBMITTED = "submitted"
ACCEPTED = "accepted"
ESCALATED = "escalated"


def _build_packet(dispute):
    """Deterministic Stage 2 + Stage 3/4. Returns (packet_kinds, claims, blocked).
    A claim is supported iff its artifact exists and predates the dispute."""
    artifacts = dispute["artifacts"]
    dispute_day = dispute["dispute_day"]

    claims = []
    for aid, art in artifacts.items():
        supported = art["present"] and art["created_day"] < dispute_day
        claims.append({"artifact_id": aid, "supported": supported})

    kept_kinds = {artifacts[c["artifact_id"]]["kind"]
                  for c in claims if c["supported"]}
    required = set(dispute["required_evidence"])
    blocked = not required.issubset(kept_kinds)
    return sorted(kept_kinds), claims, blocked


def _decision(outcome, packet=None, claims=None, p_win=None):
    return {
        "outcome": outcome,
        "contest": outcome in (SUBMITTED, ESCALATED),
        "submitted": outcome == SUBMITTED,
        "blocked": outcome == ESCALATED,
        "packet_present": packet or [],
        "claims": claims or [],
        "p_win": p_win,
    }


def contest_all(dispute, contest_cost=None):
    packet, claims, blocked = _build_packet(dispute)
    return _decision(ESCALATED if blocked else SUBMITTED, packet, claims)


def contest_none(dispute, contest_cost=None):
    return _decision(ACCEPTED)


_P_WIN_SOURCE = None


def _heuristic_p_win(dispute):
    """The original hand-written rule. Kept as an ablation baseline: reporting
    the learned model against this shows how much the model actually adds over
    a sensible EV rule a competent analyst could write in an afternoon."""
    required = dispute["required_evidence"]
    completeness = (len(set(dispute["present_evidence"]) & set(required))
                    / max(len(required), 1))
    p = 0.5
    p += 0.25 * (completeness - 0.5)
    if not dispute["address_match"]:
        p -= 0.15
    p -= 0.05 * dispute["prior_disputes"]
    if dispute["new_device"]:
        p -= 0.10
    _, _, blocked = _build_packet(dispute)
    if blocked:
        p -= 0.20
    return min(max(p, 0.02), 0.95)
def _estimate_p_win(dispute):
    """Learned model if one is on disk, heuristic otherwise. Prints which, once,
    so a run is never ambiguous about what produced the numbers.

    CB_P_WIN=heuristic forces the hand-written rule, which turns the two
    estimators into an ablation: how much does the trained model actually add
    over an EV rule an analyst could write in an afternoon?
    """
    global _P_WIN_SOURCE
    import os, sys

    if os.environ.get("CB_P_WIN") == "heuristic":
        if _P_WIN_SOURCE is None:
            _P_WIN_SOURCE = "heuristic"
            print("[p_win] heuristic (forced via CB_P_WIN)")
        return _heuristic_p_win(dispute)

    agent_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "agent")
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)
    try:
        from classifier import predict_p_win
        if _P_WIN_SOURCE is None:
            _P_WIN_SOURCE = "learned"
            print("[p_win] calibrated classifier")
        return predict_p_win(dispute)
    except Exception as exc:
        if _P_WIN_SOURCE is None:
            _P_WIN_SOURCE = "heuristic"
            print(f"[p_win] heuristic fallback ({type(exc).__name__})")
        return _heuristic_p_win(dispute)


def agent(dispute, contest_cost=None):
    """Expected value, priced against the branch the case will ACTUALLY take.

    The packet is built before the decision, not after, because _build_packet is
    deterministic and independent of the choice. A case whose packet will be
    blocked does not cost CONTEST_COST alone -- the packet is assembled and
    THEN a person picks it up, so it costs metrics.escalation_cost(), which is
    CONTEST_COST + HUMAN_REVIEW_COST, and it only pays out on the fraction a
    human can resolve. Pricing every contest at CONTEST_COST systematically
    overspends on exactly the cases least able to repay it. That sum lives in
    metrics.escalation_cost() and is imported, never re-added here: this
    function held the last hand-written copy of it, which is how E3 happened.

    CB_P_FLOOR sets a hard confidence floor beneath the EV test: never contest
    below this p(win) whatever the amount. Blunt instrument, swept in eval.
    """
    import os
    cc = dist.CONTEST_COST if contest_cost is None else contest_cost
    p = _estimate_p_win(dispute)

    floor = float(os.environ.get("CB_P_FLOOR", 0.0))
    if p < floor:
        return _decision(ACCEPTED, p_win=round(p, 3))

    packet, claims, blocked = _build_packet(dispute)
    gross = p * dispute["amount"] * dist.NET_RECOVERY_FRACTION

    if blocked:
        ev = gross * dist.HUMAN_RESOLVE_RATE - metrics.escalation_cost(cc)
    else:
        ev = gross - cc

    # CB_EV_THRESHOLD shifts the accept/contest boundary off zero, in rupees.
    # Negative accepts marginally EV-negative cases (useful if the model is
    # under-confident); positive demands a margin (useful if over-confident).
    # Swept two-sided in run_eval.py --ev-sweep; default 0 changes nothing.
    thr = float(os.environ.get("CB_EV_THRESHOLD", 0.0))
    if ev <= thr:
        return _decision(ACCEPTED, p_win=round(p, 3))
    return _decision(ESCALATED if blocked else SUBMITTED,
                     packet, claims, round(p, 3))
POLICIES = {
    "contest_all": contest_all,
    "contest_none": contest_none,
    "agent": agent,
}