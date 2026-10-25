/* ========================================================================================
   core: store, persistence, engine client (Pyodide worker), dataset registry, vault (WebCrypto)
   ======================================================================================== */
const { h, render, Fragment } = preact;
const { useState, useEffect, useRef, useMemo, useCallback } = preactHooks;
const html = htm.bind(h);

const $json = (id) => JSON.parse(document.getElementById(id).textContent);
const PYSRC = $json("pysrc");
const DEMO = $json("demo-data");
const WORKER_SRC = document.getElementById("worker-src").textContent;

/* ---------- persistence (never throws: storage can be unavailable) ---------- */
const ls = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
};

/* ---------- tiny store ---------- */
const Store = (() => {
  let s = {};
  const subs = new Set();
  return {
    get: () => s,
    init(o) { s = o; },
    set(p) { s = { ...s, ...(typeof p === "function" ? p(s) : p) }; subs.forEach((f) => f()); },
    sub(f) { subs.add(f); return () => subs.delete(f); },
  };
})();
function useStore(sel) {
  const selRef = useRef(sel); selRef.current = sel;
  const [v, setV] = useState(() => sel(Store.get()));
  useEffect(() => Store.sub(() => { const nv = selRef.current(Store.get()); setV((p) => (Object.is(p, nv) ? p : nv)); }), []);
  return v;
}

