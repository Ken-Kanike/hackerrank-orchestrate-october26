/* ========================================================================================
   Results, Case drawer, Evaluation, Monitor
   ======================================================================================== */
const PHASE_ICON = { FINDING: ["f", "FINDING", "scan-search"], REMEDIATION: ["r", "REMEDIATION", "workflow"], VERIFICATION: ["v", "VERIFICATION", "clipboard-check"] };
const INFO = new Set(["category_inferred", "retention_unknown"]);
const flagKind = (f) => (INFO.has(f) ? "" : /contradict|ghost|leak|disagree/.test(f) ? "err" : "warn");

function ExportMenu({ res }) {
  const f = res.files || {};
  return html`<div class="row wrap">
    <button class="btn outline sm" disabled=${!f["output.csv"]} onClick=${() => download("output.csv", f["output.csv"], "text/csv")}><${Icon} n="download" cls="sm" />output.csv</button>
    <button class="btn outline sm" disabled=${!f["trace.jsonl"]} onClick=${() => download("trace.jsonl", f["trace.jsonl"])}><${Icon} n="download" cls="sm" />trace.jsonl</button>
    <button class="btn outline sm" disabled=${!f["review.md"]} onClick=${() => download("review.md", f["review.md"])}><${Icon} n="download" cls="sm" />review.md</button>
    <button class="btn outline sm" onClick=${() => download("run.json", JSON.stringify(res, null, 1), "application/json")}><${Icon} n="download" cls="sm" />run.json</button></div>`;
}

