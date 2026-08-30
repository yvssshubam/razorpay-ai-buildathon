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
          + (f" (ECE {m['validation']['ece']:.3f})" if m["source"] == "learned" else ""))
    if m["source"] != "learned":
        print("[serve] WARNING: models/p_win.pkl not found. Numbers shown are "
              "the hand-written heuristic, not the calibrated model.")


def _decorate(s: dict) -> dict:
    s["status"] = STORE.state_of(s["id"])
    s["decided_by"] = STORE.actor.get(s["id"])
    return s


def _all_scored() -> list[dict]:
    rows, _ = adapter.load_disputes()
    return [_decorate(adapter.summary(d)) for d in rows]


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
    d = adapter.find(dispute_id)
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
    return {"ok": True}