/* ---------- formatting ---------- */
const fmt = {
  pct: (x, d = 1) => (x == null || isNaN(x) ? "-" : (100 * x).toFixed(d) + "%"),
  num: (x) => (x == null ? "-" : Number(x).toLocaleString()),
  ms: (x) => (x == null ? "-" : x < 1000 ? Math.round(x) + " ms" : x < 60000 ? (x / 1000).toFixed(1) + " s" : Math.floor(x / 60000) + "m " + Math.round((x % 60000) / 1000) + "s"),
  usd: (x) => (x == null ? "-" : x === 0 ? "$0" : x < 0.01 ? "$" + x.toFixed(5) : "$" + x.toFixed(4)),
  bytes: (n) => (n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(0) + " KB" : (n / 1048576).toFixed(1) + " MB"),
  time: (t) => new Date(t * 1000).toLocaleTimeString([], { hour12: false }) + "." + String(Math.floor((t % 1) * 1000)).padStart(3, "0"),
};
const cls = (...a) => a.filter(Boolean).join(" ");
function download(name, text, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
async function copyText(t) { try { await navigator.clipboard.writeText(t); return true; } catch (e) { return false; } }
const uid = () => Math.random().toString(36).slice(2, 10);

/* ---------- constants ---------- */
const STAGES = [
  { id: "vision", name: "Vision reader", icon: "eye", llm: true, role: "Reads screenshots with a vision model (hybrid mode). Output only sets a state and cross-checks catalog links; it never creates links.", needs: "hybrid + vision" },
  { id: "evidence", name: "Evidence reader", icon: "database", role: "Parses every evidence file (7 log dialects, JSON bundles, SQLite snapshots incl. replicas, handover text, PDFs, catalog events) into normalized observations.", needs: "" },
  { id: "catalog", name: "Catalog verifier", icon: "shield-check", role: "Checks each data-catalog link against the identifiers read from its artifact: contradicted links are dropped, unknown identities kept and flagged.", needs: "" },
  { id: "intent", name: "Intent gate", icon: "scan-search", llm: true, role: "Decides whether the request text really authorizes deletion: multilingual rights lexicon with negation/scope limits, instruction stripping, optional batched LLM classification with rules as guardrail.", needs: "" },
  { id: "linking", name: "Identity & linker", icon: "network", role: "Resolves current + historical identifiers, links resources by identity, then by workflow-run reconstruction; adds recreated copies via lineage edges.", needs: "" },
  { id: "investigator", name: "Investigator", icon: "bot", llm: true, role: "Bounded tool-calling loop over ambiguous links. Advisory: read-only tools, evidence-backed choices only, never changes the output unless explicitly enabled.", needs: "hybrid + ambiguous links" },
  { id: "ghost", name: "Ghost sweeper", icon: "ghost", role: "Defence in depth: greps all evidence for the subject's identifiers and flags unexplained resources and un-redacted records.", needs: "" },
  { id: "solve", name: "State, policy & validator", icon: "scale", role: "Reconstructs each resource's state at audit_at, applies deletion_rules.csv as data, compiles the ordered plan and validates the contract.", needs: "" },
  { id: "scoring", name: "Scorer", icon: "clipboard-check", role: "Scores predictions against a gold file: status accuracy, step precision/recall/F1, per-field, position, Kendall tau, LCS.", needs: "gold file" },
];
const FLAGS = [
  { k: "STRICT_TIME", label: "Strict time model", hint: "State and citations only from files captured by audit_at" },
  { k: "USE_LINEAGE", label: "Lineage propagation", hint: "Copies recreated by connectors/restores before audit_at join the case" },
  { k: "USE_ACTIVITY_CHECKS", label: "Activity state checks", hint: "CHECK_* events as weak observations" },
  { k: "USE_RUN_ALIGNMENT", label: "Workflow-run alignment", hint: "Second-offset reconstruction for accounts no identifier reaches" },
  { k: "USE_GHOST_SWEEP", label: "Ghost sweep", hint: "Grep all evidence for subject identifiers" },
  { k: "PARTITION_SINGLE_CASE_USERS_ONLY", label: "Earlier-request cut-off for multi-case users only", hint: "Fixes pre-request evidence loss for single-request users" },
  { k: "USE_INVESTIGATOR", label: "Investigator agent (hybrid)", hint: "Advisory tool loop on ambiguous links" },
  { k: "INVESTIGATOR_APPLY", label: "Let the investigator change links", hint: "Off by default; deterministic choice normally stands" },
];
const FLAG_DEFAULTS = { STRICT_TIME: true, USE_LINEAGE: true, USE_ACTIVITY_CHECKS: true, USE_RUN_ALIGNMENT: true, USE_GHOST_SWEEP: true, PARTITION_SINGLE_CASE_USERS_ONLY: true, USE_INVESTIGATOR: true, INVESTIGATOR_APPLY: false };
const PROVIDERS = {
  anthropic: { name: "Anthropic", host: "api.anthropic.com", placeholder: "sk-ant-...", model: "claude-opus-5-5", note: "Sent with the browser-access header" },
  openai: { name: "OpenAI", host: "api.openai.com", placeholder: "sk-...", model: "gpt-4.1" },
  gemini: { name: "Google Gemini", host: "generativelanguage.googleapis.com", placeholder: "AIza...", model: "gemini-2.5-pro" },
  groq: { name: "Groq", host: "api.groq.com", placeholder: "gsk_...", model: "openai/gpt-oss-120b" },
  custom: { name: "Custom (OpenAI-compatible)", host: "your endpoint", placeholder: "key (optional for local servers)", model: "model id", needsUrl: true },
};
const THEMES = {
  base: [["obsidian", "Obsidian"], ["amoled", "AMOLED black"], ["graphite", "Graphite"], ["paper", "Paper (light)"]],
  accent: [["blue", "#3b82f6"], ["violet", "#8b5cf6"], ["emerald", "#10b981"], ["amber", "#f59e0b"], ["rose", "#f43f5e"], ["cyan", "#06b6d4"], ["mono", "#e4e4e7"]],
};
const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];
const STATUS_COLOR = { COMPLETE: "var(--ok)", INCOMPLETE: "var(--warn)", NOT_APPLICABLE: "var(--faint)" };

/* ---------- initial state ---------- */
const prefs = ls.get("gda.prefs.v1", {});
Store.init({
  prefs: { base: "obsidian", accent: "blue", density: "comfortable", sidebar: true, lockMin: 10, ...prefs },
  view: ls.get("gda.view", "run"),
  engine: { status: "idle", steps: [], error: null, info: null, startedAt: null },
  datasets: {},
  activeDataset: null,
  cfg: { mode: "offline", vision: true, flags: { ...FLAG_DEFAULTS }, limit: "", requestsFile: "deletion_requests.csv", refresh: false, gold: "auto", sort: "numeric", poolSamples: true },
  run: { status: "idle", stages: {}, logs: [], llm: [], startedAt: null, finishedAt: null, error: null, label: "" },
  result: null,
  history: [],
  vault: { phase: "none", items: [], persistent: true, error: null, providers: [] },
  selectedCase: null,
  toasts: [],
  tools: { ablation: null, recovery: null, suite: null, busy: null },
});
function setPrefs(p) {
  const np = { ...Store.get().prefs, ...p };
  Store.set({ prefs: np });
  ls.set("gda.prefs.v1", np);
}
function toast(msg, kind = "info", ms = 4200) {
  const id = uid();
  Store.set((s) => ({ toasts: [...s.toasts, { id, msg, kind }].slice(-3) }));
  setTimeout(() => Store.set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), Math.min(ms, 5000));
}

