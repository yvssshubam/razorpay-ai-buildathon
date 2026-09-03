"""Does ingestion recover the reference, and does the model router earn its cost?

GROUND TRUTH IS NOT AN ANNOTATION. Each document is rendered from an artifact
whose kind, reference and date were fixed by the frozen generator before this
extractor existed. The extractor sees only the text. So a score here is the
fraction of documents from which a value decided in advance was recovered, not
the fraction that matched somebody's later reading of the document.

THREE NUMBERS, AND THE THIRD IS THE ONE THAT MATTERS. Recovery rate is how often
the right reference came out. Miss rate is how often nothing came out, which is
safe: the merchant is asked to type it instead. WRONG-VALUE RATE is how often a
confident but incorrect reference came out, and that is the dangerous one,
because a wrong artifact is a lie the verifier cannot catch. Check 4 compares a
claim to a record; if the record itself is wrong, a faithful claim about it
passes. Same trust boundary as merchant-typed evidence, reached by a different
road.

The distractors are the test. Every document carries an order number, an invoice
number, a phone number, a GST number and a rupee amount, and in a fair number of
cases the order number happens to share a prefix with the reference. An
extractor that grabs the first long digit run scores well on the easy templates
and produces silent wrong values on the rest.
"""
import argparse
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(HERE, "..", "agent"), os.path.join(HERE, "..", "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ingest as I          # noqa: E402
from documents import render  # noqa: E402


def run(artifacts, router, provider=None, progress=True):
    """Progress is printed because a local model makes this slow enough to look
    hung. The model router costs one call per document plus one more for every
    document it sends to prose, so 100 documents is roughly 160 calls and over
    an hour on a 7B. A harness that prints nothing for an hour is
    indistinguishable from a crash, which has already cost time twice."""
    ok = miss = wrong = 0
    by_template = Counter()
    tpl_total = Counter()
    tools = Counter()
    wrong_cases = []

    import time
    t0 = time.time()
    for i, art in enumerate(artifacts):
        if progress and i and i % 5 == 0:
            rate = (time.time() - t0) / i
            left = rate * (len(artifacts) - i)
            print(f"      {i}/{len(artifacts)}  ok={ok} miss={miss} wrong={wrong}"
                  f"  ~{left/60:.1f} min left", flush=True)
        text, truth = render(art, seed=i)
        got = I.ingest(text, truth["kind"], truth["created_day"],
                       router=router, provider=provider)
        tpl_total[truth["template"]] += 1
        tools[got["tool"]] += 1

        if not got["extracted"]:
            miss += 1
        elif I.matches(got["reference"], truth["reference"]):
            ok += 1
            by_template[truth["template"]] += 1
        else:
            wrong += 1
            if len(wrong_cases) < 50:
                wrong_cases.append((truth["template"], truth["rendered_as"],
                                    got["raw_extraction"], got["tool"],
                                    got["reference"]))

    n = len(artifacts)
    return dict(n=n, ok=ok, miss=miss, wrong=wrong,
                recovery=ok / n, miss_rate=miss / n, wrong_rate=wrong / n,
                by_template={t: by_template[t] / tpl_total[t] for t in tpl_total},
                tools=dict(tools), wrong_cases=wrong_cases)


def report(label, r):
    print(f"\n  {label}")
    print(f"    recovered      {r['ok']:>4} / {r['n']}   {r['recovery']:.1%}")
    print(f"    no value found {r['miss']:>4}          {r['miss_rate']:.1%}   (safe: ask the merchant)")
    print(f"    WRONG value    {r['wrong']:>4}          {r['wrong_rate']:.1%}   (dangerous: unverifiable)")
    print(f"    tools chosen   {r['tools']}")
    print("    by template:   " + ", ".join(
        f"{t} {v:.0%}" for t, v in sorted(r["by_template"].items())))
    for tpl, rendered, raw, tool, ref in r["wrong_cases"]:
        print(f"      wrong on {tpl}: document said {rendered!r}, "
              f"raw={raw!r} ref={ref!r} tool={tool}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "..", "data", "holdout.jsonl"))
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--router", default="heuristic",
                    choices=["heuristic", "model", "both"])
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    arts = []
    for line in open(a.data, encoding="utf-8"):
        for art in (json.loads(line).get("artifacts") or {}).values():
            if art.get("present") and art.get("value"):
                arts.append(art)
        if len(arts) >= a.n:
            break
    arts = arts[:a.n]

    print(f"\n  Ingestion · {len(arts)} documents rendered from known artifacts")
    out = {}
    for router in (["heuristic", "model"] if a.router == "both" else [a.router]):
        print(f"\n  running router = {router} ...", flush=True)
        out[router] = run(arts, router)
        report(f"router = {router}", out[router])
    if a.json_out:
        json.dump(out, open(a.json_out, "w"), indent=2, default=str)
        print(f"\n  wrote {a.json_out}")