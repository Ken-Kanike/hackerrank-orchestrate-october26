/* ========================================================================================
   Inputs explorer: what the audit reads (requests, evidence manifest + parse stats, policy rules, activity stream)
   ======================================================================================== */
const RULE_KIND = { DELETE: "err", REDACT: "info", ANONYMIZE: "info", RETAIN: "ok" };

function usePreview(id, ok) {
  const [p, setP] = useState(null), [err, setErr] = useState(null);
  useEffect(() => {
    let live = true; setP(null); setErr(null);
    if (!id || !ok) return;
    (async () => { try { const v = await Engine.callJson("dataset_preview", "/app/data/" + id); if (live) setP(v); } catch (e) { if (live) setErr(e.message.slice(-160)); } })();
    return () => { live = false; };
  }, [id, ok]);
  return [p, err];
}

function InputsView() {
  const ds = useStore((s) => s.datasets[s.activeDataset]), ready = useStore((s) => s.engine.status === "ready"), res = useStore((s) => s.result), busy = useStore((s) => s.run.status === "running" || !!s.tools.busy);
  const [tab, setTab] = useState("requests"), [q, setQ] = useState(""), [page, setPage] = useState(0), [open, setOpen] = useState(null), [src, setSrc] = useState("deletion_requests.csv");
  const [prev, err] = usePreview(ready && !busy ? ds?.id : null, ds?.info?.ok);
  const PAGE = 15;
  if (!ds || !ds.info?.ok) return html`<div class="page"><h1>Inputs</h1><${Card}><${Empty} icon="database" title="No dataset loaded">Load a dataset on the Run page to explore its requests, evidence, policy rules and activity stream.<//><//></div>`;
  if (err) return html`<div class="page"><h1>Inputs</h1><${Banner} kind="err"><div class="small">${err}</div><//></div>`;
  if (!prev) return html`<div class="page"><h1>Inputs</h1>${busy ? html`<${Banner} kind="info"><div class="small">The engine is busy with a run; the explorer loads when it finishes.</div><//>` : html`<div class="grid g4"><div class="skeleton" style="height:90px"></div><div class="skeleton" style="height:90px"></div><div class="skeleton" style="height:90px"></div><div class="skeleton" style="height:90px"></div></div>`}</div>`;
  const reqs = (src === "deletion_requests.csv" ? prev.requests : prev.sample_requests).filter((r) => !q || (r.case_id + " " + r.email + " " + r.request_text).toLowerCase().includes(q.toLowerCase()));
  const pages = Math.max(1, Math.ceil(reqs.length / PAGE)), pg = Math.min(page, pages - 1);
  const evMap = new Map((res?.evidence || []).map((e) => [e.file_id, e]));
  const ext = {}; prev.manifest.forEach((m) => { ext[m.ext] = (ext[m.ext] || 0) + 1; });
  const rs = prev.reported_status.map(([k, v], i) => ({ label: k, value: v, color: ["var(--ok)", "var(--warn)", "var(--s2)"][i % 3] }));
  return html`<div class="page"><div><h1>Inputs</h1><p class="muted small" style="margin-top:4px">${ds.name} - everything the audit reads. Claims (reported statuses, activity results) are shown as claims: they are not proof.</p></div>
    <div class="grid g4 keep2"><${Stat} k="Deletion requests" v=${fmt.num(prev.requests.length)} d=${prev.sample_requests.length ? prev.sample_requests.length + " public samples" : "evaluation file"} icon="list" />
      <${Stat} k="Evidence files" v=${prev.manifest.length} d=${Object.entries(ext).map(([k, v]) => v + " ." + k).join(" · ")} icon="database" />
      <${Stat} k="Identities / audit log" v=${fmt.num(prev.identities)} d=${fmt.num(prev.audit_log) + " historical identifier changes"} icon="fingerprint" />
      <${Stat} k="Activity events" v=${fmt.num(prev.activity.total)} d="global stream, includes decoys" icon="activity" /></div>
    <${Card} title="Reported status (the workflow's claim)" icon="clipboard-list" sub="The audit never accepts these as proof"><${StackBar} parts=${rs} height=12 /><div style="margin-top:10px"><${Legend} items=${rs} /></div><//>
    <${Tabs} value=${tab} onChange=${(v) => { setTab(v); setPage(0); }} options=${[["requests", "Requests", "list", reqs.length], ["evidence", "Evidence files", "database", prev.manifest.length], ["rules", "Policy rules", "scale", prev.rules.length], ["activity", "Activity stream", "activity", prev.activity.total]]} />
    ${tab === "requests" && html`<div class="col"><div class="row wrap">${prev.sample_requests.length > 0 && html`<${Seg} label="Source" value=${src} onChange=${(v) => { setSrc(v); setPage(0); }} options=${[["deletion_requests.csv", "Evaluation"], ["sample_deletion_requests.csv", "Samples"]]} />`}
        <div style="position:relative;flex:1 1 220px"><input class="input" style="padding-left:34px" placeholder="Search id, email or text…" aria-label="Search requests" value=${q} onInput=${(e) => { setQ(e.target.value); setPage(0); }} /><span style="position:absolute;left:11px;top:10px;color:var(--faint)"><${Icon} n="search" cls="sm" /></span></div></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>Case</th><th>Email</th><th>Reported</th><th class="hide-sm">Requested</th><th>Request text</th></tr></thead><tbody>${reqs.slice(pg * PAGE, pg * PAGE + PAGE).map((r) => html`<tr class="click" onClick=${() => setOpen(open === r.case_id ? null : r.case_id)}>
        <td class="mono strong">${r.case_id}</td><td class="mono small">${r.email}</td><td><${Badge}>${r.reported_status.replace("_", " ").toLowerCase()}<//></td><td class="mono small hide-sm">${r.requested_at.slice(0, 10)}</td>
        <td class="small" style="max-width:420px"><span style=${open === r.case_id ? "" : "display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden"}>${r.request_text}</span></td></tr>`)}</tbody></table></div>
      <div class="pager small muted"><span>${reqs.length} requests</span><button class="btn outline sm icon-only" aria-label="Previous page" disabled=${pg === 0} onClick=${() => setPage(pg - 1)}><${Icon} n="chevron-right" cls="sm flip" /></button><span>${pg + 1} / ${pages}</span><button class="btn outline sm icon-only" aria-label="Next page" disabled=${pg >= pages - 1} onClick=${() => setPage(pg + 1)}><${Icon} n="chevron-right" cls="sm" /></button></div></div>`}
    ${tab === "evidence" && html`<div class="col">${!res && html`<div class="hint">Observation counts appear after a run (they show how many records each parser extracted from the file).</div>`}
      <div class="table-wrap"><table class="t"><thead><tr><th>File</th><th>Path</th><th>Captured</th><th class="num">Size</th><th class="num">Observations</th><th class="num">Resources</th><th class="hide-sm">Main kinds</th></tr></thead><tbody>${prev.manifest.map((m) => { const e = evMap.get(m.file_id); return html`<tr>
        <td class="mono strong small">${m.file_id}</td><td class="mono small" style="max-width:300px"><span class="trunc" style="display:block" data-tip=${m.file_path}>${m.file_path.replace("evidence/", "")}</span></td><td class="mono small">${m.captured_at.slice(0, 16).replace("T", " ")}</td><td class="num small">${m.size != null ? fmt.bytes(m.size) : html`<${Badge} kind="err">missing<//>`}</td>
        <td class="num">${e ? e.observations : html`<span class="faint">-</span>`}</td><td class="num">${e ? e.resources : html`<span class="faint">-</span>`}</td><td class="hide-sm small muted">${e ? Object.entries(e.kinds).map(([k, v]) => k + " ×" + v).join(", ") : ""}</td></tr>`; })}</tbody></table></div></div>`}
    ${tab === "rules" && html`<div class="col"><${Banner} kind="info"><div class="small">The policy is data: edit <span class="mono">deletion_rules.csv</span> and the plan changes. Retention and hold rules are checked against <span class="mono">retention_until</span> / <span class="mono">retained_until</span> at <span class="mono">audit_at</span>.</div><//>
      <div class="table-wrap"><table class="t"><thead><tr><th>Rule</th><th>Data category</th><th>Condition</th><th>Required action</th></tr></thead><tbody>${prev.rules.map((r) => html`<tr><td class="mono small">${r.rule_id}</td><td class="mono strong small">${r.data_category}</td><td class="small muted">${r.condition}</td><td><${Badge} kind=${RULE_KIND[r.required_action] || ""}>${r.required_action}<//></td></tr>`)}</tbody></table></div></div>`}
    ${tab === "activity" && html`<div class="grid g2" style="align-items:start"><${Card} title="Events by type" icon="activity"><${HBars} rows=${prev.activity.by_type.slice(0, 12).map(([k, v], i) => ({ label: k, value: v, color: SERIES[i % 8] }))} /><//>
      <${Card} title="Events by source system" icon="network"><${HBars} rows=${prev.activity.by_source.map(([k, v], i) => ({ label: k, value: v, color: SERIES[i % 8] }))} />
        <div class="sep" style="margin:14px 0"></div><div class="small muted" style="margin-bottom:8px">Reported results (claims)</div><div class="row wrap">${prev.activity.results.map(([k, v]) => html`<${Badge} mono=${true}>${k} ${v}<//>`)}</div><//></div>`}
  </div>`;
}
