import json
import os
import random
import urllib.error
import urllib.request
def _load_dotenv():
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
            "options": {"temperature": 0.2, "seed": seed},
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