/* ========================================================================================
   Engine client
   ======================================================================================== */
const Engine = {
  worker: null, seq: 0, pending: new Map(), bootPromise: null, loaded: new Set(), buffer: [], raf: 0,

  start() {
    if (this.bootPromise) return this.bootPromise;
    Store.set({ engine: { status: "booting", steps: [], error: null, info: null, startedAt: Date.now() } });
    const url = URL.createObjectURL(new Blob([WORKER_SRC], { type: "text/javascript" }));
    this.worker = new Worker(url);
    this.worker.onmessage = (e) => this._msg(e.data);
    this.worker.onerror = (e) => this._fatal("Worker crashed: " + (e.message || "unknown error"));
    this.loaded = new Set();
    this.bootPromise = this._rpc({ cmd: "init", pysrc: PYSRC }).then((info) => {
      Store.set((s) => ({ engine: { ...s.engine, status: "ready", info } }));
      return info;
    }).catch((err) => { this._fatal(err.message); throw err; });
    return this.bootPromise;
  },
  _fatal(msg) { Store.set((s) => ({ engine: { ...s.engine, status: "error", error: msg } })); },
  _rpc(m, transfer) {
    return new Promise((res, rej) => { const id = ++this.seq; this.pending.set(id, { res, rej }); this.worker.postMessage({ ...m, id }, transfer || []); });
  },
  _msg(d) {
    if (typeof d === "string") { let m; try { m = JSON.parse(d); } catch (e) { return; } if (m.type === "event") this._event(m.e); return; }
    if (d.type === "boot") { Store.set((s) => ({ engine: { ...s.engine, steps: [...s.engine.steps, { step: d.step, detail: d.detail, t: Date.now() }] } })); return; }
    const p = this.pending.get(d.id); if (!p) return; this.pending.delete(d.id);
    d.ok ? p.res(d.result) : p.rej(new Error(d.error));
  },
  _event(e) { this.buffer.push(e); if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = 0; const b = this.buffer; this.buffer = []; applyEvents(b); }); },
  async call(fn, ...args) { await this.start(); const r = await this._rpc({ cmd: "call", fn, args }); return r; },
  async callJson(fn, ...args) { return JSON.parse(await this.call(fn, ...args)); },
  async write(files) { await this.start(); return this._rpc({ cmd: "write", files }, files.map((f) => f.data).filter((d) => d instanceof ArrayBuffer)); },
  /** Cancel = terminate the worker (a running Python call cannot be interrupted) and boot a fresh one. */
  restart() {
    try { this.worker.terminate(); } catch (e) { /* ignore */ }
    this.pending.forEach((p) => p.rej(new Error("cancelled")));
    this.pending.clear(); this.bootPromise = null; this.loaded = new Set();
    return this.start();
  },
};

function applyEvents(batch) {
  Store.set((s) => {
    const run = { ...s.run, stages: { ...s.run.stages }, logs: s.run.logs.slice(-600), llm: s.run.llm };
    for (const e of batch) {
      const t = e.t;
      if (e.kind === "stage_start") { run.stages[e.id] = { status: "running", startedAt: t, total: e.total || null, done: 0 }; run.logs.push({ t, level: "stage", msg: "▶ " + e.id + (e.total ? " (" + e.total + ")" : "") }); }
      else if (e.kind === "stage_end") {
        const { kind, t: _t, id, ms, ok, error, ...stats } = e;
        run.stages[id] = { ...(run.stages[id] || {}), status: ok ? "done" : "failed", ms, stats, error, endedAt: t, done: run.stages[id]?.total || run.stages[id]?.done };
        run.logs.push({ t, level: ok ? "stage" : "error", msg: (ok ? "✔ " : "✘ ") + id + " " + fmt.ms(ms) + (error ? " - " + error : "") });
      } else if (e.kind === "progress") {
        if (run.stages[e.stage]) run.stages[e.stage] = { ...run.stages[e.stage], done: e.done, total: e.total || run.stages[e.stage].total };
        else run.stages[e.stage] = { status: "running", startedAt: t, done: e.done, total: e.total };
        if (e.label) run.logs.push({ t, level: "info", msg: e.stage + " " + e.done + "/" + e.total + " - " + e.label });
      } else if (e.kind === "log") run.logs.push({ t, level: e.level, msg: e.msg });
      else if (e.kind === "llm") {
        run.llm = [...run.llm, e];
        run.logs.push({ t, level: "llm", msg: (e.cached ? "cache " : "call  ") + (e.provider || "-") + " " + (e.model || "") + " " + e.task + (e.ok ? "" : " FAILED") + (e.cached ? "" : " " + fmt.ms(e.ms)) + " in/out " + (e.in ?? 0) + "/" + (e.out ?? 0) });
      }
    }
    return { run };
  });
}

