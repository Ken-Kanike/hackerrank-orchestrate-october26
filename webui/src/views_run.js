/* ========================================================================================
   Run + Agents views
   ======================================================================================== */
const DEMO_TEXT = {
  "1_connector_recreation": "Active connector re-created a search record before audit_at",
  "2_expired_retention": "Expired security-audit retention must be deleted, valid kept",
  "3_late_export_must_not_decide": "A file captured after audit_at must not decide the state",
  "4_replica_drift": "Primary says gone, read replica still holds the profile",
  "5_injection_non_deletion": "Prompt injection inside a non-deletion request",
  "6_old_hash_analytics": "Historical email recognised only via an analytics hash",
  "7_complete_clean": "Fully compliant deletion with retained records",
  "8_tombstone_and_restore": "Tombstone exposing identifiers + restorable backup",
};
function repoUrl() {
  const m = location.hostname.match(/^(.+)\.github\.io$/);
  if (m) { const repo = location.pathname.split("/").filter(Boolean)[0]; return `https://github.com/${m[1]}/${repo || m[1] + ".github.io"}`; }
  return null;
}
function defaultDatasetUrl() {
  const m = location.hostname.match(/^(.+)\.github\.io$/);
  if (m) { const repo = location.pathname.split("/").filter(Boolean)[0]; return `https://raw.githubusercontent.com/${m[1]}/${repo || ""}/main/dataset/`; }
  return location.origin + location.pathname.replace(/[^/]*$/, "") + "../dataset/";
}

function EngineBanner() {
  const eng = useStore((s) => s.engine);
  if (eng.status === "ready") return null;
  if (eng.status === "error") return html`<${Banner} kind="err"><div class="strong">The engine failed to start</div><div class="small">${eng.error}</div>
    <div class="small muted" style="margin-top:6px">The Python runtime is downloaded from the jsDelivr CDN: check the connection or content blockers, then <a href="#" onClick=${(e) => { e.preventDefault(); location.reload(); }}>reload</a>.</div><//>`;
  const last = eng.steps[eng.steps.length - 1];
  return html`<${Banner} kind="info" icon="loader-circle"><div class="strong">Starting the audit engine…</div>
    <div class="small muted">${last ? last.detail : "Preparing"} · first start downloads ~10 MB of Python runtime, then it is cached by the browser.</div><div style="margin-top:8px"><${Progress} indeterminate=${true} /></div><//>`;
}

