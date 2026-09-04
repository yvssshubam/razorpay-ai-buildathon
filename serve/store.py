"""In-memory session state: decisions, wallet, autonomy policy, audit log.

Deliberately not a database. Restarting the server resets the demo, which is
what you want when you are recording a walkthrough twice.

The wallet is not decoration. CONTEST_COST and HUMAN_REVIEW_COST are the exact
constants the EV rule already prices against, so every rupee the wallet moves
is a rupee the policy in eval/baselines.py assumed it would spend. Making that
spend visible turns net rupee impact from a number in a results file into a
balance the merchant reads.

That claim only holds if the wallet debits what the policy priced. It used to
charge HUMAN_REVIEW_COST alone for a blocked packet while the policy and the
scorer charged CONTEST_COST + HUMAN_REVIEW_COST -- Rs 250 short on every
escalation. `_cost_of` below is now the single place this module decides what
anything costs.
"""
from __future__ import annotations

import itertools
import zlib
from datetime import datetime, timezone

import adapter

OPEN = "open"
QUEUED = "queued"          # merchant or agent chose to contest, pre-verdict
ESCALATED = "escalated"    # verifier blocked; a person has to look
ACCEPTED = "accepted"      # not contested
WON = "won"
LOST = "lost"

_seq = itertools.count(1)

# Reasons a case is held back, in the order a merchant should read them: what
# the policy decided, then what their own limits did, then the budget.
HOLD_POLICY = "policy"
HOLD_PWIN = "p_win"
HOLD_AMOUNT = "amount"
HOLD_PACKET = "packet"
HOLD_BUDGET = "budget"
HOLD_BALANCE = "balance"

HOLD_LABEL = {
    HOLD_POLICY:  "The policy recommends accepting",
    HOLD_PWIN:    "Below your win-probability bar",
    HOLD_AMOUNT:  "Above your amount ceiling",
    HOLD_PACKET:  "Packet is short of the rulebook requirement",
    HOLD_BUDGET:  "Daily spend cap reached",
    HOLD_BALANCE: "Wallet balance too low",
}
HOLD_ORDER = [HOLD_POLICY, HOLD_PWIN, HOLD_AMOUNT, HOLD_PACKET,
              HOLD_BUDGET, HOLD_BALANCE]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cost_of(scored: dict) -> float:
    """What acting on this case costs the wallet.

    A blocked packet was already assembled before it was found short, so the
    assembly cost is spent on top of the human review. Mirrors
    eval/metrics.py::escalation_cost, which both the EV rule and the scorer use.

    ONE definition for this module. It was previously written out at three call
    sites -- decide(), eligible() and preview() -- and all three were wrong in
    the same way.
    """
    C = adapter.CONSTANTS
    if scored["blocked"]:
        return C["contest_cost"] + C["human_review_cost"]
    return C["contest_cost"]


def _ev_of(scored: dict) -> float:
    return float(scored["ev"]["value"])


# Days of slack before the response window shuts. A case with no deadline
# overlay is treated as maximally slack, so a dispute whose deadline is simply
# unknown never jumps ahead of one that is genuinely expiring.
_MAX_SLACK = 99


def _slack_of(scored: dict) -> int:
    d = scored.get("days_left")
    return _MAX_SLACK if d is None else int(d)