/* ========================================================================================
   Datasets
   ======================================================================================== */
function normalizeFiles(entries) {
  // entries: [{path, data: ArrayBuffer}]; strip everything above the folder that holds deletion_requests.csv
  const marker = entries.filter((e) => /(^|\/)deletion_requests\.csv$/.test(e.path)).sort((a, b) => a.path.length - b.path.length)[0];
  if (!marker) return null;
  const prefix = marker.path.slice(0, marker.path.length - "deletion_requests.csv".length);
  return entries.filter((e) => e.path.startsWith(prefix)).map((e) => ({ path: e.path.slice(prefix.length), data: e.data }));
}
async function readFileList(files) {
  const out = [];
  for (const f of files) out.push({ path: (f.webkitRelativePath || f.relativePath || f.name).replace(/\\/g, "/"), data: await f.arrayBuffer() });
  return out;
}
async function readDropped(dt) {
  const items = [...(dt.items || [])].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
  const out = [];
  const walk = async (entry, base) => {
    if (entry.isFile) { const f = await new Promise((r, j) => entry.file(r, j)); out.push({ path: base + entry.name, data: await f.arrayBuffer() }); }
    else if (entry.isDirectory) {
      const rd = entry.createReader();
      let batch;
      do { batch = await new Promise((r, j) => rd.readEntries(r, j)); for (const e of batch) await walk(e, base + entry.name + "/"); } while (batch.length);
    }
  };
  for (const it of items) await walk(it, "");
  return out.length ? out : readFileList([...(dt.files || [])]);
}

