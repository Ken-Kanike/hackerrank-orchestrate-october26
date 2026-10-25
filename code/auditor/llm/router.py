"""Multi-provider LLM router: priority fallback, key rotation, caching, usage ledger.

Providers: anthropic, openai, gemini, groq (any subset). Plain HTTPS via urllib, so no SDKs are required.
`complete_json` returns a parsed dict, or None when no provider can answer; callers must then use the
deterministic path. Every network call is cached on disk (re-runs cost zero tokens) and logged to a ledger.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import events
from ..config import CACHE_DIR, load_env

DEFAULT_ORDER = ["anthropic", "openai", "gemini", "groq", "custom"]
DEFAULT_MODELS = {
    "anthropic": ("claude-opus-5-5", "claude-sonnet-5-5"),
    "openai": ("gpt-4.1", "gpt-4.1-mini"),
    "gemini": ("gemini-2.5-pro", "gemini-2.5-flash"),
    "groq": ("openai/gpt-oss-120b", "openai/gpt-oss-20b"),
    "custom": ("custom-model", "custom-model"),        # any OpenAI-compatible endpoint: CUSTOM_BASE_URL + CUSTOM_API_KEY + CUSTOM_MODEL1
}
DEFAULT_VISION = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-4.1",
    "gemini": "gemini-2.5-flash",
    "groq": "qwen/qwen3.8-27b",
    "custom": "custom-model",
}
# $ per 1M tokens (input, output) used only for the estimated-cost column in usage_report.md
PRICES = {
    "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "gpt-4.1": (2.0, 8.0), "gpt-4.1-mini": (0.4, 1.6),
    "gemini-2.5-pro": (1.25, 10.0), "gemini-2.5-flash": (0.3, 2.5),
    "openai/gpt-oss-120b": (0.15, 0.6), "llama-3.3-70b-versatile": (0.59, 0.79),
}
URLS = {"openai": "https://api.openai.com/v1/chat/completions", "groq": "https://api.groq.com/openai/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages"}


def _url(provider: str) -> str:
    if provider == "custom":
        return os.environ.get("CUSTOM_BASE_URL", "").rstrip("/") + "/chat/completions"
    return URLS[provider]


def _keys(provider: str) -> list[str]:
    pre = provider.upper()
    out = [os.environ.get(f"{pre}_API_KEY", "")]
    if provider == "custom" and os.environ.get("CUSTOM_BASE_URL") and not any(out):
        out = ["none"]                                    # local OpenAI-compatible servers often need no key
    out += [os.environ.get(f"{pre}_API_KEY_{i}", "") for i in range(1, 21)]
    seen, res = set(), []
    for k in out:
        if k and k not in seen:
            seen.add(k); res.append(k)
    return res


def _fp(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _models(provider: str) -> list[str]:
    pre = provider.upper()
    m1 = os.environ.get(f"{pre}_API_KEY_MODEL1") or os.environ.get(f"{pre}_MODEL1") or DEFAULT_MODELS[provider][0]
    m2 = os.environ.get(f"{pre}_API_KEY_MODEL2") or os.environ.get(f"{pre}_MODEL2") or DEFAULT_MODELS[provider][1]
    return [m1] + ([m2] if m2 != m1 else [])


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except Exception:
            return None
    return None


class Router:
    def __init__(self, enabled: bool = True):
        load_env()
        self.cache_dir = Path(CACHE_DIR); self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / "llm_cache.json"
        self.ledger_path = self.cache_dir / "usage.jsonl"
        self.cache = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.exists() else {}
        order = [p.strip() for p in os.environ.get("LLM_PROVIDER_ORDER", ",".join(DEFAULT_ORDER)).split(",") if p.strip()]
        self.providers = [p for p in order if p in DEFAULT_MODELS and _keys(p) and (p != "custom" or os.environ.get("CUSTOM_BASE_URL"))] if enabled else []
        self.cooldown: dict[str, float] = {}      # key fingerprint (never the raw key) -> unix time usable again
        self.no_json_mode: set = set()            # (provider, model) where response_format=json_object was rejected
        self.dead: set[str] = set()               # (provider, model) that returned 404/400 model errors
        self.rot: dict[str, int] = {}
        self.run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())          # every ledger line carries it (usage report = one run)
        self.refresh = os.environ.get("LLM_REFRESH", "0") == "1"             # --refresh-llm: ignore cached answers
        self.max_seconds = float(os.environ.get("LLM_MAX_SECONDS", "600")); self.max_calls = int(os.environ.get("LLM_MAX_CALLS", "2000"))
        self.workers = int(os.environ.get("LLM_WORKERS", "2"))
        self.started, self.calls = time.time(), 0
        self.lock = threading.RLock()
        self.available_models: dict[str, set] = {}                           # provider -> model ids from /models (discovery)

    # ------------------------------------------------------------------ public
    @property
    def available(self) -> bool:
        return bool(self.providers)

    def _over_budget(self) -> bool:
        return time.time() - self.started > self.max_seconds or self.calls >= self.max_calls

    def complete_json(self, task: str, system: str, user: str, images: list[Path] | None = None, max_tokens: int = 1200,
                      vision: bool = False, validator=None):
        """Return (parsed_json | None, meta). Cached by (task, system, user, image hashes); provider/model are stored as metadata only,
        so a stronger model's answer is reusable. `validator(parsed) -> bool` rejects malformed answers (one re-ask with the error)."""
        ihash = [hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16] for p in (images or [])]
        ck = hashlib.sha256(json.dumps([task, system, user, ihash], ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            hit = self.cache.get(ck)
        if hit is not None and not self.refresh:
            meta = hit.get("meta", {})
            self._ledger({**meta, "task": task, "cached": True, "ok": True})        # attributed tokens: what this answer originally cost
            events.emit("llm", task=task, cached=True, ok=True, ms=0, **{k: meta.get(k) for k in ("provider", "model", "in", "out")})
            return hit["json"], {"cached": True, **meta}
        for attempt in range(2 if validator else 1):
            u = user if attempt == 0 else user + "\n\nYour previous answer did not match the required JSON schema. Answer again, JSON only."
            for prov in self.providers:
                models = [DEFAULT_VISION[prov] if not os.environ.get(f"{prov.upper()}_VISION_MODEL") else os.environ[f"{prov.upper()}_VISION_MODEL"]] \
                    if vision else self._usable_models(prov)
                for model in models:
                    if (prov, model) in self.dead:
                        continue
                    if self._over_budget():
                        return None, {"cached": False, "provider": None, "budget_exhausted": True}
                    with self.lock:
                        self.calls += 1
                    _t0 = time.perf_counter()
                    res = self._try(prov, model, system, u, images or [], max_tokens)
                    if res is None:
                        events.emit("llm", task=task, provider=prov, model=model, ok=False, cached=False, ms=round((time.perf_counter() - _t0) * 1000), error="no response")
                        continue
                    text, tin, tout = res
                    parsed = extract_json(text)
                    ok = parsed is not None and (validator is None or bool(validator(parsed)))
                    meta = {"provider": prov, "model": model, "in": tin, "out": tout, "task": task}
                    self._ledger({**meta, "cached": False, "ok": ok})
                    events.emit("llm", task=task, cached=False, ok=ok, ms=round((time.perf_counter() - _t0) * 1000), provider=prov, model=model, **{"in": tin, "out": tout})
                    if not ok:
                        continue
                    with self.lock:
                        self.cache[ck] = {"json": parsed, "meta": meta}
                        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
                    return parsed, {"cached": False, **meta}
        return None, {"cached": False, "provider": None}

    def _usable_models(self, prov: str) -> list[str]:
        """Configured models filtered by the provider's /models listing (when it could be fetched); 404s never reach the run."""
        ms = _models(prov)
        have = self.available_models.get(prov)
        if have is None:
            have = self.available_models[prov] = self._discover(prov)
        usable = [m for m in ms if not have or m in have]
        return usable or ms

    def _discover(self, prov: str) -> set:
        keys = _keys(prov)
        if not keys:
            return set()
        try:
            if prov == "gemini":
                url, hdr = f"https://generativelanguage.googleapis.com/v1beta/models?key={keys[0]}", {}
            elif prov == "anthropic":
                url, hdr = "https://api.anthropic.com/v1/models", {"x-api-key": keys[0], "anthropic-version": "2023-06-01"}
            else:
                url, hdr = _url(prov).rsplit("/chat/completions", 1)[0] + "/models", {"Authorization": f"Bearer {keys[0]}"}
            req = urllib.request.Request(url, headers={"User-Agent": "ghost-data-auditor/1.0", **hdr})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
            items = d.get("data") or d.get("models") or []
            return {str(i.get("id") or i.get("name", "")).replace("models/", "") for i in items}
        except Exception:
            return set()

    # ------------------------------------------------------------------ internals
    def _ledger(self, meta: dict) -> None:
        with self.lock, open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({**meta, "run_id": self.run_id, "t": int(time.time())}) + "\n")

    def _next_key(self, prov: str) -> str | None:
        keys = _keys(prov)
        now = time.time()
        for i in range(len(keys)):
            k = keys[(self.rot.get(prov, 0) + i) % len(keys)]
            if self.cooldown.get(_fp(k), 0) <= now:
                self.rot[prov] = (self.rot.get(prov, 0) + i) % len(keys)
                return k
        return None

    def _try(self, prov, model, system, user, images, max_tokens):
        waited = 0.0
        for _ in range(len(_keys(prov)) * 3 + 2):
            key = self._next_key(prov)
            if key is None:
                soon = min((self.cooldown.get(_fp(k), 0) for k in _keys(prov)), default=0) - time.time()
                if 0 < soon <= 75 and waited < 180:     # every key is in a short rate-limit window: wait it out
                    time.sleep(soon + 0.5); waited += soon + 0.5
                    continue
                return None
            try:
                return self._call(prov, model, key, system, user, images, max_tokens)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")[:300]
                if e.code in (401, 403):
                    self.cooldown[_fp(key)] = time.time() + 1e9           # bad key: never retry this run
                elif e.code == 429:
                    ra = e.headers.get("retry-after")
                    wait = float(ra) if ra and ra.replace(".", "").isdigit() else 30.0
                    # daily-quota style errors -> park the key for an hour
                    self.cooldown[_fp(key)] = time.time() + (3600 if "per day" in body or "daily" in body.lower() else min(wait, 90))
                elif e.code == 400 and "json_validate_failed" in body and (prov, model) not in self.no_json_mode:
                    self.no_json_mode.add((prov, model))             # retry once without JSON mode (we parse JSON ourselves)
                    try:
                        return self._call(prov, model, key, system, user, images, max_tokens)
                    except Exception:
                        return None
                elif e.code == 404 or (e.code == 400 and re.search(r"model|not found|does not exist|unsupported", body, re.I)):
                    self.dead.add((prov, model)); return None        # the model itself is unusable: stop trying it this run
                elif e.code == 400:
                    return None                                      # request-specific (e.g. image too large): fail only this request
                else:
                    self.cooldown[_fp(key)] = time.time() + 20
            except Exception:
                self.cooldown[_fp(key)] = time.time() + 10
        return None

    def _call(self, prov, model, key, system, user, images, max_tokens):
        if prov in ("openai", "groq", "custom"):
            content = [{"type": "text", "text": user}]
            for p in images:
                b64 = base64.b64encode(Path(p).read_bytes()).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
            body = {"model": model, "messages": [{"role": "system", "content": system},
                                                 {"role": "user", "content": content if images else user}],
                    "temperature": 0, "max_tokens": max_tokens}
            if prov == "openai" and model.startswith(("gpt-5", "o")):
                body.pop("temperature"); body["max_completion_tokens"] = body.pop("max_tokens")
            if prov == "groq" and model.startswith("openai/gpt-oss"):
                body["reasoning_effort"] = "low"; body["max_tokens"] = max(max_tokens, 1500)   # reasoning tokens count toward the cap
            if not images and (prov, model) not in self.no_json_mode:
                body["response_format"] = {"type": "json_object"}
            data = self._post(_url(prov), body, {"Authorization": f"Bearer {key}"})
            u = data.get("usage", {})
            return data["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        if prov == "anthropic":
            content = []
            for p in images:
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                            "data": base64.b64encode(Path(p).read_bytes()).decode()}})
            content.append({"type": "text", "text": user})
            # Opus 5.5 cannot disable thinking and defaults to effort "medium": ask for "low" and leave room for thinking tokens.
            body = {"model": model, "max_tokens": max(max_tokens, 2000), "system": system, "messages": [{"role": "user", "content": content}],
                    "output_config": {"effort": "low"}}
            data = self._post(URLS[prov], body, {"x-api-key": key, "anthropic-version": "2023-06-01"})
            u = data.get("usage", {})
            if data.get("stop_reason") == "refusal":                 # safeguard decline: never parse partial content
                return "", u.get("input_tokens", 0), u.get("output_tokens", 0)
            return "".join(b.get("text", "") for b in data["content"]), u.get("input_tokens", 0), u.get("output_tokens", 0)
        if prov == "gemini":
            parts = [{"text": user}]
            for p in images:
                parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(Path(p).read_bytes()).decode()}})
            body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}}
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            data = self._post(url, body, {})
            u = data.get("usageMetadata", {})
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
            return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)
        raise ValueError(prov)

    @staticmethod
    def _post(url, body, headers):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "ghost-data-auditor/1.0", **headers})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())


def usage_summary(ledger_path: Path | None = None, run_id: str | None = None) -> dict:
    """(provider, model) -> fresh and cache-attributed calls/tokens. run_id=None aggregates every run in the ledger."""
    p = ledger_path or (CACHE_DIR / "usage.jsonl")
    agg: dict = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            m = json.loads(line)
            if (run_id and m.get("run_id") != run_id) or not m.get("provider"):
                continue
            a = agg.setdefault((m["provider"], m["model"]), {"calls": 0, "in": 0, "out": 0, "cached_calls": 0, "cached_in": 0, "cached_out": 0})
            if m.get("cached"):
                a["cached_calls"] += 1; a["cached_in"] += m.get("in", 0); a["cached_out"] += m.get("out", 0)
            else:
                a["calls"] += 1; a["in"] += m.get("in", 0); a["out"] += m.get("out", 0)
    return agg
