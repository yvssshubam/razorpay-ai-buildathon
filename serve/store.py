"""In-memory session state: decisions, wallet, autonomy policy, audit log.

Deliberately not a database. Restarting the server resets the demo, which is
what you want when you are recording a walkthrough twice.

The wallet is not decoration. CONTEST_COST and HUMAN_REVIEW_COST are the exact
constants the EV rule already prices against, so every rupee the wallet moves
is a rupee the policy in eval/baselines.py assumed it would spend. Making that
spend visible turns net rupee impact from a number in a results file into a
balance the merchant reads.
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
            "max_amount": 15_000.0,
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

        cost = (adapter.CONSTANTS["human_review_cost"] if s["blocked"]
                else adapter.CONSTANTS["contest_cost"])
        if self.balance < cost:
            raise ValueError("Wallet balance is below the cost of this contest")

        self.status[dispute_id] = ESCALATED if s["blocked"] else QUEUED
        self.actor[dispute_id] = actor
        self._post("debit", cost, dispute_id,
                   "Human review" if s["blocked"] else "Contest fee")
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
    def eligible(self, s: dict, budget_left: float) -> tuple[bool, str]:
        """Delegation gate. Distinct from the EV rule on purpose.

        The EV rule decides whether contesting is worth it. This decides whether
        the agent may act without asking. The floor sweep already showed the EV
        rule needs no confidence floor to decide well; this floor exists to
        bound blast radius, not to improve accuracy.
        """
        p = self.policy
        if s["recommendation"] != "contest":
            return False, "policy recommends accepting"
        if s["p_win"] < p["min_p_win"]:
            return False, f"p(win) {s['p_win']:.2f} below your {p['min_p_win']:.2f} bar"
        if s["amount"] > p["max_amount"]:
            return False, f"amount above your ₹{p['max_amount']:,.0f} ceiling"
        if p["require_complete_packet"] and s["blocked"]:
            return False, "packet is short of the rulebook requirement"
        cost = (adapter.CONSTANTS["human_review_cost"] if s["blocked"]
                else adapter.CONSTANTS["contest_cost"])
        if cost > budget_left:
            return False, "daily spend cap reached"
        if cost > self.balance:
            return False, "wallet balance too low"
        return True, "within your limits"

    def preview(self, scored: list[dict]) -> dict:
        """What delegation would do to the open queue, without doing it."""
        budget = self.policy["daily_spend_cap"] - self.spent_today()
        auto, held, spend = [], [], 0.0
        for s in scored:
            if self.state_of(s["id"]) != OPEN:
                continue
            ok, why = self.eligible(s, budget - spend)
            if ok:
                cost = (adapter.CONSTANTS["human_review_cost"] if s["blocked"]
                        else adapter.CONSTANTS["contest_cost"])
                spend += cost
                auto.append({"id": s["id"], "amount": s["amount"],
                             "p_win": s["p_win"], "cost": cost})
            else:
                held.append({"id": s["id"], "amount": s["amount"],
                             "p_win": s["p_win"], "reason": why})
        return {
            "auto": auto, "held": held,
            "auto_count": len(auto), "held_count": len(held),
            "projected_spend": round(spend, 2),
            "projected_recovery": round(
                sum(a["amount"] * a["p_win"] * adapter.CONSTANTS["net_recovery_fraction"]
                    for a in auto), 2),
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
        return {"acted": acted, "held": plan["held"]}

    # -- settlement simulator ---------------------------------------------
    def settle(self) -> dict:
        """Resolve queued contests against the held-out ground-truth label.

        This is a DEMO device and the UI says so. It exists because net rupee
        impact is the headline metric and it cannot be shown without outcomes.
        The label is never read during scoring, only here, after a decision has
        already been committed.
        """
        results = []
        frac = adapter.CONSTANTS["net_recovery_fraction"]
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
                credit = d["amount"] * frac
                self._post("credit", credit, did, "Recovered from issuer")
                self.status[did] = WON
            else:
                credit = 0.0
                self.status[did] = LOST
            self.log("verdict", did, {"won": won, "credited": round(credit, 2)})
            results.append({"id": did, "won": won, "credited": round(credit, 2)})
        return {"settled": results, "wallet": self.wallet()}


STORE = Store()
