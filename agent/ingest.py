"""Stage 0: turning a document into an artifact.

WHERE THIS SITS. Everything else in this pipeline assumes evidence already
exists as structured records. Real merchant evidence does not: it arrives as
courier emails, CSV exports, scanned receipts, support threads and internal
notes. This is the layer that converts that into the artifact schema the
deterministic core already understands, and it hands over canonicalised records
without touching a single downstream decision.

WHY THIS IS THE PLACE AN AGENT BELONGS, AND STAGES 1-4 ARE NOT. The argument
this project makes against planner loops is that its action space is small,
enumerable and regulated: three terminal actions, a fixed toolchain, a hard
compliance gate. None of that is true here. The input is open-ended, the right
extraction strategy depends on what the document turns out to be, and a wrong
answer is recoverable rather than a regulatory event -- because whatever comes
out of this layer still has to pass the same five checks as anything else.
Agentic at the periphery, deterministic at the core.

THE ROUTING IS THE DECISION; THE EXTRACTORS ARE NOT. Each extractor is a few
lines of deterministic parsing. What varies is which one to run, and that is
what the agent chooses. A CSV export wants field lookup, a scanned receipt wants
label matching, a support thread wants a model. Choosing wrongly does not
produce a wrong answer so much as no answer, which the caller can see.

AND THE ROUTER IS ABLATED, NOT ASSUMED. route() has two implementations: a
deterministic one built from document shape, and a model. They are measured
against each other in eval/ingest_eval.py, for the same reason the classifier is
measured against a hand-written heuristic. An LLM router that does not beat
pattern matching on structured documents has not earned its latency.

WHAT THIS LAYER MAY NOT DO. It may not decide what is true. It produces a
candidate artifact with a provenance marker, and that artifact is subject to
exactly the same treatment as one a merchant typed in by hand: check 4 compares
claims against it, and serve/packet.py reports when a packet clears the rulebook
only because of it. Extraction being confident is not extraction being right.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import llm as _llm  # noqa: E402

# ---------------------------------------------------------------------------
# Canonicalisation.
#
# The stored artifact value is "{kind}:{number}". A document writes that number
# as TRK-8724, TRK8724, #8724, 87-24 or 8724. Comparing those to the stored form
# with strict equality fails every time, which is exactly the limitation the
# README records against check 4: strict string equality is right for generated
# scalars and wrong for real evidence.
#
# Digits-only is the correct normalisation for THIS reference format and is not
# a general solution. A real deployment needs per-kind rules, because an AWB and
# a GSTIN and an email message-id do not normalise the same way. Stated here so
# nobody mistakes a working narrow rule for a general one.
# ---------------------------------------------------------------------------


def canonical(value) -> str:
    """Digits of a reference, in order. '14-25' -> '1425', 'TRK8724' -> '8724'.

    OCR CONFUSIONS ARE REPAIRED, NOT SKIPPED, and this took two attempts that
    the eval caught in turn. A scanned 'DEV-9850' reaches this function as
    'DEV-98S0'; skipping the S yields '980', a shorter reference that is
    well-formed, plausible and wrong. Silent truncation to a valid-looking
    value is the worst failure this layer can produce, because it creates an
    artifact the verifier will happily check claims against.

    The first fix mapped S->5, O->0, l->1 across the whole string, which
    corrupted every alphabetic prefix that contained one of those letters:
    'DIS 1792' became '151792' and the wrong-value rate went from 1.3% to 10%.
    So the prefix is removed first and the repair is applied only to what
    follows it. The lesson is the one this project keeps relearning: a fix
    aimed at a measured failure can create a larger one, and only re-running
    the measurement tells you which happened.
    """
    if value is None:
        return ""
    s = str(value)
    if ":" in s:                      # stored artifact form, kind:number
        s = s.split(":", 1)[1]
    if not re.search(r"\d", s):
        return ""

    # Drop a leading alphabetic prefix (TRK, POD, SVC...) before repairing, and
    # only when what remains still carries the reference.
    m = re.match(r"^\s*[A-Za-z]{1,5}\s*[-/ ]?\s*(.+)$", s)
    if m and re.search(r"[\dOolISs]", m.group(1)):
        s = m.group(1)

    s = s.translate(str.maketrans({"O": "0", "o": "0", "l": "1",
                                   "I": "1", "S": "5", "s": "5"}))
    return re.sub(r"\D", "", s)


def matches(extracted, stored) -> bool:
    """Does an extracted reference denote the same record as a stored value?"""
    a, b = canonical(extracted), canonical(stored)
    return bool(a) and a == b


# ---------------------------------------------------------------------------
# Extractors. Deterministic, cheap, and each one wrong in a different way, which
# is why choosing between them is a decision worth making.
# ---------------------------------------------------------------------------

_LABELS = ("ref", "reference", "consignment", "awb", "tracking", "pod", "docket")


def extract_delimited(text):
    """key,value or key: value lines. CSV exports and config-shaped dumps."""
    for line in text.splitlines():
        parts = re.split(r"[,:]", line, maxsplit=1)
        if len(parts) == 2 and parts[0].strip().lower().replace("_", "") in \
                [l.replace("_", "") for l in _LABELS] + ["referenceno", "refno"]:
            return parts[1].strip()
    return None


def extract_labelled(text):
    """'Ref ......... X' or 'Ref on file: X'. Receipts and notes.

    Anchored on the label rather than on the digits, which is the point: the
    order number in these documents is often longer, earlier, and a prefix of
    the reference itself.
    """
    pat = re.compile(
        r"\b(" + "|".join(_LABELS) + r")\b[^A-Za-z0-9]{0,20}"
        r"([A-Z]{0,4}[-/ ]?[\dOolISs][\dOolISs\-/ ]*)",
        re.IGNORECASE)
    m = pat.search(text)
    return m.group(2).strip(" .-/") if m else None


def extract_prose(text, provider=None):
    """A model reads the document. For threads and emails, where the reference
    is embedded in a sentence and no label reliably precedes it."""
    provider = provider or _llm.get_provider()
    system = (
        "Extract the shipment, delivery or service REFERENCE NUMBER from the "
        "document. Ignore order numbers, invoice numbers, phone numbers, GST "
        "numbers and money amounts. Return JSON only:\n"
        '{"reference": "..."} or {"reference": null} if there is none.'
    )
    try:
        raw = provider.draft(system, text, seed=0)
        return (json.loads(raw) or {}).get("reference")
    except Exception:
        return None


EXTRACTORS = {
    "delimited": extract_delimited,
    "labelled": extract_labelled,
    "prose": extract_prose,
}


# ---------------------------------------------------------------------------
# Routing: the actual decision.
# ---------------------------------------------------------------------------

def route_heuristic(text) -> str:
    """Shape-based routing. The baseline the model has to beat."""
    lines = [l for l in text.splitlines() if l.strip()]
    if lines and sum(1 for l in lines if re.match(r"^[a-z_]+,", l.strip())) >= 2:
        return "delimited"
    if re.search(r"\b(" + "|".join(_LABELS) + r")\b[^A-Za-z0-9]{2,}", text, re.I):
        return "labelled"
    return "prose"


def route_model(text, provider=None) -> str:
    """The model picks the tool. Ablated against route_heuristic."""
    provider = provider or _llm.get_provider()
    system = (
        "Choose the best tool to extract a reference number from this document.\n"
        "  delimited - the document is key/value lines, like a CSV or export\n"
        "  labelled  - a label such as 'Ref' is followed by the value\n"
        "  prose     - the reference is inside a sentence with no reliable label\n"
        'Return JSON only: {"tool": "delimited"|"labelled"|"prose"}'
    )
    try:
        raw = provider.draft(system, text, seed=0)
        tool = (json.loads(raw) or {}).get("tool")
        return tool if tool in EXTRACTORS else route_heuristic(text)
    except Exception:
        return route_heuristic(text)


def ingest(text, kind, created_day, router="heuristic", provider=None) -> dict:
    """Document in, candidate artifact out.

    `kind` and `created_day` are supplied by the caller rather than inferred.
    The merchant already says which requirement they are answering when they
    attach a file, and inferring the kind from the document would let a
    misclassification satisfy a rulebook entry the document does not support --
    a failure the verifier could not catch, because check 2 compares a claim to
    an artifact and the artifact would already be wrong.
    """
    tool = (route_model(text, provider) if router == "model"
            else route_heuristic(text))
    raw = EXTRACTORS[tool](text, provider) if tool == "prose" \
        else EXTRACTORS[tool](text)
    ref = canonical(raw)

    return {
        "kind": kind,
        "value": f"{kind}:{ref}" if ref else None,
        "created_day": created_day,
        "reference": ref or None,
        "tool": tool,
        "raw_extraction": raw,
        "provenance": "merchant",   # see serve/evidence.py _INTEGRITY
        "extracted": bool(ref),
    }