function DatasetCard() {
  const datasets = useStore((s) => s.datasets), active = useStore((s) => s.activeDataset), ready = useStore((s) => s.engine.status === "ready");
  const [tab, setTab] = useState("demo");
  const [url, setUrl] = useState(defaultDatasetUrl());
  const [busy, setBusy] = useState(null);
  const [over, setOver] = useState(false);
  const dirRef = useRef(), fileRef = useRef();

  const guard = async (label, fn) => { setBusy(label); try { await fn(); } catch (e) { toast(e.message, "error", 7000); } finally { setBusy(null); } };
  const onFiles = (list) => guard("Reading files…", async () => { const arr = await readFileList(list); const name = (list[0].webkitRelativePath || list[0].name).split("/")[0]; await Datasets.registerFiles(name, arr, "upload"); });
  const list = Object.values(datasets);

  return html`<${Card} title="1 · Dataset" sub="Where the audit reads from. Files stay in your browser." icon="database">
    <${Tabs} value=${tab} onChange=${setTab} options=${[["demo", "Demo scenarios", "flask-conical"], ["upload", "Upload", "upload"], ["url", "From URL", "globe"]]} />
    <div class="col" style="margin-top:14px">
      ${tab === "demo" && html`<div class="grid g-auto" style="grid-template-columns:repeat(auto-fill,minmax(250px,1fr))">${Object.keys(DEMO).map((n) => html`
        <button class="card flat" style="padding:12px;text-align:left;cursor:pointer;color:inherit" disabled=${!ready || !!busy} onClick=${() => guard("Loading…", () => Datasets.registerDemo(n))}>
          <div class="row between"><span class="strong small mono">${n}</span><${Icon} n="chevron-right" cls="sm" /></div><div class="hint" style="margin-top:4px">${DEMO_TEXT[n] || ""}</div></button>`)}</div>
        <div class="hint">Eight small, fully synthetic datasets with hand-written expected outputs. Pick one to load it, or run them all from Evaluation → Demo suite.</div>`}
      ${tab === "upload" && html`<div class=${cls("drop", over && "over")}
          onDragOver=${(e) => { e.preventDefault(); setOver(true); }} onDragLeave=${() => setOver(false)}
          onDrop=${(e) => { e.preventDefault(); setOver(false); guard("Reading dropped files…", async () => { const arr = await readDropped(e.dataTransfer); await Datasets.registerFiles("dropped", arr, "upload"); }); }}
          onClick=${() => dirRef.current.click()}>
          <${Icon} n="folder-open" cls="lg" /><div class="strong" style="color:var(--foreground);margin-top:6px">Drop the <span class="mono">dataset/</span> folder (or a .zip) here</div>
          <div class="small">needs deletion_requests.csv, user_identities.csv, user_audit_log.csv, system_activity.csv, deletion_rules.csv, evidence_files.csv + evidence/</div></div>
        <div class="row wrap"><button class="btn outline sm" onClick=${() => dirRef.current.click()}><${Icon} n="folder-open" cls="sm" />Choose folder</button>
          <button class="btn outline sm" onClick=${() => fileRef.current.click()}><${Icon} n="file-archive" cls="sm" />Choose .zip or files</button></div>
        <input ref=${dirRef} type="file" webkitdirectory multiple hidden onChange=${(e) => e.target.files.length && onFiles(e.target.files)} />
        <input ref=${fileRef} type="file" multiple hidden onChange=${(e) => e.target.files.length && onFiles(e.target.files)} />`}
      ${tab === "url" && html`<label class="field">Base URL of a dataset folder (CORS must allow it; raw.githubusercontent.com does)
          <input class="input mono" value=${url} onInput=${(e) => setUrl(e.target.value)} spellcheck="false" /></label>
        <div class="row"><button class="btn outline sm" disabled=${!ready || !!busy} onClick=${() => guard("Downloading dataset…", () => Datasets.fromUrl(url, "remote dataset"))}><${Icon} n="download" cls="sm" />Load dataset</button>
          <span class="hint">Downloads the six CSVs and every file listed in evidence_files.csv.</span></div>`}
      ${busy && html`<div class="row small muted"><${Icon} n="loader-circle" cls="sm spin" />${busy}</div>`}
    </div>
    ${list.length > 0 && html`<div class="sep" style="margin:16px 0"></div><div class="col gap-sm">${list.map((d) => html`<${DatasetRow} d=${d} active=${d.id === active} />`)}</div>`}
  <//>`;
}
function DatasetRow({ d, active }) {
  const info = d.info;
  const missing = info ? Object.entries(info.present).filter(([, v]) => !v).map(([k]) => k) : [];
  return html`<div class=${cls("card flat", active && "sel")} style=${"padding:10px 12px;" + (active ? "border-color:var(--primary)" : "")}>
    <div class="row" style="gap:12px"><button class="row grow" style="background:none;border:0;cursor:pointer;text-align:left;gap:10px;min-width:0" onClick=${() => Store.set({ activeDataset: d.id })} aria-pressed=${active}>
      <span class=${cls("dot", active ? "run" : "")} style=${active ? "animation:none" : ""}></span>
      <div class="grow" style="min-width:0"><div class="strong trunc">${d.name}</div>
        <div class="hint">${info ? html`${fmt.num(info.requests)} requests · ${info.evidence_present ?? info.evidence_files}/${info.evidence_files} evidence files${info.gold?.length ? " · gold: " + info.gold.join(", ") : ""}` : "inspecting…"} · ${fmt.bytes(d.bytes)}</div></div></button>
      ${info && (info.ok && (info.evidence_present ?? info.evidence_files) === info.evidence_files ? html`<${Badge} kind="ok"><${Icon} n="circle-check" cls="sm" />complete<//>` : html`<${Badge} kind="warn" tip=${missing.join(", ") || "some evidence files missing"}><${Icon} n="triangle-alert" cls="sm" />${missing.length ? "missing " + missing.length : "partial"}<//>`)}
      <button class="btn ghost icon-only sm" aria-label=${"Remove " + d.name} onClick=${() => Datasets.remove(d.id)}><${Icon} n="trash-2" cls="sm" /></button></div></div>`;
}

function ConfigCard() {
  const cfg = useStore((s) => s.cfg), prov = useStore((s) => s.vault.providers), ds = useStore((s) => s.datasets[s.activeDataset]);
  const [adv, setAdv] = useState(false);
  const set = (p) => Store.set((s) => ({ cfg: { ...s.cfg, ...p } }));
  const setFlag = (k, v) => set({ flags: { ...cfg.flags, [k]: v } });
  const gold = ds?.info?.gold || [];
  const changed = Object.keys(FLAG_DEFAULTS).some((k) => cfg.flags[k] !== FLAG_DEFAULTS[k]);
  return html`<${Card} title="2 · Configure" sub="Same engine and code path as the command line." icon="sliders-horizontal">
    <div class="col gap-lg">
      <div class="row between wrap"><div><div class="small strong">Execution mode</div><div class="hint">Offline is fully deterministic and needs no keys.</div></div>
        <${Seg} label="Mode" value=${cfg.mode} onChange=${(v) => set({ mode: v })} options=${[["offline", "Offline", "cpu"], ["hybrid", "Hybrid (LLM)", "brain"]]} /></div>
      ${cfg.mode === "hybrid" && (prov.length === 0
        ? html`<${Banner} kind="warn"><div class="strong">No provider keys loaded</div><div class="small">Hybrid will fall back to the deterministic path, exactly like the CLI. Add or unlock keys in the <a href="#" onClick=${(e) => { e.preventDefault(); Store.set({ view: "vault" }); }}>Vault</a>.</div><//>`
        : html`<${Banner} kind="ok"><div class="small">Providers in priority order: ${prov.map((p) => html`<${Badge} kind="primary">${p}<//> `)}</div><//>`)}
      ${cfg.mode === "hybrid" && html`<${Switch} label="Read screenshots with a vision model" hint="Sets states for catalog rows and corroborates catalog links. Cached by image hash." on=${cfg.vision} onChange=${(v) => set({ vision: v })} />
        <${Switch} label="Ignore the LLM cache" hint="Force fresh model calls (costs tokens)." on=${cfg.refresh} onChange=${(v) => set({ refresh: v })} />`}
      ${ds?.info?.extra_requests?.length > 0 && html`<label class="field">Cases to audit<select class="select" value=${cfg.requestsFile} onChange=${(e) => set({ requestsFile: e.target.value })}>
          <option value="deletion_requests.csv">deletion_requests.csv (${fmt.num(ds.info.requests)} evaluation requests)</option>
          <option value="sample_deletion_requests.csv">sample_deletion_requests.csv (${fmt.num(ds.info.sample_requests)} public samples, scored against sample_output.csv)</option></select></label>`}
      <div class="grid g3">
        <label class="field">Score against<select class="select" value=${cfg.gold} onChange=${(e) => set({ gold: e.target.value })}>
          <option value="auto">Auto (${resolveGold({ ...cfg, gold: "auto" }, ds?.info) || "none"})</option><option value="none">No scoring</option>${gold.map((g) => html`<option value=${g}>${g}</option>`)}</select></label>
        <label class="field">Limit cases (blank = all)<input class="input" inputmode="numeric" placeholder="all" value=${cfg.limit} onInput=${(e) => set({ limit: e.target.value.replace(/\D/g, "") })} /></label>
        <label class="field">Row order<select class="select" value=${cfg.sort} onChange=${(e) => set({ sort: e.target.value })}><option value="numeric">Numeric (input order)</option><option value="lexicographic">Lexicographic</option></select></label>
      </div>
      <div><button class="btn ghost sm" onClick=${() => setAdv(!adv)}><${Icon} n=${adv ? "chevron-down" : "chevron-right"} cls="sm" />Engine switches ${changed && html`<${Badge} kind="warn">modified<//>`}</button>
        ${adv && html`<div class="col" style="margin-top:10px">
          <${Banner} kind="info"><div class="small">Every heuristic has a switch so its effect is measurable (Evaluation → Ablation). Defaults reproduce the shipped output exactly.</div><//>
          ${FLAGS.map((f) => html`<${Switch} label=${f.label} hint=${f.hint} on=${cfg.flags[f.k]} onChange=${(v) => setFlag(f.k, v)} disabled=${(f.k === "USE_INVESTIGATOR" || f.k === "INVESTIGATOR_APPLY") && cfg.mode !== "hybrid"} />`)}
          <div><button class="btn outline sm" onClick=${() => set({ flags: { ...FLAG_DEFAULTS } })}><${Icon} n="refresh-cw" cls="sm" />Reset to defaults</button></div></div>`}</div>
    </div><//>`;
}

function StageList({ run, stages }) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => { if (run.status !== "running") return; const t = setInterval(() => setNow(Date.now() / 1000), 500); return () => clearInterval(t); }, [run.status]);
  const ids = [...new Set([...STAGES.map((s) => s.id).filter((id) => run.stages[id]), ...Object.keys(run.stages).filter((id) => !STAGES.find((s) => s.id === id))])];
  return html`<div class="col gap-sm">${ids.map((id) => {
    const st = run.stages[id], meta = STAGES.find((s) => s.id === id) || { name: id, icon: "activity" };
    const frac = st.total ? Math.min(1, (st.done || 0) / st.total) : st.status === "done" ? 1 : 0;
    const el = st.status === "running" ? (now - st.startedAt) * 1000 : st.ms;
    return html`<div><div class="row small" style="gap:8px">
      ${st.status === "running" ? html`<${Icon} n="loader-circle" cls="sm spin" />` : st.status === "done" ? html`<${Icon} n="circle-check" cls="sm" />` : st.status === "failed" ? html`<${Icon} n="circle-x" cls="sm" />` : html`<${Icon} n="circle-dashed" cls="sm" />`}
      <span class="grow trunc" style=${st.status === "done" ? "color:var(--muted-fg)" : ""}>${meta.name}</span>
      <span class="mono tiny muted">${st.total && st.status === "running" ? (st.done || 0) + "/" + st.total : ""} ${el != null ? fmt.ms(el) : ""}</span></div>
      ${st.status === "running" && html`<div style="margin:4px 0 2px 22px"><${Progress} value=${frac} indeterminate=${!st.total} /></div>`}</div>`;
  })}${ids.length === 0 && html`<div class="hint">Stages appear here as the engine works.</div>`}</div>`;
}

