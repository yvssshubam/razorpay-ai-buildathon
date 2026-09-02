"""Provider interface for Stage 3 drafting.

Three backends, selected by CB_LLM:

  mock    No network. Emits well-formed claims from the artifacts, and
          fabricates a CB_FAULT_RATE fraction of them -- citing artifact IDs
          that do not exist, or asserting facts the artifact does not contain.
          This is how the verifier is TESTED. A verifier that has never been
          shown a fabrication is an untested gate.

  ollama  Local model for development. No API key, no per-call cost.
  gemini  Hosted model for the final measurement run.

The mock is not a stand-in for measurement. Hallucination rate reported from
the mock is a number you chose. Only the real backends measure anything, and
the README must say which backend produced the headline figure.
"""
import json
import os
import random
import urllib.error
import urllib.request
def _load_dotenv():
    """Read .env from the repo root into os.environ, without overwriting
    anything already set. A shell-set variable therefore still wins, which
    keeps the CB_LLM and CB_FAULT_RATE sweeps working."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

TIMEOUT = 90


class LLMError(RuntimeError):
    pass


def _post(url, payload, headers=None, retries=3):
    """Retry with backoff. A transient timeout mid-sweep should cost seconds,
    not the whole run."""
    import time
    body = json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8")[:400]
            if e.code not in (429, 500, 502, 503, 504):
                raise LLMError(f"{e.code}: {detail}") from e
            last = LLMError(f"{e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = LLMError(f"unreachable: {e}")
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise LLMError(f"failed after {retries} attempts: {last}")

def _strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


class MockProvider:
    """Deterministic per SEED, which is the caller's job to vary.

    draft() seeds its RNG from the `seed` argument alone. It knows nothing
    about which dispute it is drafting, so passing the same seed for every
    dispute injects the same fault pattern into all of them, and passing
    seed=0 throughout can inject nothing at all. Every harness here passes
    seed=i over the enumerated queue, and the published fault curves depend on
    that convention. It is stated here because it lived only in the callers,
    and a reader reproducing those numbers without it gets zero faults at every
    rate and concludes the numbers are wrong when they are right.
    """

    def __init__(self, fault_rate=None):
        self.fault_rate = float(
            os.environ.get("CB_FAULT_RATE", 0.15 if fault_rate is None else fault_rate))

    def draft(self, system, user, seed=0):
        ctx = json.loads(user)
        rng = random.Random(seed)
        arts = ctx["artifacts"]
        claims = []
        for aid, a in arts.items():
            if not a.get("present"):
                continue
            if rng.random() < self.fault_rate:
                mode = rng.choice(["bad_id", "bad_fact", "bad_value"])
                if mode == "bad_id":
                    claims.append({
                        "text": f"A {a['kind']} record confirms the transaction.",
                        "artifact_id": f"{aid}_X",
                        "asserts_kind": a["kind"],
                        "asserts_field": "value",
                        "asserts_value": a.get("value"),
                    })
                elif mode == "bad_fact":
                    claims.append({
                        "text": f"The {a['kind']} record was signed by the cardholder.",
                        "artifact_id": aid,
                        "asserts_kind": "signed_delivery_confirmation",
                        "asserts_field": "value",
                        "asserts_value": a.get("value"),
                    })
                else:
                    # THE FIFTH FAULT CLASS, added after audit. Real ID, right
                    # kind, right date -- and a fabricated field value. This is
                    # the fabricated-delivery-timestamp case that motivates the
                    # whole architecture, and it passed every structural check
                    # before check 4 existed. The injector deliberately
                    # generates a fault the pre-audit verifier could not catch;
                    # an injector that only produces catchable faults measures
                    # nothing (E1's lesson).
                    claims.append({
                        "text": f"The {a['kind']} record was created on day "
                                f"{a.get('created_day', 0) - 3}.",
                        "artifact_id": aid,
                        "asserts_kind": a["kind"],
                        "asserts_field": "created_day",
                        "asserts_value": str(a.get("created_day", 0) - 3),
                    })
            else:
                claims.append({
                    "text": f"A {a['kind']} record dated day {a.get('created_day')} "
                            f"supports this representment.",
                    "artifact_id": aid,
                    "asserts_kind": a["kind"],
                    "asserts_field": "created_day",
                    "asserts_value": str(a.get("created_day")),
                })
        return json.dumps({"claims": claims})


class OllamaProvider:
    def __init__(self, model=None, host=None):
        self.model = model or os.environ.get("CB_LLM_MODEL", "llama3.1:8b")
        self.host = host or os.environ.get("CB_OLLAMA_HOST", "http://localhost:11434")

    def draft(self, system, user, seed=0):
        out = _post(f"{self.host}/api/chat", {
            "model": self.model,
            "format": "json",
            "stream": False,
            # num_ctx and num_predict are set explicitly because Ollama's
            # default context is 4096 and this prompt does not fit in it. The
            # system rules plus the retrieved artifacts run to a few thousand
            # tokens on a five-document reason code, and the model then has to
            # emit a claim per artifact. At the default the reply is silently
            # truncated mid-string, json.loads fails, draft_claims returns an
            # empty list, and the packet blocks -- which looks exactly like a
            # model that cannot follow the schema. It is not. Observed on
            # qwen3:8b: correctly shaped JSON, cut off inside the third claim.
            "options": {"temperature": 0.2, "seed": seed,
                        "num_ctx": 8192, "num_predict": 2048},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        })
        return _strip_fences(out["message"]["content"])


class GeminiProvider:
    def __init__(self, model=None, api_key=None):
        self.model = model or os.environ.get("CB_LLM_MODEL", "gemini-3.6-flash")
        self.key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise LLMError("GEMINI_API_KEY is not set")

    def draft(self, system, user, seed=0):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.key}")
        out = _post(url, {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2,
                                 "responseMimeType": "application/json"},
        })
        try:
            return _strip_fences(out["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError):
            raise LLMError(f"unexpected response shape: {str(out)[:400]}")


def get_provider(name=None):
    name = (name or os.environ.get("CB_LLM", "mock")).lower()
    if name == "mock":
        return MockProvider()
    if name == "ollama":
        return OllamaProvider()
    if name == "gemini":
        return GeminiProvider()
    raise LLMError(f"unknown provider: {name}")