"""Stages 3 and 4 behind the API: real drafting, real verification.

WHY THIS MODULE EXISTS. Until now serve/ ran only the decision half of the
pipeline. Scores, packets and claim counts all came from
baselines._build_packet, which is deterministic and never touches a model. That
was honest -- adapter.py said so in its header -- but it meant the two stages
the submission is actually differentiated by, LLM drafting and the verifier
gate, were invisible to anyone who only looked at the web app. A reviewer
watching the dashboard saw a triage tool. This closes that.

WHAT IS DIFFERENT FROM THE DETERMINISTIC PATH. _build_packet emits one claim
per artifact and marks it supported if the artifact exists and predates the
dispute. That is a stand-in for stages 3 and 4, not the thing itself. Here a
model writes the claims, and all five checks run: the artifact must exist, its
kind must match, it must predate the dispute, the asserted field value must
match the record, and the surviving kinds must still cover the rulebook. The
two results can disagree, and where they do the LLM one is the real answer.

WHY IT IS ON DEMAND AND NOT ON PAGE LOAD. A Gemini call costs a second or so
and counts against a 500/day quota. Drafting all 150 queued disputes on every
page load would exhaust the quota in under four page views, and would make the
queue unusable while it ran. So the merchant asks for a packet, one dispute at
a time, and the result is cached until the inputs change.

WHY A DRAFTING FAILURE IS NOT AN ERROR PAGE. draft_claims returns an empty
claim list on any provider failure, and an empty list cannot cover the
rulebook, so the packet blocks and routes to a human. That is the correct
behaviour and it is the same behaviour as a model that drafts badly. The route
surfaces the reason but does not treat it as an exception, because a rate limit
must not look different from a bad draft: both mean nobody should submit this.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(HERE, "..", "agent"), os.path.join(HERE, "..", "eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import llm as _llm            # noqa: E402
from draft import draft_claims, retrieve   # noqa: E402
from verify import verify     # noqa: E402

# key: (dispute_id, provider, fault_rate, n_supplied) -- so a packet is redrawn
# when the merchant files new evidence, and not otherwise.
_CACHE: dict[tuple, dict] = {}


def reset() -> None:
    _CACHE.clear()


def provider_name() -> str:
    return (os.environ.get("CB_LLM") or "mock").lower()


def build(d: dict, fault_rate: float | None = None, force: bool = False) -> dict:
    """Draft a packet for one dispute and run the five checks over it."""
    supplied = sum(1 for a in (d.get("artifacts") or {}).values()
                   if a.get("provenance") == "merchant")
    key = (d["dispute_id"], provider_name(), fault_rate, supplied)
    if not force and key in _CACHE:
        return {**_CACHE[key], "cached": True}

    # CB_FAULT_RATE is read by MockProvider at construction. Setting it per
    # request rather than per process is what lets the UI demonstrate a
    # blocked packet on demand; it is restored immediately so one request
    # cannot change how the next one behaves.
    prev = os.environ.get("CB_FAULT_RATE")
    if fault_rate is not None:
        os.environ["CB_FAULT_RATE"] = str(fault_rate)
    try:
        provider = _llm.get_provider()
        claims, err = draft_claims(d, provider, seed=abs(hash(d["dispute_id"])) % 10_000)
    finally:
        if fault_rate is not None:
            if prev is None:
                os.environ.pop("CB_FAULT_RATE", None)
            else:
                os.environ["CB_FAULT_RATE"] = prev

    r = verify(d, claims)
    retrieved = retrieve(d)

    out = {
        "provider": provider_name(),
        "model": os.environ.get("CB_LLM_MODEL") if provider_name() == "gemini" else None,
        "fault_rate": fault_rate,
        "draft_error": err,
        "artifacts_retrieved": len(retrieved),
        "claims_drafted": r["n_claims"],
        "kept": [
            {"text": c.get("text", ""), "artifact_id": c["artifact_id"],
             "kind": c.get("verified_kind"),
             "field": c.get("asserts_field"), "value": c.get("asserts_value")}
            for c in r["kept"]
        ],
        "stripped": [
            {"text": c.get("text", ""), "artifact_id": c.get("artifact_id"),
             "reason": c["reason"],
             "actual_kind": c.get("actual_kind"),
             "actual_value": c.get("actual_value")}
            for c in r["stripped"]
        ],
        "n_fabricated": r["n_fabricated"],
        "n_value_mismatch": r["n_value_mismatch"],
        "n_unverifiable": r["n_unverifiable"],
        "hallucination_rate": round(r["hallucination_rate"], 4),
        "completeness": round(r["completeness"], 3),
        "missing_evidence": r["missing_evidence"],
        "blocked": r["blocked"],
        "field_check": os.environ.get("CB_FIELD_CHECK", "on").lower() != "off",
        "cached": False,
    }
    _CACHE[key] = out
    return out