function LogView({ logs, max = 60, height }) {
  const ref = useRef();
  useEffect(() => { const e = ref.current; if (e) e.scrollTop = e.scrollHeight; }, [logs.length]);
  const tail = logs.slice(-max);
  return html`<div class="log" ref=${ref} style=${height ? `max-height:${height}px` : ""} role="log" aria-live="off">${tail.map((l) => html`<div class="ln"><span class="tm">${fmt.time(l.t)}</span><span class=${cls("lv", l.level)}>${l.level}</span><span>${l.msg}</span></div>`)}${tail.length === 0 && html`<span class="faint">no output yet</span>`}</div>`;
}

function RunPanel() {
  const run = useStore((s) => s.run), eng = useStore((s) => s.engine), ds = useStore((s) => s.datasets[s.activeDataset]), cfg = useStore((s) => s.cfg), busy = useStore((s) => s.tools.busy);
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => { if (run.status !== "running") return; const t = setInterval(() => setNow(Date.now() / 1000), 500); return () => clearInterval(t); }, [run.status]);
  const running = run.status === "running";
  const can = eng.status === "ready" && ds?.info?.ok && !running;
  return html`<${Card} title="3 · Run" icon="play" cls="sticky-card" actions=${running && html`<${Badge} kind="primary"><span class="dot run"></span>running ${fmt.ms((now - run.startedAt) * 1000)}<//>`}>
    <div class="col">
      <div class="small muted">${ds ? html`<span class="strong" style="color:var(--foreground)">${ds.name}</span> · ${cfg.mode}${cfg.limit ? " · first " + cfg.limit + " cases" : ""}` : "Choose a dataset to begin."}</div>
      <div class="row">${!running ? html`<button class="btn lg grow" disabled=${!can || !!busy} onClick=${Actions.runAudit}><${Icon} n="play" />Run audit <span class="kbd" style="margin-left:4px;color:inherit;background:transparent;border-color:currentColor;opacity:.6">Ctrl ↵</span></button>`
        : html`<button class="btn lg danger grow" onClick=${Actions.cancel}><${Icon} n="square" />Stop</button>`}</div>
      ${eng.status !== "ready" && html`<div class="hint">Waiting for the engine…</div>`}
      ${run.status === "error" && html`<${Banner} kind="err"><div class="strong small">Run failed</div><pre class="code" style="margin-top:6px;max-height:140px">${run.error}</pre><//>`}
      ${run.status === "cancelled" && html`<${Banner} kind="warn"><div class="small">Cancelled.</div><//>`}
      <${StageList} run=${run} />
      <${LogView} logs=${run.logs} max=40 height=210 />
    </div><//>`;
}

