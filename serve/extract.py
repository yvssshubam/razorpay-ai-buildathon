"""HTTP surface over agent/ingest.py. Routes and serialises; decides nothing.

WHY THIS IS EXPOSED. The ingestion layer is otherwise only reachable through
eval/ingest_eval.py, which needs a clone and a holdout file. A reviewer should
be able to paste a courier email and watch the extractor either recover a
reference or say it cannot. The second outcome is the one worth seeing: a
digitless capture used to be folded into a plausible number, and now returns
nothing.

NO NEW LOGIC LIVES HERE. This calls ingest() and returns its dict unchanged,
so what the dashboard shows and what the eval measures cannot drift apart.
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(REPO, "agent"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ingest as _ingest  # noqa: E402


class ExtractError(Exception):
    pass


MAX_CHARS = 20000


def extract(text: str, kind: str, created_day: int = 0,
            router: str = "heuristic") -> dict:
    if not (text or "").strip():
        raise ExtractError("Paste a document first")
    if len(text) > MAX_CHARS:
        raise ExtractError(f"Document is longer than {MAX_CHARS} characters")
    if not (kind or "").strip():
        raise ExtractError("Say which evidence requirement this answers")
    if router not in ("heuristic", "model"):
        raise ExtractError("router must be 'heuristic' or 'model'")

    try:
        r = _ingest.ingest(text, kind.strip(), int(created_day), router=router)
    except Exception as exc:                      # provider failure, bad input
        raise ExtractError(f"Extraction failed: {exc}")

    # The layer's own provenance marker says "merchant" because an extracted
    # artifact carries the same trust weight as a typed one. Surfaced separately
    # so the dashboard can say which road it arrived by.
    return {**r, "source": "extracted", "router": router}


def kinds() -> list[str]:
    """Every evidence kind the rulebook names, so the UI cannot offer one that
    answers no requirement.

    A kind that matches no rulebook entry produces a well-formed artifact
    satisfying nothing, which is the failure ingest()'s docstring warns about
    and the verifier cannot catch: check 2 compares a claim to an artifact, and
    the artifact would already be answering the wrong requirement.

    Read from the rulebook rather than listed here, so the dropdown cannot
    drift from the file the completeness check uses.
    """
    import yaml
    path = os.path.join(REPO, "rulebook", "reason_codes.yaml")
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    out = set()
    for entry in (doc.get("codes") or {}).values():
        if isinstance(entry, dict):
            out.update((entry.get("required_evidence") or {}).keys())
    return sorted(out)