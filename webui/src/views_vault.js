/* ========================================================================================
   Vault + Guide
   ======================================================================================== */
function strength(p) {
  let s = 0; if (p.length >= 8) s++; if (p.length >= 12) s++; if (/[a-z]/.test(p) && /[A-Z]/.test(p)) s++; if (/\d/.test(p)) s++; if (/[^\w\s]/.test(p)) s++;
  return Math.min(4, Math.max(p ? 1 : 0, s - (p.length < 8 ? 1 : 0)));
}
function PassField({ label, value, onInput, autoComplete = "off", id }) {
  const [show, setShow] = useState(false);
  return html`<label class="field">${label}<div style="position:relative"><input id=${id} class="input mono" type=${show ? "text" : "password"} value=${value} autocomplete=${autoComplete} spellcheck="false" onInput=${(e) => onInput(e.target.value)} style="padding-right:38px" />
    <button type="button" class="btn ghost icon-only sm" style="position:absolute;right:3px;top:3px" aria-label=${show ? "Hide" : "Show"} onClick=${() => setShow(!show)}><${Icon} n=${show ? "eye-off" : "eye"} cls="sm" /></button></div></label>`;
}

function AddKeyDialog({ onClose }) {
  const [prov, setProv] = useState("groq"), [label, setLabel] = useState(""), [secret, setSecret] = useState(""), [base, setBase] = useState(""), [model, setModel] = useState(""), [vmodel, setVmodel] = useState("");
  const [test, setTest] = useState(null), [busy, setBusy] = useState(false);
  const p = PROVIDERS[prov], busyRun = useStore((s) => s.run.status === "running"), ready = useStore((s) => s.engine.status === "ready");
  const item = () => ({ provider: prov, label: label || p.name + " key", secret: secret.trim(), base_url: base.trim(), model: model.trim(), vision_model: vmodel.trim() });
  const valid = (prov === "custom" ? /^https?:\/\//.test(base.trim()) : secret.trim().length > 8);
  return html`<${Dialog} title="Add a provider key" onClose=${onClose}><div class="col">
    <label class="field">Provider<select class="select" value=${prov} onChange=${(e) => { setProv(e.target.value); setTest(null); }}>${Object.entries(PROVIDERS).map(([k, v]) => html`<option value=${k}>${v.name}</option>`)}</select></label>
    <label class="field">Label (optional)<input class="input" value=${label} placeholder=${p.name + " key"} onInput=${(e) => setLabel(e.target.value)} /></label>
    <${PassField} label="API key" value=${secret} onInput=${(v) => { setSecret(v); setTest(null); }} />
    ${p.needsUrl && html`<label class="field">Base URL (OpenAI-compatible, ends before /chat/completions)<input class="input mono" value=${base} placeholder="https://openrouter.ai/api/v1  or  http://localhost:11434/v1" onInput=${(e) => setBase(e.target.value)} /></label>`}
    <div class="grid g2"><label class="field">Model override (optional)<input class="input mono" value=${model} placeholder=${p.model} onInput=${(e) => setModel(e.target.value)} /></label>
      <label class="field">Vision model (optional)<input class="input mono" value=${vmodel} placeholder="provider default" onInput=${(e) => setVmodel(e.target.value)} /></label></div>
    <div class="hint">Sent only to <span class="mono">${prov === "custom" ? (base || "your endpoint") : p.host}</span>, directly from your browser. ${p.note || ""}</div>
    ${test && html`<${Banner} kind=${test.ok ? "ok" : "err"}><div class="small">${test.ok ? `Key works: ${test.count} models visible (${(test.models || []).slice(0, 3).join(", ")}…)` : "Test failed: " + test.error}</div><//>`}
    <div class="row between wrap"><button class="btn outline" disabled=${!valid || busy || !ready || busyRun} onClick=${async () => { setBusy(true); setTest(await Actions.testKey(item())); setBusy(false); }}>${busy ? html`<${Icon} n="loader-circle" cls="sm spin" />` : html`<${Icon} n="zap" cls="sm" />`}Test key</button>
      <div class="row"><button class="btn ghost" onClick=${onClose}>Cancel</button><button class="btn" disabled=${!valid} onClick=${async () => { await Vault.add(item()); toast("Key stored in the vault", "ok"); onClose(); }}><${Icon} n="lock" cls="sm" />Store key</button></div></div></div><//>`;
}

function VaultView() {
  const v = useStore((s) => s.vault), prefs = useStore((s) => s.prefs), ready = useStore((s) => s.engine.status === "ready");
  const [pass, setPass] = useState(""), [pass2, setPass2] = useState(""), [err, setErr] = useState(""), [adding, setAdding] = useState(false), [tests, setTests] = useState({}), [working, setWorking] = useState(false);
  const impRef = useRef();
  const order = prefs.providerOrder || ["anthropic", "openai", "gemini", "groq", "custom"];
  const move = (p, d) => { const a = [...order]; const i = a.indexOf(p), j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; setPrefs({ providerOrder: a }); Vault.pushEnv(); };
  const st = strength(pass);
  const create = async () => { setErr(""); if (pass.length < 8) return setErr("Use at least 8 characters."); if (pass !== pass2) return setErr("Passphrases do not match."); setWorking(true); try { await Vault.create(pass); setPass(""); setPass2(""); toast("Vault created and unlocked", "ok"); } catch (e) { setErr(e.message); } setWorking(false); };
  const unlock = async () => { setErr(""); setWorking(true); try { await Vault.unlock(pass); setPass(""); toast("Vault unlocked", "ok"); } catch (e) { setErr(e.message); } setWorking(false); };
  const unlocked = v.phase === "unlocked" || v.phase === "session";
  return html`<div class="page"><div class="row between wrap"><div><h1>Vault</h1><p class="muted small" style="margin-top:4px">Bring your own provider keys to run the hybrid (LLM) mode. Nothing is sent to any server of ours - there isn't one.</p></div>
      ${unlocked && html`<div class="row"><${Badge} kind="ok"><${Icon} n="lock-open" cls="sm" />${v.phase === "session" ? "session only" : "unlocked"}<//><button class="btn outline sm" onClick=${() => Vault.lock()}><${Icon} n="lock" cls="sm" />Lock now</button></div>`}</div>
    ${v.error && html`<${Banner} kind="warn"><div class="small">${v.error}</div><//>`}
    ${v.phase === "none" && html`<div class="grid g2" style="align-items:start"><${Card} title="Create an encrypted vault" icon="lock" sub="Keys are stored in this browser, encrypted with your passphrase">
        <div class="col"><${PassField} label="Passphrase" value=${pass} onInput=${setPass} autoComplete="new-password" />
          <div class="row" style="gap:4px" aria-label="Passphrase strength">${[1, 2, 3, 4].map((i) => html`<i style=${`flex:1;height:4px;border-radius:2px;background:${i <= st ? ["", "var(--err)", "var(--warn)", "var(--info)", "var(--ok)"][st] : "var(--muted)"}`}></i>`)}</div>
          <${PassField} label="Repeat passphrase" value=${pass2} onInput=${setPass2} autoComplete="new-password" />
          ${err && html`<div class="small" style="color:var(--err)">${err}</div>`}
          <button class="btn" disabled=${working} onClick=${create}>${working ? html`<${Icon} n="loader-circle" cls="sm spin" />` : html`<${Icon} n="key-round" cls="sm" />`}Create vault</button>
          <div class="hint">There is no recovery: a forgotten passphrase means re-entering your keys (the encrypted blob is useless without it).</div></div><//>
      <${Card} title="Or: session only" icon="clock" sub="Nothing is written to storage"><div class="col"><p class="small">Keys live in this tab's memory and vanish when you close or reload it. Best for shared computers.</p><button class="btn outline" onClick=${() => Vault.sessionOnly()}><${Icon} n="timer" cls="sm" />Use a session-only vault</button></div><//></div>`}
    ${v.phase === "locked" && html`<${Card} title="Vault locked" icon="lock" sub=${`${v.items.length} key(s) stored`}><div class="col" style="max-width:420px">
        <${PassField} label="Passphrase" value=${pass} onInput=${setPass} autoComplete="current-password" id="unlock-pass" />${err && html`<div class="small" style="color:var(--err)">${err}</div>`}
        <div class="row"><button class="btn" disabled=${working || !pass} onClick=${unlock}>${working ? html`<${Icon} n="loader-circle" cls="sm spin" />` : html`<${Icon} n="lock-open" cls="sm" />`}Unlock</button>
          <button class="btn danger" onClick=${() => { if (confirm("Delete the vault and every stored key from this browser?")) Vault.wipe(); }}><${Icon} n="trash-2" cls="sm" />Wipe vault</button></div>
        <div class="list">${v.items.map((i) => html`<div class="row small muted"><${Icon} n="key-round" cls="sm" />${PROVIDERS[i.provider]?.name} · ${i.label}</div>`)}</div></div><//>`}
    ${unlocked && html`<${Card} title="Stored keys" icon="key-round" actions=${html`<button class="btn sm" onClick=${() => setAdding(true)}><${Icon} n="plus" cls="sm" />Add key</button>`}>
        ${v.items.length === 0 ? html`<${Empty} icon="key-round" title="No keys yet">Add a key for Anthropic, OpenAI, Gemini, Groq or any OpenAI-compatible endpoint.<//>` : html`<div class="col">${v.items.map((i) => html`<div class="card flat" style="padding:12px"><div class="row wrap" style="gap:12px">
          <div class="grow" style="min-width:200px"><div class="strong">${i.label}</div><div class="small muted">${PROVIDERS[i.provider]?.name} · <span class="mono">${Vault.mask(i.secret)}</span>${i.model ? " · " + i.model : ""}${i.base_url ? " · " + i.base_url : ""}</div></div>
          ${tests[i.id] && html`<${Badge} kind=${tests[i.id].ok ? "ok" : "err"} tip=${tests[i.id].error || ""}>${tests[i.id].ok ? tests[i.id].count + " models" : "failed"}<//>`}
          <button class="btn outline sm" disabled=${!ready} onClick=${async () => { setTests({ ...tests, [i.id]: { pending: true } }); const r = await Actions.testKey(i); setTests((t) => ({ ...t, [i.id]: r })); }}><${Icon} n="zap" cls="sm" />Test</button>
          <button class="btn ghost icon-only sm" aria-label=${"Remove " + i.label} onClick=${() => Vault.remove(i.id)}><${Icon} n="trash-2" cls="sm" /></button></div></div>`)}</div>`}<//>
      <div class="grid g2" style="align-items:start"><${Card} title="Provider priority" sub="Tried in this order; later ones are fallbacks" icon="workflow"><div class="col gap-sm">${order.map((p, i) => html`<div class="row"><span class="mono tiny faint" style="width:18px">${i + 1}</span><span class="grow">${PROVIDERS[p].name}</span>${v.providers.includes(p) ? html`<${Badge} kind="ok">active<//>` : html`<${Badge}>no key<//>`}
          <button class="btn ghost icon-only sm" aria-label="Move up" disabled=${i === 0} onClick=${() => move(p, -1)}><${Icon} n="chevron-down" cls="sm flip" /></button><button class="btn ghost icon-only sm" aria-label="Move down" disabled=${i === order.length - 1} onClick=${() => move(p, 1)}><${Icon} n="chevron-down" cls="sm" /></button></div>`)}</div><//>
        <${Card} title="Security" icon="shield-check"><div class="col">
          ${v.phase === "unlocked" && html`<label class="field">Auto-lock after idle<select class="select" value=${prefs.lockMin} onChange=${(e) => { setPrefs({ lockMin: +e.target.value }); Vault.touch(); }}>${[[0, "Never"], [5, "5 minutes"], [10, "10 minutes"], [30, "30 minutes"], [60, "1 hour"]].map(([m, l]) => html`<option value=${m}>${l}</option>`)}</select></label>`}
          <div class="row wrap"><button class="btn outline sm" disabled=${v.phase !== "unlocked"} onClick=${() => download("gda-vault-export.json", Vault.exportBlob(), "application/json")}><${Icon} n="download" cls="sm" />Export (encrypted)</button>
            <button class="btn outline sm" onClick=${() => impRef.current.click()}><${Icon} n="upload" cls="sm" />Import</button>
            <button class="btn danger sm" onClick=${() => { if (confirm("Delete the vault and every stored key from this browser?")) Vault.wipe(); }}><${Icon} n="trash-2" cls="sm" />Wipe</button></div>
          <input ref=${impRef} type="file" accept="application/json" hidden onChange=${async (e) => { try { Vault.importBlob(await e.target.files[0].text()); toast("Vault imported - unlock it with its passphrase", "ok"); } catch (x) { toast(x.message, "error"); } }} /></div><//></div>`}
    <${Card} title="How your keys are protected" icon="shield-check"><ul class="col small" style="margin:0;padding-left:18px;gap:8px">
      <li><b>Encrypted at rest.</b> AES-256-GCM with a key derived from your passphrase by PBKDF2-SHA256 (310,000 iterations, random salt). Only ciphertext is stored in this browser's localStorage.</li>
      <li><b>In memory only while unlocked.</b> Locking (manually or by idle timeout) discards the decrypted keys and clears them from the engine worker.</li>
      <li><b>Direct to the provider.</b> Calls go from your browser to the provider's API over HTTPS. This page has no backend and loads no analytics; its content-security policy only allows HTTPS (and localhost) connections.</li>
      <li><b>Never logged.</b> Keys are not written to the event log, the exports, run.json or the LLM cache; only fingerprints are used inside the engine.</li>
      <li><b>Honest limits.</b> Anyone with access to this unlocked browser tab can use the keys; browser extensions with page access can read them. Use keys with spending limits, and prefer session-only on shared machines.</li></ul>
      <div class="sep" style="margin:14px 0"></div><div class="small muted">Endpoints this page may contact</div><div class="row wrap" style="margin-top:6px">${Object.values(PROVIDERS).filter((p) => !p.needsUrl).map((p) => html`<${Badge} mono=${true}>${p.host}<//>`)}<${Badge} mono=${true}>cdn.jsdelivr.net (Python runtime)<//><${Badge} mono=${true}>pypi.org (pypdf)<//></div><//>
    ${adding && html`<${AddKeyDialog} onClose=${() => setAdding(false)} />`}</div>`;
}

function GuideView() {
  const gh = repoUrl();
  const docs = [["README.md", "Overview, quick start, headline numbers"], ["docs/ARCHITECTURE.md", "System architecture with diagrams"], ["docs/AGENTS.md", "Agent architecture and guardrails"], ["docs/ACCURACY.md", "Accuracy, precision, ablations, methodology"], ["docs/WEB_UI.md", "This interface: design, vault, deployment"], ["docs/DATA_AND_POLICY.md", "Inputs, outputs, policy engine, step contract"]];
  return html`<div class="page"><div><h1>Guide</h1><p class="muted small" style="margin-top:4px">How to use this interface, and where the documentation lives.</p></div>
    <div class="grid g2" style="align-items:start"><${Card} title="Quick start" icon="play"><ol class="col small" style="margin:0;padding-left:18px;gap:8px">
      <li>Wait for the engine badge (top bar) to turn <b>ready</b>. The Python runtime loads once and is cached.</li>
      <li>On <b>Run</b>, load a demo scenario - or upload the challenge <span class="mono">dataset/</span> folder (or a zip, or a URL).</li>
      <li>Choose <b>Offline</b> (deterministic, no keys) or <b>Hybrid</b> (adds the LLM layer; add keys in the Vault first).</li>
      <li>Press <b>Run audit</b> (<span class="kbd">Ctrl</span>+<span class="kbd">Enter</span>). Watch agents and the event log live.</li>
      <li>Explore <b>Results</b> case by case, check <b>Evaluation</b>, download <span class="mono">output.csv</span>, <span class="mono">trace.jsonl</span> and <span class="mono">review.md</span>.</li></ol><//>
      <${Card} title="What runs where" icon="cpu"><div class="col small"><p>The page runs the same Python package as the command line, compiled to WebAssembly (Pyodide) inside a Web Worker, so the interface stays responsive. Stopping a run restarts that worker.</p>
        <p>Datasets never leave your browser. In hybrid mode only request texts and screenshots you chose to analyse go to the provider you configured.</p><p>Full-dataset runs (518 cases, 94 evidence files) take roughly a minute in the browser; the demo scenarios take seconds.</p></div><//></div>
    <${Card} title="Documentation" icon="book-open" sub=${gh ? "Links open the repository on GitHub" : "Open these files in the repository"}><div class="grid g-auto" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr))">${docs.map(([f, d]) => html`<${gh ? "a" : "div"} class="card flat" style="padding:12px;display:block;color:inherit;text-decoration:none" href=${gh ? gh + "/blob/main/" + f : null} target="_blank" rel="noopener"><div class="mono small strong">${f}</div><div class="hint">${d}</div><//>`)}</div><//>
    <${Card} title="Keyboard & accessibility" icon="terminal"><div class="small col"><div><span class="kbd">Ctrl</span>+<span class="kbd">Enter</span> run the audit · <span class="kbd">Esc</span> close drawers and dialogs · <span class="kbd">Enter</span> open the focused table row.</div>
      <div>All controls are keyboard reachable, charts carry text alternatives, motion respects <i>prefers-reduced-motion</i>, and every colour state also has an icon or label.</div></div><//></div>`;
}