function Summary() {
  const res = useStore((s) => s.result);
  if (!res) return null;
  const s = res.summary, m = res.metrics, st = s.status;
  const parts = [{ label: "COMPLETE", value: st.COMPLETE || 0, color: "var(--ok)" }, { label: "INCOMPLETE", value: st.INCOMPLETE || 0, color: "var(--warn)" }, { label: "NOT_APPLICABLE", value: st.NOT_APPLICABLE || 0, color: "var(--faint)" }];
  const calls = res.llm.calls, tin = calls.reduce((a, c) => a + (c.in || 0), 0), tout = calls.reduce((a, c) => a + (c.out || 0), 0);
  return html`<${Card} title="Latest result" sub=${`${res.meta.dataset} · ${s.mode} · run ${s.run_id}`} icon="activity" actions=${html`<button class="btn outline sm" onClick=${() => Store.set({ view: "results" })}>Open results<${Icon} n="chevron-right" cls="sm" /></button>`}>
    <div class="grid g4 keep2">
      <${Stat} k="Cases" v=${fmt.num(s.cases)} d=${fmt.ms(s.duration_ms)} icon="list" />
      <${Stat} k="Validator flags" v=${s.validator_flags} d=${s.validator_flags ? "contract violations" : "contract clean"} icon="shield-check" color=${s.validator_flags ? "var(--err)" : "var(--ok)"} />
      <${Stat} k="Ambiguous links" v=${s.ambiguous} d="decided by tie-break, flagged" icon="git-compare" />
      <${Stat} k="LLM tokens" v=${fmt.num(tin + tout)} d=${`${calls.filter((c) => !c.cached).length} fresh · ${calls.filter((c) => c.cached).length} cached calls`} icon="brain" />
    </div>
    <div class="row wrap" style="gap:28px;margin-top:16px;align-items:center">
      <${Donut} parts=${parts} label=${fmt.num(s.cases)} sub="cases" />
      <div class="col grow" style="min-width:220px"><${Legend} items=${parts} />${m && html`<div class="grid g4 keep2" style="margin-top:6px">
        <${Stat} k="Status accuracy" v=${fmt.pct(m.status_acc)} d=${`${m.status}/${m.n}`} />
        <${Stat} k="Step precision" v=${fmt.pct(m.precision)} /><${Stat} k="Step recall" v=${fmt.pct(m.recall)} /><${Stat} k="Exact sequence" v=${fmt.pct(m.exact_acc)} d=${`${m.exact}/${m.n}`} /></div>`}</div>
    </div><//>`;
}

