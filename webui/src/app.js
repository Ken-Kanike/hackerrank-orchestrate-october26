/* ========================================================================================
   App shell
   ======================================================================================== */
const NAV = [
  ["run", "Run", "play", "Execute the audit"],
  ["inputs", "Inputs", "database", "What is audited"],
  ["agents", "Agents", "bot", "Live pipeline"],
  ["results", "Results", "list", "Cases & plans"],
  ["evaluation", "Evaluation", "gauge", "Accuracy & tests"],
  ["monitor", "Monitor", "activity", "Tracing & logs"],
  ["vault", "Vault", "key-round", "Provider keys"],
  ["guide", "Guide", "book-open", "Docs"],
];

function ThemeMenu() {
  const prefs = useStore((s) => s.prefs);
  const [open, setOpen] = useState(false);
  const ref = useRef();
  useEffect(() => { if (!open) return; const f = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }; document.addEventListener("pointerdown", f); return () => document.removeEventListener("pointerdown", f); }, [open]);
  return html`<div style="position:relative" ref=${ref}>
    <button class="btn ghost icon-only" aria-label="Appearance" aria-expanded=${open} onClick=${() => setOpen(!open)}><${Icon} n="palette" /></button>
    ${open && html`<div class="menu" role="dialog" aria-label="Appearance"><div class="col" style="gap:14px">
      <div><div class="small muted" style="margin-bottom:6px">Base</div><div class="col" style="gap:4px">${THEMES.base.map(([k, l]) => html`<button class="nav-item" aria-current=${prefs.base === k ? "page" : null} onClick=${() => setPrefs({ base: k })}><${Icon} n=${k === "paper" ? "sun" : "moon"} cls="sm" /><span class="lbl">${l}</span></button>`)}</div></div>
      <div><div class="small muted" style="margin-bottom:6px">Accent</div><div class="row wrap">${THEMES.accent.map(([k, c]) => html`<button class="swatch" aria-label=${k} aria-pressed=${prefs.accent === k ? "true" : "false"} style=${"background:" + c} onClick=${() => setPrefs({ accent: k })}></button>`)}</div></div>
      <div><div class="small muted" style="margin-bottom:6px">Density</div><${Seg} label="Density" value=${prefs.density} onChange=${(v) => setPrefs({ density: v })} options=${[["comfortable", "Comfortable"], ["compact", "Compact"]]} /></div>
    </div></div>`}</div>`;
}

function EnginePill() {
  const eng = useStore((s) => s.engine), run = useStore((s) => s.run);
  const running = run.status === "running";
  const cur = Object.entries(run.stages).find(([, v]) => v.status === "running");
  const [k, t, d] = eng.status === "ready" ? (running ? ["primary", cur ? "working: " + cur[0] : "working", "run"] : ["ok", "engine ready", "ok"]) : eng.status === "error" ? ["err", "engine error", "err"] : ["warn", "engine starting", "run"];
  return html`<${Badge} kind=${k}><span class=${cls("dot", d)}></span><span class="hide-sm">${t}</span><span class="show-sm">${eng.status === "ready" ? (running ? "busy" : "ready") : "…"}</span><//>`;
}

function Toasts() {
  const ts = useStore((s) => s.toasts);
  return html`<div class="toasts" aria-live="polite">${ts.map((t) => html`<div class="toast"><${Icon} n=${{ ok: "circle-check", error: "circle-x", info: "info" }[t.kind] || "info"} /><div class="grow">${t.msg}</div></div>`)}</div>`;
}

function App() {
  const view = useStore((s) => s.view), prefs = useStore((s) => s.prefs), vault = useStore((s) => s.vault), res = useStore((s) => s.result), run = useStore((s) => s.run);
  useEffect(() => {
    const r = document.documentElement;
    r.dataset.base = prefs.base; r.dataset.accent = prefs.accent; r.dataset.density = prefs.density;
    document.querySelector('meta[name="theme-color"]').setAttribute("content", getComputedStyle(document.body).backgroundColor);
  }, [prefs.base, prefs.accent, prefs.density]);
  useEffect(() => { ls.set("gda.view", view); }, [view]);
  useEffect(() => {
    const f = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); if (Store.get().view !== "vault") Actions.runAudit(); } };
    addEventListener("keydown", f); return () => removeEventListener("keydown", f);
  }, []);
  const go = (v) => { Store.set({ view: v }); document.querySelector(".main")?.scrollTo(0, 0); };
  const counts = { results: res ? res.cases.length : null };
  const locked = vault.phase === "locked" || vault.phase === "none";
  const View = { run: RunView, inputs: InputsView, agents: AgentsView, results: ResultsView, evaluation: EvaluationView, monitor: MonitorView, vault: VaultView, guide: GuideView }[view] || RunView;
  const gh = repoUrl();
  return html`<div class=${cls("app", !prefs.sidebar && "collapsed")}>
    <header class="topbar"><button class="btn ghost icon-only hide-sm" aria-label="Toggle sidebar" onClick=${() => setPrefs({ sidebar: !prefs.sidebar })}><${Icon} n="panel-left" /></button>
      <div class="brand"><div class="logo"><${Icon} n="ghost" /></div><div><span>Ghost Data Auditor</span><small class="hide-sm">deletion audit agent</small></div></div>
      <div class="spacer"></div><${EnginePill} />
      <button class="btn ghost sm" onClick=${() => go("vault")} aria-label=${locked ? "Vault locked" : "Vault unlocked"} data-tip=${locked ? "Vault locked / not created" : "Vault unlocked"}><${Icon} n=${locked ? "lock" : "lock-open"} cls="sm" /><span class="hide-sm">${vault.providers.length ? vault.providers.join(" · ") : "no keys"}</span></button>
      ${gh && html`<a class="btn ghost icon-only hide-sm" href=${gh} target="_blank" rel="noopener" aria-label="Repository"><${Icon} n="external-link" /></a>`}
      <${ThemeMenu} /></header>
    <nav class="sidebar" aria-label="Primary">${NAV.map(([k, l, ic, d], i) => html`${i === 6 && html`<div class="nav-sec">Setup</div>`}<button class="nav-item" aria-current=${view === k ? "page" : null} onClick=${() => go(k)} data-tip=${!prefs.sidebar ? l : null}><${Icon} n=${ic} /><span class="lbl">${l}</span>${counts[k] != null && html`<span class="count">${counts[k]}</span>`}${k === "run" && run.status === "running" && html`<span class="count"><span class="dot run"></span></span>`}</button>`)}
      <div class="spacer"></div><div class="hint hide-sm" style="padding:8px 10px;${prefs.sidebar ? "" : "display:none"}">Runs entirely in your browser.<br/>No server, no telemetry.</div></nav>
    <main class="main" id="main"><${View} /></main>
    <nav class="bottomnav" aria-label="Primary">${NAV.map(([k, l, ic]) => html`<button aria-current=${view === k ? "page" : null} onClick=${() => go(k)}><${Icon} n=${ic} /><span>${l}</span></button>`)}</nav>
    <${Toasts} /></div>`;
}

/* ---------- boot ---------- */
installTooltips();
Vault.init();
render(html`<${App} />`, document.getElementById("root"));
Engine.start().then(() => Vault.pushEnv()).catch(() => {});
if (new URLSearchParams(location.search).has("debug")) window.__gda = { Store, Engine, Datasets, Vault, Actions };   // test/automation handle (opt-in)
