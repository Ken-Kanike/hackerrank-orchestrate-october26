"""End-to-end browser tests for docs/index.html (Playwright + Chrome).

python webui/tests/test_ui.py [--full] [--shots DIR]

Serves the repo over http://127.0.0.1, drives the real page, and checks: engine boot, demo run vs hand-written expectation, results drawer,
8-scenario suite, vault lifecycle + key hygiene, hybrid mode through a local mock OpenAI-compatible provider, themes + responsive layout,
cancel/restart and (--full) that the in-browser run over dataset/ reproduces the CLI's output.csv exactly.
Requires: pip install playwright (uses the installed Chrome via channel="chrome").
"""
from __future__ import annotations

import csv
import functools
import http.server
import io
import json
import re
import socketserver
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SHOTS = Path(sys.argv[sys.argv.index("--shots") + 1]) if "--shots" in sys.argv else None
FULL = "--full" in sys.argv
SECRET = "sk-test-SECRET-1234567890-abcdef"
PASS = "correct horse battery staple"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve_repo(port=8765):
    srv = socketserver.TCPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Mock(http.server.BaseHTTPRequestHandler):
    """OpenAI-compatible mock provider with CORS. Records every Authorization header it sees."""
    seen_auth: list = []
    calls: list = []

    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "*"); self.send_header("Access-Control-Allow-Methods", "*")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        Mock.seen_auth.append(self.headers.get("Authorization"))
        body = json.dumps({"data": [{"id": "mock-model"}]}).encode()
        self.send_response(200); self._cors(); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        Mock.seen_auth.append(self.headers.get("Authorization"))
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = req["messages"][-1]["content"]
        Mock.calls.append(req["messages"][0]["content"][:40])
        if "REQUEST TEXTS" in user:
            payload = json.loads(user.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0])
            items = [{"id": p["id"], "rights": [], "authorizes_deletion": "delet" in p["text"].lower() or "erase" in p["text"].lower(), "negated": False, "confidence": 0.9} for p in payload]
            content = json.dumps({"items": items})
        else:
            m = re.search(r"Candidates: \[(.*?)\]", user)
            c = re.findall(r"'([^']+)'", m.group(1)) if m else []
            content = json.dumps({"choose": c[0] if c else None, "reason": "mock"})
        out = json.dumps({"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 120, "completion_tokens": 30}}).encode()
        self.send_response(200); self._cors(); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)


def shot(page, name):
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"))


def state(page, expr):
    return page.evaluate(f"(() => {{ const s = window.__gda.Store.get(); return {expr}; }})()")


def wait_run_done(page, timeout=600000):
    page.wait_for_function("['done','error','cancelled'].includes(window.__gda.Store.get().run.status)", timeout=timeout)
    return state(page, "s.run.status")


def main():
    srv = serve_repo()
    mock = socketserver.TCPServer(("127.0.0.1", 8799), Mock); threading.Thread(target=mock.serve_forever, daemon=True).start()
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:300]))
        page.on("console", lambda m: m.type == "error" and errors.append("console: " + m.text[:300]))
        page.goto("http://127.0.0.1:8765/docs/index.html?debug")

        # 1. engine boots
        page.wait_for_function("window.__gda && ['ready','error'].includes(window.__gda.Store.get().engine.status)", timeout=240000)
        check("engine boots (Pyodide + sqlite3 + pypdf)", state(page, "s.engine.status") == "ready", str(state(page, "s.engine.error")))
        check("pypdf available for PDF evidence", state(page, "s.engine.info.pdf"))
        shot(page, "01-run")

        # 2. demo scenario run (offline), compared with its hand-written expected output
        page.click("text=1_connector_recreation")
        page.wait_for_function("window.__gda.Store.get().datasets && Object.values(window.__gda.Store.get().datasets).some(d => d.info && d.info.ok)", timeout=60000)
        page.click("button:has-text('Run audit'):visible")
        check("demo run finishes", wait_run_done(page) == "done", str(state(page, "s.run.error")))
        check("run button is enabled again after a run", page.locator("button:has-text('Run audit'):visible").is_enabled())
        res = state(page, "s.result")
        exp = json.loads(next(csv.DictReader(open(ROOT / "code/evaluation/custom_cases/1_connector_recreation/expected_output.csv", encoding="utf-8")))["steps_json"])
        check("demo output equals the hand-written expected steps", res["cases"][0]["steps"] == exp)
        check("scored: status 100% / precision 100% / recall 100%", res["metrics"] and res["metrics"]["status_acc"] == 1 and res["metrics"]["precision"] == 1 and res["metrics"]["recall"] == 1)
        stages = state(page, "Object.keys(s.run.stages)")
        check("live stage events received (evidence, intent, linking, solve, scoring)", all(k in stages for k in ("evidence", "intent", "linking", "solve", "scoring")), str(stages))
        shot(page, "02-run-done")

        # 3. navigation + results drawer
        for view in ("inputs", "agents", "results", "evaluation", "monitor", "vault", "guide"):
            page.click(f".sidebar >> text={view.capitalize()}")
            page.wait_for_timeout(150)
            check(f"view '{view}' renders", state(page, "s.view") == view and page.locator(".main h1").first.is_visible())
            if view == "results":
                page.click("tbody tr >> nth=0")
                page.wait_for_selector(".drawer")
                check("case drawer opens with the plan", page.locator(".drawer .step").count() >= 5)
                shot(page, "03-case-drawer")
                page.keyboard.press("Escape")
                check("Esc closes the drawer", page.locator(".drawer").count() == 0)
            if view == "inputs":
                page.wait_for_selector("text=Reported status", timeout=30000)
                check("inputs explorer loads requests/evidence/rules", page.locator("table.t tbody tr").count() >= 1)
                page.click(".tabs >> text=Evidence files"); page.wait_for_selector("text=Observations")
                check("evidence tab shows per-file parser stats after a run", page.locator("table.t tbody tr td.num >> nth=1").inner_text().strip() not in ("", "-"))
                page.click(".tabs >> text=Policy rules"); page.wait_for_selector("text=Required action")
                shot(page, "03b-inputs")
            if view == "agents":
                shot(page, "04-agents")
            if view == "monitor":
                shot(page, "05-monitor")

        # 4. demo suite: 8 / 8 exact
        page.click(".sidebar >> text=Evaluation")
        page.click("button:has-text('Run suite')")
        page.wait_for_function("window.__gda.Store.get().tools.suite", timeout=180000)
        suite = state(page, "s.tools.suite")
        check("demo suite: all 8 scenarios exact", len(suite["datasets"]) == 8 and all(d["exact"] for d in suite["datasets"]), json.dumps([d["name"] for d in suite["datasets"] if not d["exact"]]))
        shot(page, "06-evaluation")

        # 5. vault lifecycle + key hygiene
        page.click(".sidebar >> text=Vault")
        page.click("text=Use a session-only vault") if False else None
        page.fill("input[type=password] >> nth=0", PASS); page.fill("input[type=password] >> nth=1", PASS)
        page.click("button:has-text('Create vault')")
        page.wait_for_selector("text=Stored keys")
        check("vault created and unlocked", state(page, "s.vault.phase") == "unlocked")
        page.click("button:has-text('Add key')")
        page.select_option(".dialog select", "custom")
        page.fill(".dialog input[type=password]", SECRET)
        page.fill(".dialog input[placeholder*='openrouter']", "http://127.0.0.1:8799/v1")
        page.fill(".dialog input[placeholder='provider default'] >> nth=0", "")
        page.fill(".dialog input[placeholder*='model id']", "mock-model")
        page.click(".dialog button:has-text('Test key')")
        page.wait_for_selector(".dialog .banner")
        check("test-key reaches the provider and lists models", "Key works" in page.inner_text(".dialog .banner"), page.inner_text(".dialog .banner"))
        page.click(".dialog button:has-text('Store key')")
        page.wait_for_function("window.__gda.Store.get().vault.providers.includes('custom')", timeout=20000)
        check("stored key activates the provider in the engine", True)
        stored = page.evaluate("JSON.stringify(Object.fromEntries(Object.entries(localStorage)))")
        check("secret is NOT in localStorage in plaintext", SECRET not in stored and "ciphertext" not in stored.lower() or SECRET not in stored)
        check("masked key shown (last 4 only)", "••••••cdef" in page.inner_text(".main"))
        shot(page, "07-vault")
        page.click("button:has-text('Lock now')")
        page.wait_for_selector("text=Vault locked")
        check("locking clears providers from the engine", state(page, "s.vault.providers.length") == 0)
        page.fill("#unlock-pass", "wrong passphrase"); page.click("button:has-text('Unlock')")
        page.wait_for_selector("text=Wrong passphrase")
        check("wrong passphrase rejected", True)
        page.reload(); page.wait_for_function("window.__gda && window.__gda.Store.get().engine.status==='ready'", timeout=240000)
        check("after reload the vault is locked but persisted", state(page, "s.vault.phase") == "locked" and state(page, "s.vault.items.length") == 1)
        page.click(".sidebar >> text=Vault")
        page.fill("#unlock-pass", PASS); page.click("button:has-text('Unlock')")
        page.wait_for_selector("text=Stored keys")
        page.wait_for_function("window.__gda.Store.get().vault.providers.includes('custom')", timeout=20000)
        check("unlock with the right passphrase restores the key", True)

        # 6. hybrid mode through the mock provider
        page.click(".sidebar >> text=Run")
        page.click("text=1_connector_recreation")                       # datasets are intentionally not persisted across reloads
        page.wait_for_function("Object.values(window.__gda.Store.get().datasets).some(d => d.info && d.info.ok)", timeout=60000)
        page.click("button:has-text('Hybrid')")
        page.wait_for_timeout(200)
        page.click("button:has-text('Run audit'):visible")
        check("hybrid run finishes", wait_run_done(page) == "done", str(state(page, "s.run.error")))
        res2 = state(page, "s.result")
        check("hybrid: model calls recorded", len(res2["llm"]["calls"]) >= 1, str(res2["llm"]["calls"][:2]))
        check("hybrid: output unchanged vs offline", res2["cases"][0]["steps"] == exp)
        check("hybrid: provider saw the key only as a Bearer header", any(a == f"Bearer {SECRET}" for a in Mock.seen_auth if a))
        blob = json.dumps(res2) + json.dumps(state(page, "s.run.logs"))
        check("key never appears in results or logs", SECRET not in blob)
        shot(page, "08-hybrid")

        # 7. themes + responsive
        page.click("button[aria-label=Appearance]")
        page.click(".menu >> text=Paper (light)")
        page.click("button[aria-label=violet]")
        try:
            page.wait_for_function("document.documentElement.dataset.base==='paper' && document.documentElement.dataset.accent==='violet'", timeout=5000)
            ok_theme = True
        except Exception:
            ok_theme = False
        check("theme switch applies base + accent", ok_theme, page.evaluate("document.documentElement.dataset.base+'/'+document.documentElement.dataset.accent"))
        check("theme persists to storage", page.evaluate("JSON.parse(localStorage.getItem('gda.prefs.v1')).base") == "paper")
        shot(page, "09-light-violet")
        page.click(".menu >> text=AMOLED black"); page.click("button[aria-label=emerald]"); page.keyboard.press("Escape")
        page.mouse.click(700, 500)
        page.set_viewport_size({"width": 390, "height": 844})
        page.click(".bottomnav >> text=Results")
        page.wait_for_timeout(300)
        overflow = page.evaluate("Math.max(document.documentElement.scrollWidth - window.innerWidth, document.querySelector('.main').scrollWidth - document.querySelector('.main').clientWidth)")
        check("mobile: no horizontal page overflow (results)", overflow <= 1, f"overflow {overflow}px")
        shot(page, "10-mobile-results")
        page.click(".bottomnav >> text=Run"); page.wait_for_timeout(300)
        overflow = page.evaluate("Math.max(document.documentElement.scrollWidth - window.innerWidth, document.querySelector('.main').scrollWidth - document.querySelector('.main').clientWidth)")
        check("mobile: no horizontal page overflow (run)", overflow <= 1, f"overflow {overflow}px")
        shot(page, "11-mobile-run")
        page.set_viewport_size({"width": 1440, "height": 900})

        # 8. exports
        page.click(".sidebar >> text=Results")
        with page.expect_download() as dl:
            page.click("button:has-text('output.csv')")
        text = Path(dl.value.path()).read_text(encoding="utf-8")
        check("output.csv export has header + row", text.startswith("case_id,deletion_status,steps_json") and len(text.splitlines()) == 2)

        # 9. full dataset parity (slow)
        if FULL:
            page.click(".sidebar >> text=Run")
            page.click("button:has-text('Offline')")
            page.click("button:has-text('Upload')")
            t0 = time.time()
            page.set_input_files("input[webkitdirectory]", str(ROOT / "dataset"))
            page.wait_for_function("Object.values(window.__gda.Store.get().datasets).some(d => d.kind==='upload' && d.info && d.info.ok)", timeout=300000)
            info = state(page, "Object.values(s.datasets).find(d => d.kind==='upload').info")
            check("full dataset uploads and validates", info["ok"] and info["requests"] == 518 and info["evidence_present"] == info["evidence_files"], json.dumps(info)[:200])
            page.click("button:has-text('Run audit'):visible")
            status = wait_run_done(page, timeout=1500000)
            dt = time.time() - t0
            check("full dataset run finishes in the browser", status == "done", str(state(page, "s.run.error")) + f" {dt:.0f}s")
            full = state(page, "s.result")
            got = {c["case_id"]: (c["status"], c["steps"]) for c in full["cases"]}
            ref = {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"])) for r in csv.DictReader(open(ROOT / "output.csv", encoding="utf-8"))}
            diff = [k for k in ref if got.get(k) != ref[k]]
            check("full dataset: browser output == CLI output.csv (518 rows)", len(got) == 518 and not diff, f"{len(diff)} differing: {diff[:5]}")
            check("full dataset: no gold for the evaluation requests (nothing to score)", full["metrics"] is None)
            print(f"   full run wall time (upload + audit): {dt:.0f}s; engine {full['summary']['duration_ms'] / 1000:.0f}s")
            # samples: scored against sample_output.csv, must reproduce the documented metrics
            page.select_option("select >> nth=0", "sample_deletion_requests.csv") if False else page.select_option("label:has-text('Cases to audit') select", "sample_deletion_requests.csv")
            page.click("button:has-text('Run audit'):visible")
            check("sample requests run finishes", wait_run_done(page, timeout=900000) == "done", str(state(page, "s.run.error")))
            m = state(page, "s.result.metrics")
            check("samples scored: status 32/32, precision 1.000, recall 0.969, exact 27/32",
                  m and m["status"] == 32 and m["n"] == 32 and m["precision"] == 1.0 and abs(m["recall"] - 0.9689) < 1e-3 and m["exact"] == 27, str(m and {k: m[k] for k in ("status", "n", "precision", "recall", "exact")}))
            shot(page, "12-full-results")
            # ablation + link recovery on the full dataset (labels-free and sample-scored checks from evaluation_report.md)
            page.click(".sidebar >> text=Run")
            page.select_option("label:has-text('Cases to audit') select", "deletion_requests.csv")
            page.click(".sidebar >> text=Evaluation")
            page.click("button:has-text('Run ablation')")
            page.wait_for_function("window.__gda.Store.get().tools.ablation", timeout=900000)
            ab = state(page, "s.tools.ablation")
            byname = {r["name"]: r for r in ab["results"]}
            check("ablation: default changes 0 outputs", byname["Default (all switches on)"]["changed"] == 0)
            check("ablation: alignment off changes many outputs and lowers sample recall",
                  byname["No workflow-run alignment"]["changed"] > 100 and byname["No workflow-run alignment"]["metrics"]["recall"] < byname["Default (all switches on)"]["metrics"]["recall"],
                  json.dumps({k: (v["changed"], v["metrics"] and round(v["metrics"]["recall"], 3)) for k, v in byname.items()}))
            shot(page, "13-ablation")
            page.click("button:has-text('Run test')")
            page.wait_for_function("window.__gda.Store.get().tools.recovery", timeout=900000)
            rc = state(page, "s.tools.recovery")
            check("link recovery: >= 97% of hidden proven accounts re-derived", rc["accuracy"] >= 0.97 and rc["proven_accounts"] > 200, json.dumps({k: rc[k] for k in ("accuracy", "proven_accounts", "ambiguity")}))
            # cancel + restart
            page.click(".sidebar >> text=Run")
            page.click("button:has-text('Run audit'):visible")
            page.wait_for_function("window.__gda.Store.get().run.status==='running'", timeout=20000)
            page.wait_for_timeout(1500)
            page.click("button:has-text('Stop'):visible")
            page.wait_for_function("window.__gda.Store.get().engine.status==='ready' && window.__gda.Store.get().run.status==='cancelled'", timeout=240000)
            check("cancel restarts the engine and it becomes ready again", True)

        check("no uncaught page/console errors", not errors, " | ".join(errors[:4]))
        browser.close()
    srv.shutdown(); mock.shutdown()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