function MobileRunBar() {
  const run = useStore((s) => s.run), eng = useStore((s) => s.engine), ds = useStore((s) => s.datasets[s.activeDataset]), busy = useStore((s) => s.tools.busy);
  const running = run.status === "running", can = eng.status === "ready" && ds?.info?.ok && !running && !busy;
  return html`<div class="runbar show-sm">${running ? html`<button class="btn lg danger" style="width:100%" onClick=${Actions.cancel}><${Icon} n="square" />Stop</button>`
    : html`<button class="btn lg" style="width:100%" disabled=${!can} onClick=${Actions.runAudit}><${Icon} n="play" />${ds ? "Run audit" : "Choose a dataset first"}</button>`}</div>`;
}

function RunView() {
  return html`<div class="page">
    <section class="card hero"><div class="row between wrap" style="gap:16px"><div><h1>Ghost Data Auditor</h1>
      <p class="muted" style="max-width:640px;margin-top:6px">Runs the real deletion-audit engine in your browser. A workflow can say <em>Complete</em> while data lingers; this audits what the evidence proves at <span class="mono">audit_at</span>, applies the deletion policy, and writes the ordered remediation and verification plan.</p></div>
      <div class="row wrap"><${Badge} kind="primary"><${Icon} n="shield-check" cls="sm" />runs locally<//><${Badge}><${Icon} n="lock" cls="sm" />keys never leave your browser<//></div></div></section>
    <${EngineBanner} />
    <div class="grid" style="grid-template-columns:minmax(0,1.55fr) minmax(300px,1fr);align-items:start" id="run-grid">
      <div class="col" style="gap:20px"><${DatasetCard} /><${ConfigCard} /><${Summary} /></div>
      <div style="position:sticky;top:0" id="run-side"><${RunPanel} /></div>
    </div>
    <${MobileRunBar} />
    <style>@media (max-width:1000px){ #run-grid{grid-template-columns:minmax(0,1fr)!important} #run-side{position:static!important} }</style>
  </div>`;
}

