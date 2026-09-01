"""Merchant-supplied evidence: re-score a dispute as if a missing record existed.

WHY THIS EXISTS. The strongest finding in the eval is the structural block
floor: at zero model error, 39.5% of packets still block, because the required
evidence was timestamped after the dispute or never existed at all. No
improvement in drafting removes that share of the human queue. But the merchant
can remove it, because the merchant is the only party who actually has the
missing record. This turns that finding into an action.

WHY IT IS OPTIONAL, AND WHY THAT IS NOT A UX SOFTENING. The EV rule already
decides correctly without the extra evidence. Supplying it changes the inputs,
not the policy. A merchant who supplies nothing gets the same honest
recommendation they would have got anyway; a merchant who supplies a real record
gets a better one because the case is genuinely stronger. Nothing here nags.

WHAT THIS IS NOT: a way to improve the score by asserting things. Read
_INTEGRITY below before changing anything in this file.
"""
from __future__ import annotations

import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(HERE, "..", "agent"), os.path.join(HERE, "..", "eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import adapter  # noqa: E402

# ---------------------------------------------------------------------------
# _INTEGRITY
#
# This endpoint is the one place in the product where a user action moves
# p(win). That makes it the one place worth attacking, so three rules hold:
#
# 1. THE MERCHANT SUPPLIES A VALUE, NOT A TICK. A checkbox saying "yes I have
#    the delivery confirmation" would let anyone inflate their own score by
#    asserting. The record must carry a value, and that value is what the
#    verifier will later compare a drafted claim against. If the merchant
#    invents it, check 4 strips the claim that cites it and the packet blocks
#    for the same reason it blocked before. The fabrication surface is closed
#    by the gate that already exists, not by a new one.
#
# 2. SUPPLIED ARTIFACTS ARE MARKED, PERMANENTLY. Provenance is 'merchant' and
#    is carried on the artifact itself, so it survives into the packet, the
#    audit line, and anything reading the record downstream. A reviewer asking
#    "which of these did the system retrieve and which did the merchant hand
#    over" gets an answer without inference.
#
# 3. THE PREVIEW IS NOT A DECISION. preview() mutates nothing. It answers "what
#    would p(win) be", and the caller can walk away. Only commit() writes, and
#    only commit() logs.
#
# One more constraint, on dates. A supplied record dated on or after the
# dispute is STALE by the same rule that made it stale when the pipeline found
# it, and stale evidence does not satisfy the rulebook. So a merchant cannot
# fix a late record by re-submitting it. That is enforced here rather than
# trusted to the caller, because it is exactly the shortcut a rushed frontend
# would take.
# ---------------------------------------------------------------------------

MERCHANT = "merchant"
SYSTEM = "system"


class EvidenceError(ValueError):
    pass


def _missing_kinds(d: dict) -> dict[str, str]:
    """kind -> state, for every required kind not currently verified."""
    return {e["kind"]: e["state"]
            for e in adapter.evidence_view(d)
            if e["state"] in ("missing", "stale")}


def _inject(d: dict, items: list[dict]) -> dict:
    """Return a copy of the dispute with the supplied records added.

    Deep-copied on purpose: the caller holds the canonical record and a
    preview must not touch it.
    """
    out = copy.deepcopy(d)
    arts = out.setdefault("artifacts", {})
    present = out.setdefault("present_evidence", [])
    dday = out.get("dispute_day", 0)

    allowed = _missing_kinds(d)
    for it in items:
        kind = (it.get("kind") or "").strip()
        value = str(it.get("value") or "").strip()

        if kind not in allowed:
            raise EvidenceError(
                f"{kind!r} is not a missing requirement for this dispute")
        if not value:
            raise EvidenceError(f"{kind!r} needs the record's value, not a tick")

        # See _INTEGRITY note 1: dated before the dispute or it is stale, and
        # stale evidence does not satisfy the rulebook. Default to one day
        # before rather than to 'now', which would silently be stale.
        day = it.get("created_day")
        day = dday - 1 if day is None else int(day)
        if day >= dday:
            raise EvidenceError(
                f"{kind!r} is dated on or after the dispute and cannot support it")

        aid = f"merch_{kind[:12]}_{len(arts)}"
        arts[aid] = {
            "artifact_id": aid,
            "kind": kind,
            "api_field": it.get("api_field"),
            "created_day": day,
            "present": True,
            "value": value,
            "provenance": MERCHANT,   # see _INTEGRITY note 2
        }
        if kind not in present:
            present.append(kind)

    return out


def _delta(before: dict, after: dict) -> dict:
    return {
        "p_win": round(after["p_win"] - before["p_win"], 4),
        "ev": round(after["ev"]["value"] - before["ev"]["value"], 2),
        "completeness": round(after["completeness"] - before["completeness"], 3),
        "unblocked": bool(before["blocked"] and not after["blocked"]),
        "flipped": before["recommendation"] != after["recommendation"],
    }


def opportunities(d: dict) -> dict:
    """What the merchant could supply, and what each item is worth.

    Each kind is priced ALONE, not cumulatively, so the numbers are a menu
    rather than a total. Summing them would overstate the gain: two missing
    documents that block the same packet are worth their joint effect once, not
    twice, and completeness is capped at 1.0 regardless.
    """
    before = adapter.score(d)
    rows = []
    for kind, state in _missing_kinds(d).items():
        probe = _inject(d, [{"kind": kind, "value": f"<{kind}>"}])
        after = adapter._score_uncached(probe)
        rows.append({"kind": kind, "state": state, **_delta(before, after)})

    rows.sort(key=lambda r: (-r["ev"], r["kind"]))
    return {
        "current": {"p_win": before["p_win"], "ev": before["ev"]["value"],
                    "completeness": before["completeness"],
                    "blocked": before["blocked"],
                    "recommendation": before["recommendation"]},
        "items": rows,
        # If nothing is missing there is nothing to ask for, and the UI should
        # say so rather than render an empty prompt.
        "complete": not rows,
    }


def preview(d: dict, items: list[dict]) -> dict:
    """Re-score with the supplied records. Mutates nothing. Writes nothing."""
    before = adapter.score(d)
    after = adapter._score_uncached(_inject(d, items))
    return {"before": before, "after": after, "delta": _delta(before, after)}


# ---------------------------------------------------------------------------
# Session state.
#
# Held here rather than in store.py because it is not a decision -- it is an
# input the merchant added to a record. It resets with the rest of the session.
#
# hydrate() is applied at the API boundary, not inside adapter.score(). Putting
# it in the scoring path would mean evidence.py and adapter.py importing each
# other, and worse, _inject() rejects a kind that is no longer missing -- so a
# record hydrated twice would raise. One choke point, applied once.
# ---------------------------------------------------------------------------

_SUPPLIED: dict[str, list[dict]] = {}


def reset() -> None:
    _SUPPLIED.clear()


def supplied_for(dispute_id: str) -> list[dict]:
    return list(_SUPPLIED.get(dispute_id) or [])


def hydrate(d: dict | None) -> dict | None:
    """Apply anything the merchant has filed against this dispute."""
    if d is None:
        return None
    items = _SUPPLIED.get(d["dispute_id"])
    return _inject(d, items) if items else d


def commit(d: dict, items: list[dict]) -> dict:
    """File the records against the dispute and return the before/after.

    _inject() validates first, so a rejected item leaves nothing stored. The
    scoring cache is keyed by dispute_id and is now stale for this one, so it
    is dropped rather than updated -- the next read recomputes from the
    hydrated record and there is only ever one code path producing a score.
    """
    before = adapter.score(d)

    # Dedupe by kind, last write wins. Re-filing a kind is a correction -- a
    # merchant fixing a mistyped tracking number -- not a second document.
    # Appending would grow the artifact list without bound and leave two
    # records of one kind disagreeing about the same fact, which is precisely
    # the state the verifier's check 4 exists to catch.
    merged: dict[str, dict] = {i["kind"]: i for i in supplied_for(d["dispute_id"])}
    for i in items:
        merged[i["kind"]] = i
    merged_list = list(merged.values())

    after_rec = _inject(d, merged_list)     # raises before anything is stored
    _SUPPLIED[d["dispute_id"]] = merged_list
    adapter._SCORES.pop(d["dispute_id"], None)

    after = adapter._score_uncached(after_rec)
    return {"before": before, "after": after, "delta": _delta(before, after),
            "supplied": [i["kind"] for i in merged_list]}