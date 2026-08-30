"""Thin adapter over the existing pipeline. Owns NO decision logic.

Every number this module serves comes out of code that already exists in the
repo:

    p(win)        agent/classifier.py::predict_p_win      (calibrated model)
    decision      eval/baselines.py::agent                (EV rule)
    packet        eval/baselines.py::_build_packet        (deterministic)
    constants     eval/distributions_ref.py               (250/800/0.85/0.80)
    rulebook      rulebook/reason_codes.yaml

If this file ever starts computing a probability or a threshold of its own,
the dashboard has stopped showing the system and started showing a mock.

ONE THING IS CONSTRUCTED HERE AND IT IS LABELLED: customer identity. The
generator emits `prior_disputes` as a scalar and no customer key, so disputes
cannot be grouped by filer. build_customers() derives a consistent identity
join at serve time. It does not touch labels, features, or the model, and it
is flagged as derived in the API response.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from functools import lru_cache

# --- wire the repo's own import layout ------------------------------------
# baselines.py does `import distributions_ref`, i.e. flat imports within eval/.
# classifier.py does `import features`. So both directories go on the path.
def _find_repo() -> str:
    """Walk up from this file until we find the pipeline. Lets serve/ live
    either inside the repo or one level out, without a config change."""
    env = os.environ.get("CB_REPO")
    if env:
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.exists(os.path.join(here, "eval", "baselines.py")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    raise SystemExit(
        "Could not locate the pipeline (eval/baselines.py) above "
        f"{os.path.dirname(os.path.abspath(__file__))}.\n"
        "Set CB_REPO to the repo root, e.g.  CB_REPO=~/razorpay-ai-buildathon uvicorn app:app"
    )


REPO = _find_repo()
for sub in ("eval", "agent", "generator"):
    p = os.path.join(REPO, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import baselines  # noqa: E402
import distributions_ref as dist  # noqa: E402

CONSTANTS = {
    "contest_cost": dist.CONTEST_COST,
    "human_review_cost": dist.HUMAN_REVIEW_COST,
    "net_recovery_fraction": dist.NET_RECOVERY_FRACTION,
    "human_resolve_rate": dist.HUMAN_RESOLVE_RATE,
}

DISPUTE_DAY_EPOCH = date.today() - timedelta(days=20)


# --------------------------------------------------------------------------
# rulebook
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def rulebook() -> dict:
    """Load the YAML rulebook directly.

    Deliberately not routed through generator/rulebook_loader.load_rulebook():
    its PyYAML-free fallback parser looks for a top-level `reason_codes:` key,
    but the file uses `codes:`. Without PyYAML installed that path returns an
    empty rulebook and every packet silently scores as complete.
    """
    path = os.path.join(REPO, "rulebook", "reason_codes.yaml")
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PyYAML is required to read the rulebook. pip install pyyaml"
        ) from exc
    with open(path, encoding="utf-8") as fh:
        book = yaml.safe_load(fh)
    if not book.get("codes"):
        raise SystemExit(f"rulebook at {path} has no `codes:` section")
    return book


def code_meta(code: str) -> dict:
    return rulebook()["codes"].get(str(code), {})


# --------------------------------------------------------------------------
# disputes
# --------------------------------------------------------------------------

def _candidate_paths() -> list[str]:
    env = os.environ.get("CB_DISPUTES")
    if env:
        return [env]
    d = os.path.join(REPO, "data")
    return [os.path.join(d, n) for n in ("holdout.jsonl", "train.jsonl")]


@lru_cache(maxsize=1)
def load_disputes() -> tuple[list[dict], str]:
    for path in _candidate_paths():
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                rows = [json.loads(l) for l in fh if l.strip()]
            return rows, path
    raise SystemExit(
        "No dispute file found. Expected data/holdout.jsonl.\n"
        "Regenerate with:  python generator/generate.py --profile holdout "
        "--n 150 --seed 23 --out data/holdout.jsonl"
    )


def model_status() -> dict:
    """Report whether the calibrated model is actually on disk.

    baselines._estimate_p_win falls back to the hand-written heuristic when the
    pickle is missing. Silently serving heuristic numbers through a UI labelled
    'calibrated model' would be the exact kind of overclaim this project is
    trying not to make, so the banner reads from here.
    """
    try:
        sys.path.insert(0, os.path.join(REPO, "agent"))
        from classifier import _load

        bundle = _load()
        return {
            "source": "learned",
            "calibration": bundle.get("calibration"),
            "n_train": bundle.get("n_train"),
            "validation": bundle.get("validation", {}),
        }
    except Exception as exc:
        return {"source": "heuristic", "error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------
# scoring: straight through to the existing policy
# --------------------------------------------------------------------------

def _day_to_date(day: int) -> str:
    return (DISPUTE_DAY_EPOCH + timedelta(days=int(day))).isoformat()


def evidence_view(d: dict) -> list[dict]:
    """Per required-evidence-kind status, using the same support test as
    baselines._build_packet: present AND created before the dispute."""
    arts = d.get("artifacts") or {}
    dday = d.get("dispute_day", 0)
    by_kind: dict[str, dict] = {}
    for aid, a in arts.items():
        by_kind.setdefault(a.get("kind"), {"artifact_id": aid, **a})

    meta = code_meta(d.get("reason_code"))
    slots = meta.get("required_evidence") or {}

    out = []
    for kind in d.get("required_evidence") or []:
        a = by_kind.get(kind)
        if a is None:
            state = "missing"
        elif not a.get("present"):
            state = "missing"
        elif a.get("created_day", 0) >= dday:
            state = "stale"
        else:
            state = "verified"
        out.append({
            "kind": kind,
            "api_field": slots.get(kind) or (a or {}).get("api_field"),
            "state": state,
            "artifact_id": (a or {}).get("artifact_id"),
            "value": (a or {}).get("value"),
            "created_on": _day_to_date(a["created_day"]) if a and "created_day" in a else None,
        })
    return out


_SCORES: dict[str, dict] = {}


def score(d: dict) -> dict:
    """Cached wrapper. The model, the rulebook and the record are all fixed for
    the life of the process, so a dispute's score cannot change between
    requests. Without this, every page load runs 150 sklearn predictions."""
    did = d["dispute_id"]
    if did not in _SCORES:
        _SCORES[did] = _score_uncached(d)
    return _SCORES[did]


def _score_uncached(d: dict) -> dict:
    """Run the real policy and expose the arithmetic behind it.

    NOTE on `blocked`. baselines._decision sets blocked = (outcome ==
    ESCALATED), which answers "did we escalate", not "is the packet short". A
    case whose packet fails the rulebook but whose EV is negative comes back
    ACCEPTED with blocked=False. Reading the flag off the decision would then
    price the case at CONTEST_COST and display a positive EV beside an accept
    verdict. So the packet is built here directly, which is the same
    deterministic call the policy itself makes.
    """
    packet, claims, blocked = baselines._build_packet(d)
    decision = baselines.agent(d)
    p = decision.get("p_win")
    if p is None:  # defensive: policy returns p on every path today
        p = baselines._estimate_p_win(d)

    gross = p * d["amount"] * dist.NET_RECOVERY_FRACTION
    if blocked:
        # Single definition in eval/metrics.py -- do not re-add the two terms.
        # The packet was already assembled before it was found short, so the
        # assembly cost is spent on top of the human review.
        from metrics import escalation_cost
        cost = escalation_cost(dist.CONTEST_COST)
        ev = gross * dist.HUMAN_RESOLVE_RATE - cost
        branch = "escalated"
    else:
        cost = dist.CONTEST_COST
        ev = gross - cost
        branch = "submitted"

    ev_items = evidence_view(d)
    return {
        "p_win": round(float(p), 4),
        "recommendation": "contest" if decision["contest"] else "accept",
        "outcome_if_contested": branch,
        "blocked": blocked,
        "ev": {
            "gross": round(gross, 2),
            "cost": cost,
            "cost_label": "contest + human review" if blocked else "contest",
            "resolve_rate": dist.HUMAN_RESOLVE_RATE if blocked else None,
            "value": round(ev, 2),
            "positive": ev > 0,
        },
        # From _build_packet, not from the decision: an accepted case still has
        # a packet worth showing the merchant, and baselines returns [] there.
        "packet_present": packet,
        "claims": claims,
        "claims_supported": sum(1 for c in claims if c["supported"]),
        "claims_total": len(claims),
        "evidence": ev_items,
        "completeness": round(
            sum(1 for e in ev_items if e["state"] == "verified") / max(len(ev_items), 1), 3
        ),
    }


# --------------------------------------------------------------------------
# customer identity (DERIVED AT SERVE TIME - see module docstring)
# --------------------------------------------------------------------------

FIRST = ["Rohan", "Priya", "Arjun", "Neha", "Vikram", "Ananya", "Karthik", "Sneha",
         "Aditya", "Meera", "Farhan", "Ishita", "Sameer", "Divya", "Nikhil", "Tanvi",
         "Rahul", "Kavya", "Imran", "Pooja", "Varun", "Ritika", "Yash", "Anjali"]
LAST = ["Mehta", "Shah", "Rao", "Iyer", "Nair", "Gupta", "Menon", "Kulkarni",
        "Verma", "Pillai", "Qureshi", "Bose", "Joshi", "Reddy", "Bhatt", "Desai"]


def _name(i: int) -> str:
    return f"{FIRST[i % len(FIRST)]} {LAST[(i // len(FIRST) + i) % len(LAST)]}"


@lru_cache(maxsize=1)
def build_customers() -> dict:
    """Assign each dispute to a customer so that the record's own
    `prior_disputes` count is exactly satisfied.

    A dispute carrying prior_disputes = k is attached to a customer who already
    has k disputes in the queue. The join is therefore consistent with the
    generated data rather than layered on top of it: a customer's nth dispute
    always reads prior_disputes = n-1.
    """
    rows, _ = load_disputes()
    counts: dict[str, int] = {}
    assign: dict[str, str] = {}
    order: list[str] = []

    for d in rows:
        k = int(d.get("prior_disputes") or 0)
        cid = next((c for c in order if counts[c] == k), None)
        if cid is None:
            cid = f"cust_{len(order):04d}"
            order.append(cid)
            counts[cid] = 0
            if k > 0:
                # No customer had k priors yet. Seed the count so the record's
                # own field stays truthful; those k earlier disputes are before
                # this queue's window and are shown as such.
                counts[cid] = k
        assign[d["dispute_id"]] = cid
        counts[cid] += 1

    people = {
        cid: {
            "customer_id": cid,
            "name": _name(i),
            "email": f"{_name(i).split()[0].lower()}.{_name(i).split()[1].lower()}@example.in",
        }
        for i, cid in enumerate(order)
    }
    return {"assign": assign, "people": people}


def customer_of(dispute_id: str) -> dict:
    c = build_customers()
    return c["people"][c["assign"][dispute_id]]


def customer_disputes(customer_id: str) -> list[dict]:
    c = build_customers()
    rows, _ = load_disputes()
    ids = {k for k, v in c["assign"].items() if v == customer_id}
    return [d for d in rows if d["dispute_id"] in ids]


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------

def summary(d: dict) -> dict:
    meta = code_meta(d.get("reason_code"))
    cust = customer_of(d["dispute_id"])
    s = score(d)
    return {
        "id": d["dispute_id"],
        "reason_code": d["reason_code"],
        "network": d.get("network") or meta.get("network"),
        "category": d.get("category") or meta.get("category"),
        "description": meta.get("description", ""),
        "amount": round(float(d["amount"]), 2),
        "filed_on": _day_to_date(d.get("dispute_day", 20)),
        "customer": cust,
        "prior_disputes": int(d.get("prior_disputes") or 0),
        "address_match": bool(d.get("address_match")),
        "new_device": bool(d.get("new_device")),
        **s,
    }


def detail(d: dict) -> dict:
    out = summary(d)
    out["artifacts"] = [
        {**a, "created_on": _day_to_date(a.get("created_day", 0))}
        for a in (d.get("artifacts") or {}).values()
    ]
    out["provenance"] = {
        "code_provenance": code_meta(d["reason_code"]).get("provenance", "razorpay_docs"),
        "rulebook_version": rulebook()["meta"]["version"],
        "verified_on": str(rulebook()["meta"]["verified_on"]),
    }
    return out


def find(dispute_id: str) -> dict | None:
    rows, _ = load_disputes()
    return next((d for d in rows if d["dispute_id"] == dispute_id), None)


def truth(dispute_id: str) -> bool | None:
    """Held-out ground-truth label. Used ONLY by the settlement simulator, never
    by scoring, and never sent to the client before a case is settled."""
    d = find(dispute_id)
    return None if d is None else bool(d.get("label_won"))