/* ---------------------------------------------------------------- Agents */
function AgentsView() {
  const run = useStore((s) => s.run), cfg = useStore((s) => s.cfg), llmCalls = useStore((s) => s.run.llm);
  const [sel, setSel] = useState("intent");
  const stageStatus = (s) => {
    const st = run.stages[s.id];
    if (st) return st.status;
    if (s.id === "vision" && !(cfg.mode === "hybrid" && cfg.vision)) return "skipped";
    if (s.id === "investigator" && !(cfg.mode === "hybrid" && cfg.flags.USE_INVESTIGATOR)) return "skipped";
    if (s.id === "ghost" && !cfg.flags.USE_GHOST_SWEEP) return "skipped";
    return "idle";
  };
  const label = { idle: "idle", pending: "queued", running: "working", done: "done", failed: "failed", skipped: "off for this run" };
  const kind = { done: "ok", running: "primary", failed: "err", skipped: "", idle: "", pending: "" };
  const cur = STAGES.find((s) => s.id === sel);
  const cst = run.stages[sel];
  const taskCounts = {}; llmCalls.forEach((c) => { taskCounts[c.task] = (taskCounts[c.task] || 0) + 1; });
  return html`<div class="page">
    <div><h1>Agents</h1><p class="muted small" style="margin-top:4px">The pipeline is a chain of specialised agents. The core is deterministic code; the three marked <${Icon} n="brain" cls="sm" /> may use an LLM, always behind guardrails.</p></div>
    <div class="agents" role="list">${STAGES.map((s, i) => { const status = stageStatus(s); const st = run.stages[s.id];
      return html`<button role="listitem" class=${cls("node", sel === s.id && "sel", status)} onClick=${() => setSel(s.id)}>
          <div class="nm"><span class="idx">${i + 1}</span><${Icon} n=${s.icon} />${s.name}${s.llm && html`<${Icon} n="brain" cls="sm" />`}</div>
          <div class="st"><span class=${cls("dot", status === "done" ? "ok" : status === "running" ? "run" : status === "failed" ? "err" : "")}></span>${label[status]}${st?.ms != null ? " · " + fmt.ms(st.ms) : ""}</div>
          ${st && st.total && html`<div style="margin-top:8px"><${Progress} value=${(st.done || 0) / st.total} /></div>`}</button>`; })}</div>
    <div class="grid g2" style="align-items:start">
      <${Card} title=${cur.name} icon=${cur.icon} sub=${cur.llm ? "May use an LLM (guarded)" : "Deterministic"} actions=${html`<${Badge} kind=${kind[stageStatus(cur)]}>${label[stageStatus(cur)]}<//>`}>
        <div class="col"><p>${cur.role}</p>
          ${cur.needs && html`<div class="hint">Active when: ${cur.needs}</div>`}
          ${cst?.stats && Object.keys(cst.stats).length > 0 && html`<dl class="kv">${Object.entries(cst.stats).map(([k, v]) => html`<dt>${k.replace(/_/g, " ")}</dt><dd class="mono">${typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>`)}</dl>`}
          ${cst?.ms != null && html`<div class="small muted">Last duration: <span class="mono">${fmt.ms(cst.ms)}</span></div>`}
          ${!cst && html`<div class="hint">Run an audit to see live statistics for this agent.</div>`}</div><//>
      <${Card} title="Guardrails & principles" icon="shield-check">
        <ul class="col small" style="margin:0;padding-left:18px;gap:8px">
          <li><b>Claims are not proof.</b> Reported statuses and activity results never decide a state; only evidence captured by <span class="mono">audit_at</span> does.</li>
          <li><b>Rules are the guardrail.</b> The LLM can confirm a weak "not deletion" or rescue a cue-less paraphrase at high confidence; it never overrides a strong rule verdict.</li>
          <li><b>Read-only investigator.</b> Tool loop with evidence-backed candidates only; advisory unless you switch on <i>apply</i>.</li>
          <li><b>Policy is data.</b> <span class="mono">deletion_rules.csv</span> drives actions; unknown categories are flagged, never silently defaulted.</li>
          <li><b>Everything is traceable.</b> Each case keeps resolved user, link reasons, deciding evidence, rule and flags.</li></ul>
        ${Object.keys(taskCounts).length > 0 && html`<div class="sep" style="margin:14px 0"></div><div class="small muted">LLM activity this run</div>
          <div class="row wrap" style="margin-top:6px">${Object.entries(taskCounts).map(([k, v]) => html`<${Badge} mono=${true}>${k} × ${v}<//>`)}</div>`}<//>
    </div></div>`;
}