function ResultsView() {
  const res = useStore((s) => s.result), selected = useStore((s) => s.selectedCase);
  const [q, setQ] = useState(""), [status, setStatus] = useState("ALL"), [flag, setFlag] = useState("ALL"), [bad, setBad] = useState(false), [page, setPage] = useState(0);
  const PAGE = 25;
  if (!res) return html`<div class="page"><h1>Results</h1><${Card}><${Empty} icon="list" title="No results yet">Run an audit from the Run page. Every case, its plan, trace and evidence will be explorable here.<//><//></div>`;
  const hasGold = !!res.metrics;
  const allFlags = [...new Set(res.cases.flatMap((c) => c.trace?.flags || []))].filter((f) => !INFO.has(f)).sort();
  const rows = res.cases.filter((c) => (status === "ALL" || c.status === status)
    && (flag === "ALL" || (c.trace?.flags || []).includes(flag) || (flag === "VALIDATOR" && c.validator.length))
    && (!bad || (c.gold && !c.gold.exact))
    && (!q || (c.case_id + " " + c.request.email + " " + c.steps.map((s) => s.resource_id).join(" ")).toLowerCase().includes(q.toLowerCase())));
  const pages = Math.max(1, Math.ceil(rows.length / PAGE)), pg = Math.min(page, pages - 1);
  const counts = { ALL: res.cases.length, COMPLETE: 0, INCOMPLETE: 0, NOT_APPLICABLE: 0 }; res.cases.forEach((c) => counts[c.status]++);
  const open = (c) => Store.set({ selectedCase: c.case_id });
  return html`<div class="page">
    <div class="row between wrap"><div><h1>Results</h1><p class="muted small" style="margin-top:4px">${res.meta.dataset} · ${res.summary.mode} · ${fmt.num(res.cases.length)} cases · run <span class="mono">${res.summary.run_id}</span></p></div><${ExportMenu} res=${res} /></div>
    <div class="row wrap" style="gap:10px">
      <div style="position:relative;flex:1 1 220px;min-width:180px"><input class="input" style="padding-left:34px" placeholder="Search case, email or resource id…" aria-label="Search cases" value=${q} onInput=${(e) => { setQ(e.target.value); setPage(0); }} /><span style="position:absolute;left:11px;top:10px;color:var(--faint)"><${Icon} n="search" cls="sm" /></span></div>
      <${Seg} label="Status" value=${status} onChange=${(v) => { setStatus(v); setPage(0); }} options=${[["ALL", "All " + counts.ALL], ["INCOMPLETE", "Incomplete " + counts.INCOMPLETE], ["COMPLETE", "Complete " + counts.COMPLETE], ["NOT_APPLICABLE", "N/A " + counts.NOT_APPLICABLE]]} />
      <select class="select" style="width:auto" aria-label="Flag filter" value=${flag} onChange=${(e) => { setFlag(e.target.value); setPage(0); }}><option value="ALL">Any flag</option><option value="VALIDATOR">Validator errors</option>${allFlags.map((f) => html`<option value=${f}>${f}</option>`)}</select>
      ${hasGold && html`<label class="row small" style="gap:8px"><button class="switch" role="switch" aria-checked=${bad ? "true" : "false"} aria-label="Only gold mismatches" onClick=${() => { setBad(!bad); setPage(0); }}></button>Only gold mismatches</label>`}</div>
    <div class="table-wrap"><table class="t"><thead><tr><th>Case</th><th>Status</th><th class="num">Steps</th><th>Resources</th><th>Flags</th>${hasGold && html`<th>Gold</th>`}<th class="hide-sm">Intent</th></tr></thead>
      <tbody>${rows.slice(pg * PAGE, pg * PAGE + PAGE).map((c) => { const fl = (c.trace?.flags || []).filter((f) => !INFO.has(f)); const rs = [...new Set(c.steps.map((s) => s.resource_id))];
        return html`<tr class=${cls("click", selected === c.case_id && "sel")} tabindex="0" onClick=${() => open(c)} onKeyDown=${(e) => e.key === "Enter" && open(c)}>
          <td class="mono strong">${c.case_id}</td><td><${StatusBadge} status=${c.status} /></td><td class="num">${c.steps.length}</td>
          <td class="small muted" style="max-width:260px"><span class="trunc" style="display:block">${rs.slice(0, 3).join(", ")}${rs.length > 3 ? " +" + (rs.length - 3) : ""}</span></td>
          <td><div class="row wrap gap-sm">${fl.slice(0, 2).map((f) => html`<${Badge} kind=${flagKind(f)}>${f}<//>`)}${fl.length > 2 && html`<${Badge}>+${fl.length - 2}<//>`}${c.validator.length > 0 && html`<${Badge} kind="err">validator<//>`}</div></td>
          ${hasGold && html`<td>${c.gold ? (c.gold.exact ? html`<${Badge} kind="ok"><${Icon} n="check" cls="sm" />exact<//>` : c.gold.status_ok ? html`<${Badge} kind="warn">${c.gold.missing.length} missing · ${c.gold.extra.length} extra<//>` : html`<${Badge} kind="err">status<//>`) : html`<span class="faint">-</span>`}</td>`}
          <td class="hide-sm"><${Badge} mono=${true}>${c.intent.final}${c.intent.llm != null ? " · llm" : ""}<//></td></tr>`; })}
        ${rows.length === 0 && html`<tr><td colspan="7"><${Empty} title="No cases match">Adjust the filters.<//></td></tr>`}</tbody></table></div>
    <div class="pager small muted"><span>${rows.length} cases</span><button class="btn outline sm icon-only" aria-label="Previous page" disabled=${pg === 0} onClick=${() => setPage(pg - 1)}><${Icon} n="chevron-right" cls="sm flip" /></button><span>${pg + 1} / ${pages}</span><button class="btn outline sm icon-only" aria-label="Next page" disabled=${pg >= pages - 1} onClick=${() => setPage(pg + 1)}><${Icon} n="chevron-right" cls="sm" /></button></div>
    ${selected && html`<${CaseDrawer} id=${selected} />`}
  </div>`;
}

function CaseDrawer({ id }) {
  const res = useStore((s) => s.result);
  const [tab, setTab] = useState("plan");
  const c = res.cases.find((x) => x.case_id === id);
  if (!c) return null;
  const close = () => Store.set({ selectedCase: null });
  const t = c.trace, r = c.request;
  const groups = ["FINDING", "REMEDIATION", "VERIFICATION"].map((p) => [p, c.steps.filter((s) => s.phase === p)]).filter(([, a]) => a.length);
  return html`<${Drawer} title=${c.case_id} sub=${r.email} onClose=${close} actions=${html`<${StatusBadge} status=${c.status} />`}>
    ${c.validator.length > 0 && html`<${Banner} kind="err"><div class="strong small">Validator flagged this row</div>${c.validator.map((e) => html`<div class="small mono">${e}</div>`)}<div class="small muted" style="margin-top:4px">Such rows are reported, never silently emitted as valid.</div><//>`}
    <${Tabs} value=${tab} onChange=${setTab} options=${[["plan", "Plan", "list", c.steps.length], ["resources", "Resources & rules", "layers", t?.resources.length], ["request", "Request & intent", "file-text"], c.gold && ["gold", "Gold comparison", "scale"], ["json", "JSON", "terminal"]].filter(Boolean)} />
    ${tab === "plan" && (c.steps.length === 0
      ? html`<${Empty} icon="circle-dashed" title=${c.status === "NOT_APPLICABLE" ? "Not applicable" : "No steps"}>${c.status === "NOT_APPLICABLE" ? "The request text does not authorize deletion, so the contract requires an empty plan." : "Nothing to report."}<//>`
      : html`<div class="col">${c.status === "COMPLETE" && html`<${Banner} kind="ok"><div class="small">Complete: verification steps only, each citing the evidence that proves the compliant state at audit_at.</div><//>`}
        ${groups.map(([p, steps]) => html`<div><div class="row" style="margin-bottom:10px"><${Icon} n=${PHASE_ICON[p][2]} cls="sm" /><span class="small strong">${p}</span><span class="hint">${p === "FINDING" ? "what is wrong, cited" : p === "REMEDIATION" ? "ordered future work, no evidence" : "checks that must pass"}</span></div>
          ${steps.map((s) => html`<div class="step"><div class=${cls("n", PHASE_ICON[p][0])}>${s.step_no}</div><div class="col gap-sm" style="gap:5px"><div class="row wrap" style="gap:8px"><span class="mono small strong">${s.operation}</span><${Badge} mono=${true}>${s.state}<//><${EvChip} id=${s.evidence_id} /></div>
            <div class="small muted"><span class="mono">${s.resource_id}</span> · ${s.system_id}</div></div></div>`)}</div>`)}</div>`)}
    ${tab === "resources" && (t ? html`<div class="col"><dl class="kv"><dt>Resolved user</dt><dd class="mono">${t.user_id}</dd><dt>Flags</dt><dd><div class="row wrap gap-sm">${t.flags.length ? t.flags.map((f) => html`<${Badge} kind=${flagKind(f)}>${f}<//>`) : html`<span class="faint">none</span>`}</div></dd></dl>
      <div class="table-wrap"><table class="t"><thead><tr><th>Resource</th><th>State</th><th>Link</th><th>Rule</th><th>Evidence</th></tr></thead><tbody>${t.resources.map((x) => html`<tr>
        <td><div class="mono strong small">${x.resource_id}</div><div class="hint">${x.system_id}</div></td><td><${Badge} kind=${x.violation ? "warn" : "ok"}>${x.state}<//></td>
        <td><${Badge} mono=${true} tip=${x.link === "identity" ? "an identifier on the record matches the subject" : x.link === "workflow-run" ? "reconstructed from the deletion-worker activity stream" : "recreated by a connector/restore job before audit_at"}>${x.link}<//></td>
        <td class="small"><div>${x.category}</div><div class="hint">${x.rule_id} → ${x.action}${x.violation ? " · violation" : ""}</div>${x.flags.length > 0 && html`<div class="row wrap gap-sm" style="margin-top:4px">${x.flags.map((f) => html`<${Badge} kind=${flagKind(f)}>${f}<//>`)}</div>`}</td><td><${EvChip} id=${x.evidence_id} /></td></tr>`)}</tbody></table></div>
      ${t.ghost_hits && html`<${Banner} kind="warn"><div class="strong small">Ghost-sweep hits</div>${t.ghost_hits.map((g) => html`<div class="small mono">${g.rid} · ${g.fid} · ${g.loc}</div>`)}<//>`}
      ${c.investigator && html`<${Banner} kind="info" icon="bot"><div class="strong small">Investigator (advisory)</div><div class="small">Chose <span class="mono">${c.investigator.choose}</span> in ${c.investigator.turns} turn(s) - ${c.investigator.agrees ? "agrees with" : "differs from"} the engine. ${c.investigator.reason}</div><//>`}</div>`
      : html`<${Empty} title="No trace">Not applicable cases have no resource trace.<//>`)}
    ${tab === "request" && html`<div class="col"><dl class="kv"><dt>Email</dt><dd class="mono">${r.email}</dd><dt>Requested</dt><dd class="mono">${r.requested_at}</dd><dt>Reported</dt><dd><span class="mono">${r.reported_at}</span> <${Badge}>${r.reported_status}<//></dd><dt>Audit at</dt><dd class="mono">${r.audit_at}</dd></dl>
      <div class="card flat" style="padding:12px"><div class="hint" style="margin-bottom:4px">Request text (treated as data)</div><div>${r.request_text}</div></div>
      <dl class="kv"><dt>Rule verdict</dt><dd><${Badge} mono=${true}>${c.intent.rule}<//> <span class="muted small">${c.intent.strength}</span></dd><dt>Rights detected</dt><dd>${c.intent.rights.length ? c.intent.rights.map((x) => html`<${Badge}>${x}<//> `) : html`<span class="faint">none besides erasure</span>`}</dd>
        <dt>LLM</dt><dd>${c.intent.llm == null ? html`<span class="faint">not consulted</span>` : html`<${Badge} kind=${c.intent.llm ? "warn" : ""}>${c.intent.llm ? "deletion" : "not deletion"}<//> <span class="muted small">confidence ${c.intent.llm_conf}</span>`}</dd><dt>Final</dt><dd><${Badge} kind="primary" mono=${true}>${c.intent.final}<//>${c.intent.disagree && html` <${Badge} kind="warn">rule/LLM disagree<//>`}</dd></dl></div>`}
    ${tab === "gold" && c.gold && html`<div class="col"><dl class="kv"><dt>Predicted</dt><dd><${StatusBadge} status=${c.status} /></dd><dt>Gold</dt><dd><${StatusBadge} status=${c.gold.gold_status} /></dd></dl>
      ${c.gold.exact ? html`<${Banner} kind="ok"><div class="small">Exact match with the gold steps (order included).</div><//>` : html`<div class="col">
        ${c.gold.missing.length > 0 && html`<${Banner} kind="warn"><div class="strong small">Missing (in gold, not predicted)</div>${c.gold.missing.map((m) => html`<div class="small mono">${m[0]} · ${m[3]} · ${m[2]} ${m[4] ? "· " + m[4] : ""}</div>`)}<//>`}
        ${c.gold.extra.length > 0 && html`<${Banner} kind="err"><div class="strong small">Extra (predicted, not in gold)</div>${c.gold.extra.map((m) => html`<div class="small mono">${m[0]} · ${m[3]} · ${m[2]} ${m[4] ? "· " + m[4] : ""}</div>`)}<//>`}
        ${c.gold.evidence_diff.length > 0 && html`<${Banner} kind="info"><div class="strong small">Different evidence id</div>${c.gold.evidence_diff.map((m) => html`<div class="small mono">${m[2]} · ${m[3]}: ${m[4]} vs gold ${m[5]}</div>`)}<//>`}
        ${c.gold.missing.length + c.gold.extra.length + c.gold.evidence_diff.length === 0 && html`<${Banner} kind="info"><div class="small">Same steps, different order or numbering.</div><//>`}</div>`}</div>`}
    ${tab === "json" && html`<div class="col"><div class="row"><button class="btn outline sm" onClick=${async () => toast((await copyText(JSON.stringify(c, null, 1))) ? "Copied" : "Copy failed", "info")}><${Icon} n="copy" cls="sm" />Copy</button></div><pre class="code">${JSON.stringify({ ...c, gold: undefined }, null, 1)}</pre></div>`}
  <//>`;
}

/* ---------------------------------------------------------------- Evaluation */
function MetricsPanel({ res }) {
  const m = res.metrics;
  if (!m) return html`<${Card} title="Accuracy" icon="gauge"><${Empty} icon="scale" title="No gold file for this run">Load a dataset that ships <span class="mono">sample_output.csv</span> or <span class="mono">expected_output.csv</span>, or pick one under Run → Score against. Predictions are then scored per case and per field.<//><//>`;
  const labels = ["COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"];
  const mat = labels.map(() => labels.map(() => 0));
  res.cases.filter((c) => c.gold).forEach((c) => { const i = labels.indexOf(c.gold.gold_status), j = labels.indexOf(c.status); if (i >= 0 && j >= 0) mat[i][j]++; });
  const bad = res.cases.filter((c) => c.gold && !c.gold.exact);
  return html`<div class="col" style="gap:20px">
    <div class="grid g4 keep2"><${Stat} k="Status accuracy" v=${fmt.pct(m.status_acc)} d=${`${m.status}/${m.n} cases`} icon="circle-check" tip="Share of cases whose deletion_status equals the gold status" />
      <${Stat} k="Step precision" v=${fmt.pct(m.precision)} d="predicted steps that are right" icon="scan-search" tip="Steps matched on (phase, system, resource, operation) / predicted steps" />
      <${Stat} k="Step recall" v=${fmt.pct(m.recall)} d="gold steps recovered" icon="search" tip="Matched steps / gold steps" />
      <${Stat} k="Step F1" v=${fmt.pct(m.f1)} d=${`exact sequence ${m.exact}/${m.n}`} icon="gauge" /></div>
    <div class="grid g2" style="align-items:start">
      <${Card} title="Field accuracy" sub="Steps aligned by (resource, phase)" icon="sliders-horizontal"><${HBars} rows=${[["system_id", "system_id"], ["operation", "operation"], ["state", "state"], ["evidence_id", "evidence_id"]].map(([k, l], i) => ({ label: l, value: m.field_acc[k], color: SERIES[i] }))} max=${1} fmtv=${(v) => fmt.pct(v)} />
        <div class="sep" style="margin:14px 0"></div><${HBars} rows=${[{ label: "Position accuracy (step_no)", value: m.position_acc, color: SERIES[4] }, { label: "Kendall tau (relative order)", value: m.kendall_tau, color: SERIES[5] }, { label: "LCS ratio", value: m.lcs_ratio, color: SERIES[6] }]} max=${1} fmtv=${(v) => fmt.pct(v)} /><//>
      <${Card} title="Status confusion matrix" sub="Rows: gold · columns: predicted" icon="layers"><${Heat} rows=${labels} cols=${labels} matrix=${mat} label="status confusion matrix" />
        <div class="hint" style="margin-top:10px">Unreachable ceiling: ${m.unreach} gold step(s) name resources that appear nowhere in participant-visible data.</div><//></div>
    <${Card} title=${`Cases that differ from gold (${bad.length})`} icon="triangle-alert">${bad.length === 0 ? html`<${Banner} kind="ok"><div class="small">Every scored case matches exactly.</div><//>` :
      html`<div class="table-wrap"><table class="t"><thead><tr><th>Case</th><th>Status</th><th class="num">Missing</th><th class="num">Extra</th></tr></thead><tbody>${bad.map((c) => html`<tr class="click" onClick=${() => Store.set({ view: "results", selectedCase: c.case_id })}><td class="mono strong">${c.case_id}</td>
        <td>${c.gold.status_ok ? html`<${Badge} kind="ok">ok<//>` : html`<${Badge} kind="err">${c.status} vs ${c.gold.gold_status}<//>`}</td><td class="num">${c.gold.missing.length}</td><td class="num">${c.gold.extra.length}</td></tr>`)}</tbody></table></div>`}<//></div>`;
}

function SuitePanel() {
  const suite = useStore((s) => s.tools.suite), busy = useStore((s) => s.tools.busy), ready = useStore((s) => s.engine.status === "ready");
  return html`<${Card} title="Demo suite" sub="8 hand-derived end-to-end scenarios, each scored against its own expected_output.csv" icon="flask-conical" actions=${html`<button class="btn sm" disabled=${!ready || !!busy} onClick=${Actions.runSuite}>${busy === "suite" ? html`<${Icon} n="loader-circle" cls="sm spin" />` : html`<${Icon} n="play" cls="sm" />`}Run suite</button>`}>
    ${!suite ? html`<div class="hint">Run the suite to verify the engine against the scenarios (injection, replica drift, late export, lineage, retention, historical hash, tombstone…).</div>`
      : html`<div class="table-wrap"><table class="t"><thead><tr><th>Scenario</th><th class="num">Cases</th><th class="num">Status</th><th class="num">Precision</th><th class="num">Recall</th><th>Result</th></tr></thead><tbody>${suite.datasets.map((d) => html`<tr><td><div class="mono small strong">${d.name}</div><div class="hint">${DEMO_TEXT[d.name] || ""}</div></td><td class="num">${d.cases}</td>
        <td class="num">${fmt.pct(d.metrics.status_acc, 0)}</td><td class="num">${fmt.pct(d.metrics.precision, 0)}</td><td class="num">${fmt.pct(d.metrics.recall, 0)}</td><td>${d.exact && !d.validator_flags ? html`<${Badge} kind="ok"><${Icon} n="circle-check" cls="sm" />exact match<//>` : html`<${Badge} kind="err"><${Icon} n="circle-x" cls="sm" />differs<//>`}</td></tr>`)}</tbody></table></div>`}<//>`;
}
function AblationPanel() {
  const ab = useStore((s) => s.tools.ablation), busy = useStore((s) => s.tools.busy), ds = useStore((s) => s.datasets[s.activeDataset]), ready = useStore((s) => s.engine.status === "ready");
  const base = ab?.results[0];
  return html`<${Card} title="Ablation" sub="Switch one design element off at a time and measure the effect" icon="git-compare" actions=${html`<button class="btn sm" disabled=${!ready || !ds?.info?.ok || !!busy} onClick=${Actions.runAblation}>${busy === "ablation" ? html`<${Icon} n="loader-circle" cls="sm spin" />` : html`<${Icon} n="play" cls="sm" />`}Run ablation</button>`}>
    ${!ab ? html`<div class="hint">Runs the active dataset ${ABLATIONS.length} times offline (${ds ? ds.name : "no dataset selected"}). On the full 518-case dataset this takes several minutes in the browser; use the case limit on the Run page for a quick look.</div>`
      : html`<div class="col"><div class="hint">${ab.dataset} · outputs compared over ${ab.results[0].cases} cases${ab.results[0].metrics ? " · metrics scored on the gold file / public samples" : " · no gold file: only output changes are shown"}</div><div class="table-wrap"><table class="t"><thead><tr><th>Configuration</th>${ab.results[0].metrics && html`<th class="num">Status</th><th class="num">Precision</th><th class="num">Recall</th><th class="num">Exact</th>`}<th class="num">Outputs changed</th><th class="num">Ambiguous</th></tr></thead>
        <tbody>${ab.results.map((r, i) => html`<tr><td>${r.name}${i === 0 && html` <${Badge}>baseline<//>`}</td>${ab.results[0].metrics && html`<td class="num">${fmt.pct(r.metrics?.status_acc)}</td><td class="num">${fmt.pct(r.metrics?.precision)}</td><td class="num">${fmt.pct(r.metrics?.recall)}</td><td class="num">${r.metrics ? r.metrics.exact + "/" + r.metrics.n : "-"}</td>`}
          <td class="num"><span style=${r.changed ? "color:var(--warn);font-weight:600" : ""}>${r.changed}</span></td><td class="num">${r.summary.ambiguous}</td></tr>`)}</tbody></table></div></div>`}<//>`;
}
function RecoveryPanel() {
  const rc = useStore((s) => s.tools.recovery), busy = useStore((s) => s.tools.busy), ds = useStore((s) => s.datasets[s.activeDataset]), ready = useStore((s) => s.engine.status === "ready");
  const [folds, setFolds] = useState(4), [reps, setReps] = useState(1);
  return html`<${Card} title="Link-recovery test" sub="Label-free check of the activity-based account linker" icon="network" actions=${html`<button class="btn sm" disabled=${!ready || !ds?.info?.ok || !!busy} onClick=${() => Actions.runRecovery(folds, reps)}>${busy === "recovery" ? html`<${Icon} n="loader-circle" cls="sm spin" />` : html`<${Icon} n="play" cls="sm" />`}Run test</button>`}>
    <div class="col"><div class="hint">For cases whose account is proven by identity, the proof is hidden and the linker must re-derive it from workflow activity alone. Needs a dataset with identity-proven accounts (the full dataset).</div>
      <div class="row"><label class="field" style="width:110px">Folds<input class="input" type="number" min="2" max="8" value=${folds} onInput=${(e) => setFolds(+e.target.value || 4)} /></label><label class="field" style="width:110px">Repeats<input class="input" type="number" min="1" max="3" value=${reps} onInput=${(e) => setReps(+e.target.value || 1)} /></label></div>
      ${rc && html`<div class="grid g3"><${Stat} k="Proven accounts" v=${fmt.num(rc.proven_accounts)} /><${Stat} k="Recovery accuracy" v=${fmt.pct(rc.accuracy)} d=${rc.folds + " folds · " + fmt.ms(rc.ms)} color=${rc.accuracy > 0.95 ? "var(--ok)" : "var(--warn)"} /><${Stat} k="Residual ambiguity" v=${fmt.pct(rc.ambiguity)} /></div>`}</div><//>`;
}
function EvaluationView() {
  const res = useStore((s) => s.result);
  return html`<div class="page"><div><h1>Evaluation</h1><p class="muted small" style="margin-top:4px">Accuracy against a gold file, plus the self-checks that do not need one.</p></div>
    ${res ? html`<${MetricsPanel} res=${res} />` : html`<${Card} title="Accuracy" icon="gauge"><${Empty} icon="scale" title="Run an audit first">Scored metrics appear here after a run on a dataset with a gold file.<//><//>`}
    <${SuitePanel} /><${AblationPanel} /><${RecoveryPanel} /></div>`;
}

/* ---------------------------------------------------------------- Monitor */
function MonitorView() {
  const run = useStore((s) => s.run), res = useStore((s) => s.result), eng = useStore((s) => s.engine), prov = useStore((s) => s.vault.providers);
  const [lv, setLv] = useState("all"), [q, setQ] = useState("");
  const calls = run.llm, fresh = calls.filter((c) => !c.cached), cached = calls.filter((c) => c.cached);
  const tin = calls.reduce((a, c) => a + (c.in || 0), 0), tout = calls.reduce((a, c) => a + (c.out || 0), 0);
  const lat = fresh.map((c) => c.ms).filter(Boolean), avg = lat.length ? lat.reduce((a, b) => a + b, 0) / lat.length : 0;
  const cost = res?.llm.by_model.reduce((a, m) => a + m.cost_if_uncached, 0) || 0;
  const byTask = {}; calls.forEach((c) => { const t = (byTask[c.task] = byTask[c.task] || { n: 0, tok: 0 }); t.n++; t.tok += (c.in || 0) + (c.out || 0); });
  const flags = Object.entries(res?.summary.flag_counts || {}).filter(([k]) => !INFO.has(k)).sort((a, b) => b[1] - a[1]);
  const logs = run.logs.filter((l) => (lv === "all" || l.level === lv) && (!q || l.msg.toLowerCase().includes(q.toLowerCase())));
  return html`<div class="page"><div class="row between wrap"><div><h1>Monitor</h1><p class="muted small" style="margin-top:4px">Live engine status, stage timings, model calls and the event log.</p></div>
      <div class="row"><button class="btn outline sm" onClick=${() => download("events.log", run.logs.map((l) => `${new Date(l.t * 1000).toISOString()} ${l.level.padEnd(5)} ${l.msg}`).join("\n"))}><${Icon} n="download" cls="sm" />Download log</button></div></div>
    <div class="grid g4 keep2">
      <${Stat} k="Engine" v=${eng.status === "ready" ? "Ready" : eng.status === "booting" ? "Starting" : eng.status === "error" ? "Error" : "Idle"} d=${eng.info ? "Python " + eng.info.python + (eng.info.pdf ? " · pypdf" : " · no PDF") : ""} icon="cpu" color=${eng.status === "ready" ? "var(--ok)" : eng.status === "error" ? "var(--err)" : undefined} />
      <${Stat} k="Run" v=${{ idle: "Idle", running: "Running", done: "Done", error: "Failed", cancelled: "Cancelled" }[run.status]} d=${run.finishedAt && run.startedAt ? fmt.ms((run.finishedAt - run.startedAt) * 1000) : run.label} icon="activity" />
      <${Stat} k="Model calls" v=${calls.length} d=${`${fresh.length} fresh · ${cached.length} cached`} icon="brain" />
      <${Stat} k="Tokens in / out" v=${fmt.num(tin) + " / " + fmt.num(tout)} d=${`avg latency ${fmt.ms(avg)} · est. ${fmt.usd(cost)} if uncached`} icon="coins" /></div>
    <div class="grid g2" style="align-items:start">
      <${Card} title="Stage timeline" sub="When each agent ran in this run" icon="timer"><${Waterfall} stages=${run.stages} order=${STAGES} /><//>
      <${Card} title="Model activity" icon="brain" sub=${prov.length ? "Providers: " + prov.join(" → ") : "No providers loaded (offline)"}>
        ${calls.length === 0 ? html`<div class="hint">No model calls in this run.</div>` : html`<div class="col"><${HBars} rows=${Object.entries(byTask).map(([k, v], i) => ({ label: k + " · " + v.n + " calls", value: v.tok, color: SERIES[i % 8] }))} fmtv=${(v) => fmt.num(v) + " tok"} />
          <div class="row" style="gap:14px"><span class="small muted">Latency</span><${Spark} values=${lat} w=${200} /></div></div>`}<//></div>
    ${calls.length > 0 && html`<${Card} title="Model call ledger" icon="list"><div class="table-wrap" style="max-height:300px"><table class="t"><thead><tr><th>Time</th><th>Task</th><th>Provider / model</th><th class="num">In</th><th class="num">Out</th><th class="num">Latency</th><th>Result</th></tr></thead><tbody>${calls.slice(-200).reverse().map((c) => html`<tr>
      <td class="mono small">${fmt.time(c.t)}</td><td class="mono small">${c.task}</td><td class="small">${c.provider || "-"} <span class="muted">${c.model || ""}</span></td><td class="num">${c.in ?? 0}</td><td class="num">${c.out ?? 0}</td><td class="num">${c.cached ? "-" : fmt.ms(c.ms)}</td>
      <td>${c.cached ? html`<${Badge}>cache<//>` : c.ok ? html`<${Badge} kind="ok">ok<//>` : html`<${Badge} kind="err">failed<//>`}</td></tr>`)}</tbody></table></div><//>`}
    ${flags.length > 0 && html`<${Card} title="Review flags" sub="Cases a human may want to look at (informational flags excluded)" icon="triangle-alert"><${HBars} rows=${flags.map(([k, v], i) => ({ label: k, value: v, color: SERIES[i % 8] }))} /><//>`}
    <${Card} title="Event log" icon="terminal" actions=${html`<div class="row"><select class="select" style="width:auto;height:30px" aria-label="Level" value=${lv} onChange=${(e) => setLv(e.target.value)}><option value="all">all levels</option><option value="info">info</option><option value="stage">stage</option><option value="llm">llm</option><option value="warn">warn</option><option value="error">error</option></select><input class="input" style="height:30px;width:150px" placeholder="filter…" aria-label="Filter log" value=${q} onInput=${(e) => setQ(e.target.value)} /></div>`}>
      <${LogView} logs=${logs} max=400 height=340 /><//></div>`;
}