class Store:
    def __init__(self) -> None:
        self.reset()

    # -- lifecycle ---------------------------------------------------------
    def reset(self) -> None:
        self.status: dict[str, str] = {}
        self.actor: dict[str, str] = {}
        self.audit: list[dict] = []
        self.ledger: list[dict] = []
        self.opening_balance = 25_000.0
        self.policy = {
            "mode": "manual",              # "manual" | "delegated"
            "min_p_win": 0.70,
            "max_amount": 5_000.0,
            "require_complete_packet": True,
            "daily_spend_cap": 5_000.0,
        }

    # -- wallet ------------------------------------------------------------
    def _post(self, kind: str, amount: float, dispute_id: str | None, note: str) -> None:
        self.ledger.append({
            "seq": next(_seq),
            "at": _now(),
            "kind": kind,          # debit | credit | topup
            "amount": round(amount, 2),
            "dispute_id": dispute_id,
            "note": note,
        })

    @property
    def spent(self) -> float:
        return sum(l["amount"] for l in self.ledger if l["kind"] == "debit")

    @property
    def recovered(self) -> float:
        return sum(l["amount"] for l in self.ledger if l["kind"] == "credit")

    @property
    def topped_up(self) -> float:
        return sum(l["amount"] for l in self.ledger if l["kind"] == "topup")

    @property
    def balance(self) -> float:
        return self.opening_balance + self.topped_up + self.recovered - self.spent

    def spent_today(self) -> float:
        today = _now()[:10]
        return sum(l["amount"] for l in self.ledger
                   if l["kind"] == "debit" and l["at"][:10] == today)

    def wallet(self) -> dict:
        return {
            "opening_balance": self.opening_balance,
            "balance": round(self.balance, 2),
            "spent": round(self.spent, 2),
            "recovered": round(self.recovered, 2),
            "net": round(self.recovered - self.spent, 2),
            "spent_today": round(self.spent_today(), 2),
            "daily_spend_cap": self.policy["daily_spend_cap"],
            "ledger": list(reversed(self.ledger))[:60],
            "constants": adapter.CONSTANTS,
        }

    def topup(self, amount: float) -> dict:
        self._post("topup", amount, None, "Merchant added funds")
        self.log("wallet.topup", None, {"amount": amount})
        return self.wallet()

    # -- audit -------------------------------------------------------------
    def log(self, event: str, dispute_id: str | None, payload: dict) -> None:
        self.audit.append({
            "seq": next(_seq),
            "at": _now(),
            "event": event,
            "dispute_id": dispute_id,
            "policy_mode": self.policy["mode"],
            "rulebook_version": adapter.rulebook()["meta"]["version"],
            **payload,
        })

    # -- decisions ---------------------------------------------------------
    def state_of(self, dispute_id: str) -> str:
        return self.status.get(dispute_id, OPEN)

    def decide(self, dispute_id: str, action: str, actor: str) -> dict:
        """action: contest | accept.  actor: merchant | agent."""
        d = adapter.find(dispute_id)
        if d is None:
            raise KeyError(dispute_id)
        if self.state_of(dispute_id) != OPEN:
            raise ValueError(f"{dispute_id} already {self.state_of(dispute_id)}")

        s = adapter.score(d)

        if action == "accept":
            self.status[dispute_id] = ACCEPTED
            self.actor[dispute_id] = actor
            self.log("decision.accept", dispute_id, {
                "actor": actor, "p_win": s["p_win"], "ev": s["ev"]["value"],
                "forfeited": round(d["amount"], 2),
            })
            return {"status": ACCEPTED, "charged": 0.0}

        cost = _cost_of(s)
        if self.balance < cost:
            raise ValueError("Wallet balance is below the cost of this contest")

        self.status[dispute_id] = ESCALATED if s["blocked"] else QUEUED
        self.actor[dispute_id] = actor
        self._post("debit", cost, dispute_id,
                   "Assembly + human review" if s["blocked"] else "Contest fee")
        self.log("decision.contest", dispute_id, {
            "actor": actor,
            "p_win": s["p_win"],
            "ev": s["ev"]["value"],
            "cost": cost,
            "blocked": s["blocked"],
            "packet": s["packet_present"],
            "claims_supported": s["claims_supported"],
            "claims_total": s["claims_total"],
        })
        return {"status": self.status[dispute_id], "charged": cost}

    # -- autonomy ----------------------------------------------------------
    def eligible(self, s: dict, budget_left: float) -> tuple[bool, str, str]:
        """Delegation gate. Distinct from the EV rule on purpose.

        The EV rule decides whether contesting is worth it. This decides whether
        the agent may act without asking. The floor sweep already showed the EV
        rule needs no confidence floor to decide well; this floor exists to
        bound blast radius, not to improve accuracy.

        Returns (ok, reason_code, human_text). The code lets the UI group holds
        by cause instead of listing hundreds of rows in dispute-id order, which
        hides which constraint is actually binding.

        NOTE on min_p_win. If the calibrated model fails to load, eval/baselines
        falls back to a heuristic with a low reachable maximum, so a high bar
        would silently hold everything. /api/health reports which estimator is
        live; the UI should show it.
        """
        p = self.policy
        if s["recommendation"] != "contest":
            return False, HOLD_POLICY, "policy recommends accepting"
        if s["p_win"] < p["min_p_win"]:
            return False, HOLD_PWIN, \
                f"p(win) {s['p_win']:.2f} below your {p['min_p_win']:.2f} bar"
        if s["amount"] > p["max_amount"]:
            return False, HOLD_AMOUNT, \
                f"amount above your ₹{p['max_amount']:,.0f} ceiling"
        if p["require_complete_packet"] and s["blocked"]:
            return False, HOLD_PACKET, "packet is short of the rulebook requirement"
        cost = _cost_of(s)
        if cost > budget_left:
            return False, HOLD_BUDGET, "daily spend cap reached"
        if cost > self.balance:
            return False, HOLD_BALANCE, "wallet balance too low"
        return True, "", "within your limits"

    def preview(self, scored: list[dict]) -> dict:
        """What delegation would do to the open queue, without doing it.

        EXPIRING FIRST, THEN BEST VALUE PER RUPEE. The queue is ordered by days
        of slack before the budget is walked, and within a slack band by
        expected value per rupee of cost. Iterating in arrival order made the
        daily cap pick an arbitrary subset; iterating by raw value spent the cap
        on whatever was worth most even when it was not the thing about to
        expire. See the sort below for why urgency comes first.

        HOLDS ARE GROUPED. A case the policy declined is unreachable by any
        slider; a case stopped by the budget would be picked up by raising the
        cap. Presenting both as one undifferentiated list, ordered by dispute
        id, is why the limits appeared to do nothing when the cap was the thing
        actually binding.
        """
        budget = self.policy["daily_spend_cap"] - self.spent_today()
        opens = [s for s in scored if self.state_of(s["id"]) == OPEN]
        # URGENCY FIRST, THEN VALUE PER RUPEE.
        #
        # Sorting on value alone spends today's cap on whatever is worth most,
        # ignoring that most of it does not expire today. Razorpay allows 3
        # business days to represent a chargeback, so a case with 3 days of
        # slack is still there tomorrow at no cost; a case with 1 day left is
        # act-now-or-lose-it. Deferring the first costs nothing. Deferring the
        # second costs the whole dispute.
        #
        # The key is a tuple, compared left to right: slack picks the band,
        # value per rupee orders within it. So a Rs 1,800 case with 1 day left
        # outranks a Rs 3,000 case with 3 days, because tomorrow only one of
        # them still exists.
        #
        # Value per rupee, not raw value, because the cap is denominated in
        # rupees: a blocked packet costs 4x a clean one, so raw EV let
        # expensive cases crowd out cheaper, better-value ones.
        #
        # LIMIT, stated rather than hidden: this is right when tomorrow has
        # spare capacity. With a queue far deeper than the daily cap, tomorrow
        # is saturated too, and strict day-banding can spend on small expiring
        # cases while large ones age out. Fixing that needs multi-day planning,
        # which this does not attempt.
        opens.sort(key=lambda s: (_slack_of(s),
                                  -_ev_of(s) / max(_cost_of(s), 1e-9)))

        auto, held, spend = [], [], 0.0
        for s in opens:
            ok, code, why = self.eligible(s, budget - spend)
            if ok:
                cost = _cost_of(s)
                spend += cost
                auto.append({"id": s["id"], "amount": s["amount"],
                             "network": s.get("network"),
                             "days_left": s.get("days_left"),
                             "p_win": s["p_win"], "ev": _ev_of(s), "cost": cost})
            else:
                held.append({"id": s["id"], "amount": s["amount"],
                             "days_left": s.get("days_left"),
                             "p_win": s["p_win"], "ev": _ev_of(s),
                             "reason": why, "reason_code": code})

        groups = []
        for code in HOLD_ORDER:
            items = [h for h in held if h["reason_code"] == code]
            if items:
                groups.append({
                    "code": code,
                    "label": HOLD_LABEL[code],
                    "count": len(items),
                    "amount": round(sum(i["amount"] for i in items), 2),
                    "examples": items[:5],
                })

        # Which constraint is actually deciding the outcome. Without this the
        # merchant moves a slider, sees the count stay where it was, and
        # concludes the control is broken -- when the daily cap is binding.
        exhausted = any(h["reason_code"] == HOLD_BUDGET for h in held)
        binding = HOLD_BUDGET if exhausted else (
            max(groups, key=lambda g: g["count"])["code"] if groups else None)

        recovery = sum(a["amount"] * a["p_win"]
                       * adapter.dist.net_recovery(a.get("network"))
                       for a in auto)

        return {
            "auto": auto, "held": held,
            "auto_count": len(auto), "held_count": len(held),
            "hold_groups": groups,
            "binding_constraint": binding,
            "binding_label": HOLD_LABEL.get(binding) if binding else None,
            "budget_remaining": round(max(budget - spend, 0.0), 2),
            "budget_exhausted": exhausted,
            "projected_spend": round(spend, 2),
            "projected_recovery": round(recovery, 2),
            "projected_net": round(recovery - spend, 2),
        }

    def run_agent(self, scored: list[dict]) -> dict:
        if self.policy["mode"] != "delegated":
            raise ValueError("Autonomy is off. Switch to delegated mode first.")
        plan = self.preview(scored)
        acted = []
        for a in plan["auto"]:
            try:
                r = self.decide(a["id"], "contest", "agent")
                acted.append({**a, **r})
            except ValueError:
                break
        self.log("agent.run", None, {"acted": len(acted),
                                     "spend": sum(a["cost"] for a in acted)})
        return {"acted": acted, "held": plan["held"],
                "hold_groups": plan["hold_groups"]}

    # -- settlement simulator ---------------------------------------------
    def settle(self) -> dict:
        """Resolve queued contests against the held-out ground-truth label.

        This is a DEMO device and the UI says so. It exists because net rupee
        impact is the headline metric and it cannot be shown without outcomes.
        The label is never read during scoring, only here, after a decision has
        already been committed.
        """
        results = []
        rate = adapter.CONSTANTS["human_resolve_rate"]
        for did, st in list(self.status.items()):
            if st not in (QUEUED, ESCALATED):
                continue
            d = adapter.find(did)
            won = bool(d.get("label_won"))
            if st == ESCALATED:
                # The human fixes the packet on HUMAN_RESOLVE_RATE of cases and
                # then wins at the case's true rate. Same assumption the eval
                # harness makes; no skill bonus granted.
                #
                # crc32, not hash(): Python randomises string hashing per
                # process, so hash() would settle the same dispute differently
                # on every restart and the demo would not reproduce.
                won = won and (zlib.crc32(did.encode()) % 100) / 100.0 < rate
            if won:
                credit = d["amount"] * adapter.dist.net_recovery(d.get("network"))
                self._post("credit", credit, did, "Recovered from issuer")
                self.status[did] = WON
            else:
                credit = 0.0
                self.status[did] = LOST
            self.log("verdict", did, {"won": won, "credited": round(credit, 2)})
            results.append({"id": did, "won": won, "credited": round(credit, 2)})
        return {"settled": results, "wallet": self.wallet()}


STORE = Store()