const Datasets = {
  store: new Map(),   // id -> { files: [{path, data}] | zip: ArrayBuffer }
  async registerFiles(name, entries, kind) {
    const isZip = entries.length === 1 && /\.zip$/i.test(entries[0].path);
    let files = null;
    if (!isZip) {
      files = normalizeFiles(entries);
      if (!files) throw new Error("No deletion_requests.csv found. Select the dataset folder (or a .zip of it).");
    }
    const id = (kind || "ds") + "_" + uid();
    this.store.set(id, isZip ? { zip: entries[0].data } : { files });
    Store.set((s) => ({ datasets: { ...s.datasets, [id]: { id, name, kind: kind || "upload", fileCount: isZip ? null : files.length, bytes: (isZip ? entries[0].data.byteLength : files.reduce((a, f) => a + f.data.byteLength, 0)), info: null } }, activeDataset: id }));
    await this.ensure(id);
    return id;
  },
  async registerDemo(name) {
    const existing = Object.values(Store.get().datasets).find((d) => d.kind === "demo" && d.name === name);
    if (existing) { Store.set({ activeDataset: existing.id }); return existing.id; }
    const enc = new TextEncoder();
    const entries = Object.entries(DEMO[name]).map(([p, t]) => ({ path: p, data: enc.encode(t).buffer }));
    return this.registerFiles(name, entries, "demo");
  },
  async ensure(id) {
    await Engine.start();
    const rec = this.store.get(id); if (!rec) throw new Error("dataset missing");
    if (!Engine.loaded.has(id)) {
      if (rec.zip) {
        await Engine.write([{ path: id + ".zip", data: rec.zip.slice(0) }]);
        await Engine.call("unzip_to", "/app/data/" + id + ".zip", "/app/data/" + id);
      } else {
        const chunk = 40; // keep messages moderate
        for (let i = 0; i < rec.files.length; i += chunk)
          await Engine.write(rec.files.slice(i, i + chunk).map((f) => ({ path: id + "/" + f.path, data: f.data.slice(0) })));
      }
      Engine.loaded.add(id);
    }
    const info = await Engine.callJson("dataset_info", "/app/data/" + id);
    Store.set((s) => ({ datasets: { ...s.datasets, [id]: { ...s.datasets[id], info } } }));
    return info;
  },
  async fromUrl(base, name) {
    base = base.replace(/\/?$/, "/");
    const get = async (p, bin) => { const r = await fetch(base + p); if (!r.ok) throw new Error(p + " -> HTTP " + r.status); return bin ? r.arrayBuffer() : r.text(); };
    const top = ["deletion_requests.csv", "user_identities.csv", "user_audit_log.csv", "system_activity.csv", "deletion_rules.csv", "evidence_files.csv"];
    const optional = ["sample_deletion_requests.csv", "sample_output.csv", "expected_output.csv"];
    const entries = [];
    for (const f of top) entries.push({ path: f, data: await get(f, true) });
    for (const f of optional) { try { entries.push({ path: f, data: await get(f, true) }); } catch (e) { /* optional */ } }
    const man = new TextDecoder().decode(entries.find((e) => e.path === "evidence_files.csv").data).trim().split(/\r?\n/);
    const cols = man[0].split(","); const pi = cols.indexOf("file_path");
    const paths = man.slice(1).map((l) => l.split(",")[pi]);
    let done = 0;
    for (const p of paths) {
      try { entries.push({ path: p, data: await get(p, true) }); } catch (e) { /* missing evidence is reported by dataset_info */ }
      if (++done % 10 === 0) Store.set((s) => ({ engine: { ...s.engine } }));
    }
    return this.registerFiles(name || base, entries, "url");
  },
  async remove(id) {
    this.store.delete(id);
    try { await Engine.start(); await Engine._rpc({ cmd: "remove", dir: id }); Engine.loaded.delete(id); } catch (e) { /* ignore */ }
    Store.set((s) => { const d = { ...s.datasets }; delete d[id]; return { datasets: d, activeDataset: s.activeDataset === id ? null : s.activeDataset }; });
  },
};

/* ========================================================================================
   Vault - AES-GCM encrypted with a key derived (PBKDF2-SHA256, 310k iterations) from the passphrase.
   Plaintext keys exist only in this tab's memory while unlocked; they are sent to the engine worker as environment variables and to
   the provider you configured - nowhere else.
   ======================================================================================== */
