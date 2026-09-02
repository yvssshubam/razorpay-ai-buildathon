"""FastAPI surface over the chargeback pipeline.

    uvicorn app:app --reload --port 8000    (run from serve/)

Every scored field is produced by the existing agent/ and eval/ modules. This
file routes and serialises; it does not decide anything.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import adapter
import evidence
import packet as packet_mod
from store import STORE

app = FastAPI(title="Chargeback Triage and Evidence Agent", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _warm() -> None:
    """Score the whole queue once at boot. Takes a few seconds and means the
    first page load does not."""
    rows, path = adapter.load_disputes()
    for d in rows:
        adapter.score(d)
    m = adapter.model_status()
    print(f"[serve] {len(rows)} disputes from {path}")
    print(f"[serve] p(win) source: {m['source']}"
          + (f" (validation ECE {m['validation']['ece']:.3f})"
             if m["source"] == "learned" else ""))
    if m["source"] != "learned":
        print("[serve] WARNING: models/p_win.pkl not found. Numbers shown are "
              "the hand-written heuristic, not the calibrated model.")


def _decorate(s: dict) -> dict:
    s["status"] = STORE.state_of(s["id"])
    s["decided_by"] = STORE.actor.get(s["id"])
    return s


def _all_scored() -> list[dict]:
    rows, _ = adapter.load_disputes()
    return [_decorate(adapter.summary(evidence.hydrate(d))) for d in rows]


# --------------------------------------------------------------------------

@app.get("/api/health")
def health():
    rows, path = adapter.load_disputes()
    book = adapter.rulebook()
    return {
        "ok": True,
        "disputes": len(rows),
        "dispute_source": path,
        "model": adapter.model_status(),
        "rulebook": {
            "version": book["meta"]["version"],
            "verified_on": str(book["meta"]["verified_on"]),
            "codes": len(book["codes"]),
        },
        "constants": adapter.CONSTANTS,
    }


@app.get("/api/disputes")
def list_disputes(limit: int = 150):
    return _all_scored()[:limit]


@app.get("/api/disputes/{dispute_id}")
def get_dispute(dispute_id: str):
    d = evidence.hydrate(adapter.find(dispute_id))
    if d is None:
        raise HTTPException(404, "No such dispute")
    out = _decorate(adapter.detail(d))
    cid = out["customer"]["customer_id"]
    peers = adapter.customer_disputes(cid)
    out["customer_history"] = {
        "in_queue": len(peers),
        "prior_before_queue": min(
            (int(p.get("prior_disputes") or 0) for p in peers), default=0),
        "total_amount": round(sum(p["amount"] for p in peers), 2),
        "derived": True,
        "items": sorted(
            [{
                "id": p["dispute_id"],
                "amount": round(p["amount"], 2),
                "reason_code": p["reason_code"],
                "status": STORE.state_of(p["dispute_id"]),
                "is_current": p["dispute_id"] == dispute_id,
            } for p in peers],
            key=lambda x: x["id"],
        ),
    }
    return out


class Decision(BaseModel):
    action: str          # contest | accept
    actor: str = "merchant"


@app.post("/api/disputes/{dispute_id}/decision")
def decide(dispute_id: str, body: Decision):
    if body.action not in ("contest", "accept"):
        raise HTTPException(400, "action must be contest or accept")
    try:
        r = STORE.decide(dispute_id, body.action, body.actor)
    except KeyError:
        raise HTTPException(404, "No such dispute")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {**r, "wallet": STORE.wallet()}


# -- merchant-supplied evidence --------------------------------------------
#
# The structural block floor is 40% of the queue: packets that block on
# evidence timestamped after the dispute, or that never existed. No drafting
# improvement removes that share -- but the merchant has the missing record.
# These three routes are the only place in the product where a user action
# changes a score, so read the _INTEGRITY block in evidence.py before touching
# them.

class EvidenceItem(BaseModel):
    kind: str
    value: str
    created_day: int | None = None
    api_field: str | None = None


class EvidenceBody(BaseModel):
    items: list[EvidenceItem]


def _dispute_or_404(dispute_id: str) -> dict:
    d = evidence.hydrate(adapter.find(dispute_id))
    if d is None:
        raise HTTPException(404, "No such dispute")
    return d


@app.get("/api/disputes/{dispute_id}/evidence")
def evidence_gaps(dispute_id: str):
    """What is missing, and what each record is worth on its own."""
    return {**evidence.opportunities(_dispute_or_404(dispute_id)),
            "already_supplied": evidence.supplied_for(dispute_id)}


@app.post("/api/disputes/{dispute_id}/evidence/preview")
def evidence_preview(dispute_id: str, body: EvidenceBody):
    """What WOULD change. Writes nothing, logs nothing, decides nothing."""
    try:
        return evidence.preview(_dispute_or_404(dispute_id),
                                [i.model_dump() for i in body.items])
    except evidence.EvidenceError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/disputes/{dispute_id}/evidence")
def evidence_commit(dispute_id: str, body: EvidenceBody):
    d = _dispute_or_404(dispute_id)
    if STORE.state_of(dispute_id) != "open":
        raise HTTPException(409, "This dispute has already been decided")
    try:
        r = evidence.commit(adapter.find(dispute_id),
                            [i.model_dump() for i in body.items])
    except evidence.EvidenceError as exc:
        raise HTTPException(400, str(exc))

    # Logged with provenance, because a reviewer asking which records the
    # system retrieved and which the merchant handed over should not have to
    # infer it.
    STORE.log("evidence.supplied", dispute_id, {
        "actor": "merchant",
        "kinds": [i.kind for i in body.items],
        "p_win_before": r["before"]["p_win"],
        "p_win_after": r["after"]["p_win"],
        "blocked_before": r["before"]["blocked"],
        "blocked_after": r["after"]["blocked"],
        "recommendation_before": r["before"]["recommendation"],
        "recommendation_after": r["after"]["recommendation"],
    })
    return r


# -- drafting and verification (stages 3 and 4) ----------------------------
#
# The rest of serve/ runs the deterministic half of the pipeline. This route
# runs the half that a model touches: an LLM drafts claims against the
# retrieved artifacts, then the five deterministic checks decide what survives
# and whether the packet may be submitted at all.
#
# On demand, one dispute at a time, because a Gemini call costs a second and
# the free tier allows 500 a day.


@app.post("/api/disputes/{dispute_id}/packet")
def build_packet(dispute_id: str, fault_rate: float | None = None,
                 force: bool = False, redraft: bool = False):
    d = evidence.hydrate(adapter.find(dispute_id))
    if d is None:
        raise HTTPException(404, "No such dispute")

    r = packet_mod.build(d, fault_rate=fault_rate, force=force, redraft=redraft)

    # Logged whether or not it blocked. A packet that was drafted and refused
    # is the event most worth having in an audit trail, not the least.
    if not r["cached"]:
        STORE.log("packet.drafted", dispute_id, {
            "provider": r["provider"],
            "claims_drafted": r["claims_drafted"],
            "kept": len(r["kept"]),
            "stripped": len(r["stripped"]),
            "hallucination_rate": r["hallucination_rate"],
            "blocked": r["blocked"],
            "missing_evidence": r["missing_evidence"],
            "fault_rate": r["fault_rate"],
            "merchant_artifacts": r["merchant_artifacts"],
            "depends_on_merchant_evidence": r["depends_on_merchant_evidence"],
            "redraft": r["redraft"],
            "attempts": r["attempts"],
            "recovered": r["recovered"],
        })
    return r


# -- customers -------------------------------------------------------------

@app.get("/api/customers")
def customers():
    rows, _ = adapter.load_disputes()
    c = adapter.build_customers()
    agg: dict[str, dict] = {}
    for d in rows:
        cid = c["assign"][d["dispute_id"]]
        a = agg.setdefault(cid, {
            **c["people"][cid], "disputes": 0, "amount": 0.0,
            "prior_before_queue": int(d.get("prior_disputes") or 0),
            "codes": set(), "open": 0,
        })
        a["disputes"] += 1
        a["amount"] += d["amount"]
        a["codes"].add(d["reason_code"])
        if STORE.state_of(d["dispute_id"]) == "open":
            a["open"] += 1
    out = []
    for a in agg.values():
        total = a["disputes"] + a["prior_before_queue"]
        out.append({**a, "codes": sorted(a["codes"]), "amount": round(a["amount"], 2),
                    "lifetime_disputes": total, "repeat": total > 1})
    out.sort(key=lambda x: (-x["lifetime_disputes"], -x["amount"]))
    return {"derived": True, "customers": out}


# -- wallet and autonomy ---------------------------------------------------

@app.get("/api/wallet")
def wallet():
    return STORE.wallet()


class TopUp(BaseModel):
    amount: float


@app.post("/api/wallet/topup")
def topup(body: TopUp):
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    return STORE.topup(body.amount)


class Policy(BaseModel):
    mode: str | None = None
    min_p_win: float | None = None
    max_amount: float | None = None
    require_complete_packet: bool | None = None
    daily_spend_cap: float | None = None


@app.get("/api/policy")
def get_policy():
    return {"policy": STORE.policy, "preview": STORE.preview(_all_scored())}


@app.put("/api/policy")
def set_policy(body: Policy):
    for k, v in body.model_dump(exclude_none=True).items():
        STORE.policy[k] = v
    STORE.log("policy.update", None, {"policy": dict(STORE.policy)})
    return {"policy": STORE.policy, "preview": STORE.preview(_all_scored())}


@app.post("/api/agent/run")
def run_agent():
    try:
        return {**STORE.run_agent(_all_scored()), "wallet": STORE.wallet()}
    except ValueError as exc:
        raise HTTPException(409, str(exc))


# -- audit and demo helpers ------------------------------------------------

@app.get("/api/audit")
def audit(limit: int = 100):
    return list(reversed(STORE.audit))[:limit]


@app.post("/api/simulate/settle")
def settle():
    return STORE.settle()


@app.post("/api/simulate/reset")
def reset():
    STORE.reset()
    evidence.reset()
    packet_mod.reset()
    adapter._SCORES.clear()
    return {"ok": True}