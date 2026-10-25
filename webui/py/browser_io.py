"""Browser adapter (Pyodide in a Web Worker): replaces the router's urllib network calls with synchronous XMLHttpRequest.

Synchronous XHR is allowed inside workers, so the (synchronous, cached, rate-limit-aware) router runs unchanged. Anthropic additionally
needs the 'direct browser access' header. Nothing else about the engine is touched.
"""
from __future__ import annotations

import io
import json
import urllib.error

from js import XMLHttpRequest  # noqa: E402  (only importable inside Pyodide)

from auditor.llm import router as R


def _xhr(method: str, url: str, headers: dict, body: str | None = None, timeout_ms: int = 90000):
    x = XMLHttpRequest.new()
    x.open(method, url, False)
    try:
        x.timeout = timeout_ms
    except Exception:
        pass
    if body is not None:
        x.setRequestHeader("Content-Type", "application/json")
    for k, v in headers.items():
        x.setRequestHeader(k, v)
    if "anthropic.com" in url:
        x.setRequestHeader("anthropic-dangerous-direct-browser-access", "true")
    try:
        x.send(body)
    except Exception as e:                                   # network down / CORS / mixed content
        raise urllib.error.URLError(str(e)[:200])
    return x


def _post(url, body, headers):
    x = _xhr("POST", url, headers, json.dumps(body))
    if 200 <= x.status < 300:
        return json.loads(x.responseText)
    if x.status == 0:
        raise urllib.error.URLError("network error or blocked by CORS")
    raise urllib.error.HTTPError(url, x.status, "http error", {}, io.BytesIO(str(x.responseText).encode("utf-8")))


def _discover(self, prov: str) -> set:
    keys = R._keys(prov)
    if not keys:
        return set()
    try:
        return set(list_models(prov, keys[0]))
    except Exception:
        return set()


def list_models(prov: str, key: str, base_url: str = "") -> list[str]:
    """GET the provider's model list (also used by the vault's 'test key' button). Raises on HTTP errors."""
    if prov == "gemini":
        url, hdr = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", {}
    elif prov == "anthropic":
        url, hdr = "https://api.anthropic.com/v1/models", {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif prov == "custom":
        url, hdr = base_url.rstrip("/") + "/models", {"Authorization": f"Bearer {key}"}
    else:
        url, hdr = R.URLS[prov].rsplit("/chat/completions", 1)[0] + "/models", {"Authorization": f"Bearer {key}"}
    x = _xhr("GET", url, hdr, None, 20000)
    if not 200 <= x.status < 300:
        raise RuntimeError(f"HTTP {x.status}")
    d = json.loads(x.responseText)
    items = d.get("data") or d.get("models") or []
    return [str(i.get("id") or i.get("name", "")).replace("models/", "") for i in items]


def install() -> None:
    R.Router._post = staticmethod(_post)
    R.Router._discover = _discover
