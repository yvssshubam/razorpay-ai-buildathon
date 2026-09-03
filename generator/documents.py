"""Render an artifact as the kind of document a merchant would actually send.

WHY THIS EXISTS. Ingestion cannot be evaluated without documents, and there are
no real ones. The circular trap would be to write documents by hand, tune an
extractor until it reads them, and report the accuracy: that measures the
extractor against its author's imagination.

This avoids the circle the same way the fault injector does. A document is
rendered FROM an artifact whose kind, reference and date are already known, and
the extractor never sees the artifact -- only the rendered text. Ground truth is
the source record, not an annotation someone made up afterwards. If extraction
is scored at 0.9 it means 90% of the time it recovered a value that was decided
before the extractor existed.

WHAT MAKES A DOCUMENT HARD, AND WHY EACH ONE IS HERE. Every noise source below
is a real failure mode for extraction, not decoration:

  Distractor numbers. An order number, an invoice number, a phone number and a
  rupee amount sit alongside the reference. Without these, extraction collapses
  to "find the digits", which no real document permits.

  Reformatted references. The stored value is tracking_information:8724, but a
  courier writes TRK-8724, a spreadsheet writes 8724, an email writes
  "ref 8724 /". Canonicalisation is the whole reason check 4's strict string
  equality has to become normalised equality on real evidence.

  Dates in five formats, none of them the integer day the record stores.

  OCR damage on scanned documents: O/0, l/1, S/5, and dropped spaces.

  Surrounding prose. The signal is a few characters inside a few hundred.

WHAT IS STILL NOT REAL. These are generated from templates, so they carry the
vocabulary and structure of whoever wrote the templates -- which is the same
limitation the dispute generator carries and is disclosed the same way. Real
merchant evidence is worse: multi-page PDFs, forwarded threads with quoted
replies, screenshots, and handwriting. An extractor scoring well here has
cleared a bar, not the bar.
"""
from __future__ import annotations

import random
import re

# Reference presentations. The stored value is "{kind}:{number}"; a document
# writes the number in one of these shapes and never the stored form.
_REF_STYLES = [
    lambda n, p: f"{p}-{n}",
    lambda n, p: f"{p}{n}",
    lambda n, p: f"{p} {n}",
    lambda n, p: str(n),
    lambda n, p: f"#{n}",
    lambda n, p: f"{p}/{n}",
    lambda n, p: "-".join([str(n)[:2], str(n)[2:]]) if len(str(n)) > 2 else str(n),
]

_PREFIX = {
    "tracking_information": "TRK",
    "delivery_confirmation_signed": "POD",
    "digital_delivery_logs": "DL",
    "service_completion_records": "SVC",
    "customer_acknowledgement": "ACK",
    "authentication_log": "AUTH",
    "device_and_ip_records": "DEV",
    "refund_records": "RFND",
    "cancellation_policy": "POL",
    "terms_of_service": "TOS",
}

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _date_forms(day, rng):
    """Five presentations of the same date. None is the integer the record holds."""
    m = 1 + (day // 28) % 12
    d = 1 + day % 28
    return rng.choice([
        f"{d:02d}/{m:02d}/2026",
        f"2026-{m:02d}-{d:02d}",
        f"{d} {_MONTHS[m - 1]} 2026",
        f"{_MONTHS[m - 1]} {d}, 2026",
        f"{d:02d}.{m:02d}.26",
    ])


def _ocr_damage(text, rng, rate=0.02):
    """Character confusions a scanner makes. Applied only to scanned templates."""
    swaps = {"O": "0", "0": "O", "l": "1", "1": "l", "S": "5", "5": "S"}
    out = []
    for ch in text:
        if ch in swaps and rng.random() < rate:
            out.append(swaps[ch])
        else:
            out.append(ch)
    return "".join(out)


def _distractors(rng):
    return {
        "order": rng.randint(100000, 999999),
        "invoice": rng.randint(10000, 99999),
        "phone": f"+91 {rng.randint(70000, 99999)}{rng.randint(10000, 99999)}",
        "amount": f"{rng.randint(200, 90000):,}.00",
        "gst": f"{rng.randint(10, 37)}AABCU{rng.randint(1000, 9999)}L1Z{rng.randint(0, 9)}",
    }


_TEMPLATES = {
    "courier_email": """From: operations@bluedart-logistics.in
To: disputes@merchant.co.in
Subject: Re: POD request for order {order}

Hi team,

Please find the delivery confirmation you asked for. Consignment {ref} was
delivered on {date} and signed for at the door. The recipient's registered
number on file is {phone}.

Invoice {invoice} for this shipment was Rs {amount}. Let me know if you need
the scanned sheet as well.

Regards,
Operations desk""",

    "system_export": """orders_export_2026.csv (row 1 of 1)

order_id,{order}
invoice_no,{invoice}
reference,{ref}
recorded_on,{date}
amount_inr,{amount}
gstin,{gst}
status,COMPLETED""",

    "scanned_receipt": """                 DELIVERY / SERVICE RECEIPT
                 ---------------------------
   Order No .......... {order}
   Ref ............... {ref}
   Date .............. {date}
   Amount ............ Rs {amount}
   Contact ........... {phone}

   Received in good condition.
   Signature on file.""",

    "support_thread": """[Support conversation, exported {date}]

Customer: hi i wanted to check on my order {order}, has it shipped
Agent: Let me check that for you.
Agent: Yes, it went out and the reference is {ref}. It was recorded on {date}.
Customer: ok great thanks
Agent: No problem. The invoice total was Rs {amount} against invoice {invoice}.
Customer: got it, all good then""",

    "internal_note": """Internal note, added by ops

Re order {order} ({date}).
Ref on file: {ref}.
Customer contacted on {phone}, confirmed receipt, no complaint raised.
Nothing outstanding. Invoice {invoice}, Rs {amount}.""",
}

SCANNED = {"scanned_receipt"}


def render(artifact, seed=0):
    """Return (document_text, ground_truth) for one artifact.

    ground_truth carries what an extractor is expected to recover: the kind, the
    bare reference number, and the day. Nothing else in the document is a target,
    and everything else in it is there to be ignored.
    """
    rng = random.Random(seed)

    kind = artifact["kind"]
    value = str(artifact.get("value") or "")
    number = value.split(":", 1)[1] if ":" in value else re.sub(r"\D", "", value)
    day = artifact.get("created_day", 0)

    prefix = _PREFIX.get(kind, kind.split("_")[0][:3].upper())
    ref = rng.choice(_REF_STYLES)(number, prefix)

    name = rng.choice(list(_TEMPLATES))
    text = _TEMPLATES[name].format(ref=ref, date=_date_forms(day, rng),
                                   **_distractors(rng))
    if name in SCANNED:
        text = _ocr_damage(text, rng)

    return text, {
        "kind": kind,
        "reference": number,
        "created_day": day,
        "template": name,
        "rendered_as": ref,
    }