const Vault = (() => {
  const KEY = "gda.vault.v1";
  const enc = new TextEncoder(), dec = new TextDecoder();
  const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
  const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  let cryptoKey = null, idleTimer = null;
  const ITER = 310000;

  async function derive(pass, salt, iter) {
    const base = await crypto.subtle.importKey("raw", enc.encode(pass), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: iter, hash: "SHA-256" }, base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }
  async function seal(key, obj) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, enc.encode(JSON.stringify(obj)));
    return { iv: b64(iv), ct: b64(ct) };
  }
  async function open(key, box) {
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(box.iv) }, key, unb64(box.ct));
    return JSON.parse(dec.decode(pt));
  }
  const rec = () => ls.get(KEY, null);
  const setV = (p) => Store.set((s) => ({ vault: { ...s.vault, ...p } }));
  const mask = (k) => (k ? "••••••" + k.slice(-4) : "");

  const api = {
    exists: () => !!rec(),
    init() {
      const r = rec();
      setV({ phase: r ? "locked" : "none", items: r ? r.items.map((i) => ({ id: i.id, provider: i.provider, label: i.label, base_url: i.base_url, model: i.model, vision_model: i.vision_model, secret: null })) : [] });
    },
    async create(pass) {
      const salt = crypto.getRandomValues(new Uint8Array(16));
      cryptoKey = await derive(pass, salt, ITER);
      const verifier = await seal(cryptoKey, { ok: "gda-vault" });
      const ok = ls.set(KEY, { v: 1, salt: b64(salt), iter: ITER, verifier, items: [] });
      setV({ phase: "unlocked", items: [], persistent: ok, error: ok ? null : "Browser storage unavailable: vault is memory-only." });
      api.touch();
    },
    async unlock(pass) {
      const r = rec(); if (!r) throw new Error("No vault");
      const k = await derive(pass, unb64(r.salt), r.iter);
      try { await open(k, r.verifier); } catch (e) { throw new Error("Wrong passphrase"); }
      cryptoKey = k;
      const items = [];
      for (const i of r.items) items.push({ id: i.id, provider: i.provider, label: i.label, base_url: i.base_url, model: i.model, vision_model: i.vision_model, secret: (await open(k, i.box)).key });
      setV({ phase: "unlocked", items, error: null });
      api.touch(); await api.pushEnv();
    },
    sessionOnly() { cryptoKey = null; setV({ phase: "session", items: [], persistent: false }); api.touch(); },
    async add(item) {
      const full = { id: uid(), ...item };
      const items = [...Store.get().vault.items, full];
      if (Store.get().vault.phase === "unlocked" && cryptoKey) {
        const r = rec();
        r.items.push({ id: full.id, provider: full.provider, label: full.label, base_url: full.base_url, model: full.model, vision_model: full.vision_model, box: await seal(cryptoKey, { key: full.secret }) });
        ls.set(KEY, r);
      }
      setV({ items }); await api.pushEnv();
    },
    async remove(id) {
      const r = rec(); if (r) { r.items = r.items.filter((i) => i.id !== id); ls.set(KEY, r); }
      setV({ items: Store.get().vault.items.filter((i) => i.id !== id) }); await api.pushEnv();
    },
    async lock() {
      cryptoKey = null; clearTimeout(idleTimer);
      setV({ providers: [] });                                  // UI truth first; the engine worker is cleared right after
      const r = rec();
      setV({ phase: r ? "locked" : "none", items: (r ? r.items : []).map((i) => ({ id: i.id, provider: i.provider, label: i.label, base_url: i.base_url, model: i.model, vision_model: i.vision_model, secret: null })) });
      if (Engine.bootPromise && Store.get().engine.status === "ready") { try { await Engine.call("set_env", "{}"); setV({ providers: [] }); } catch (e) { /* busy */ } }
    },
    wipe() { ls.del(KEY); cryptoKey = null; setV({ phase: "none", items: [], providers: [] }); if (Store.get().engine.status === "ready") Engine.call("set_env", "{}").catch(() => {}); },
    exportBlob() { return JSON.stringify(rec() || {}); },
    importBlob(text) { const o = JSON.parse(text); if (!o.salt || !o.verifier || !Array.isArray(o.items)) throw new Error("Not a vault export"); ls.set(KEY, o); api.init(); },
    touch() {
      clearTimeout(idleTimer);
      const m = Store.get().prefs.lockMin;
      if (m > 0 && Store.get().vault.phase === "unlocked") idleTimer = setTimeout(() => { api.lock(); toast("Vault auto-locked after " + m + " min idle", "info"); }, m * 60000);
    },
    buildEnv() {
      const env = {}, order = [];
      const by = {};
      for (const i of Store.get().vault.items) if (i.secret !== null) (by[i.provider] = by[i.provider] || []).push(i);
      for (const [prov, items] of Object.entries(by)) {
        const pre = prov.toUpperCase();
        items.forEach((it, n) => { env[`${pre}_API_KEY_${n + 1}`] = it.secret || (prov === "custom" ? "none" : ""); });
        if (items[0].model) env[`${pre}_MODEL1`] = items[0].model;
        if (items[0].vision_model) env[`${pre}_VISION_MODEL`] = items[0].vision_model;
        if (prov === "custom") env.CUSTOM_BASE_URL = items[0].base_url;
        order.push(prov);
      }
      const prio = Store.get().prefs.providerOrder || ["anthropic", "openai", "gemini", "groq", "custom"];
      env.LLM_PROVIDER_ORDER = [...prio.filter((p) => order.includes(p)), ...order.filter((p) => !prio.includes(p))].join(",");
      return env;
    },
    async pushEnv() {
      if (Store.get().engine.status !== "ready") return;
      try { const r = JSON.parse(await Engine.call("set_env", JSON.stringify(api.buildEnv()))); setV({ providers: r.providers }); } catch (e) { /* engine busy; run() pushes again */ }
    },
    mask,
  };
  return api;
})();
["pointerdown", "keydown"].forEach((ev) => addEventListener(ev, () => Vault.touch(), { passive: true }));
