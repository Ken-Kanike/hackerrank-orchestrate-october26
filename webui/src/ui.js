/* ========================================================================================
   ui primitives + charts (hand-built, shadcn-style)
   ======================================================================================== */
function Icon({ n, cls: c = "", title }) {
  const inner = ICONS[n] || "";
  return html`<svg class=${cls("icon", c)} viewBox="0 0 24 24" aria-hidden=${title ? "false" : "true"} role=${title ? "img" : null} dangerouslySetInnerHTML=${{ __html: (title ? `<title>${title}</title>` : "") + inner }}></svg>`;
}
function Badge({ kind = "", children, mono, tip }) { return html`<span class=${cls("badge", kind, mono && "mono")} data-tip=${tip}>${children}</span>`; }
function StatusBadge({ status }) {
  const m = { COMPLETE: ["ok", "circle-check", "Complete"], INCOMPLETE: ["warn", "triangle-alert", "Incomplete"], NOT_APPLICABLE: ["", "circle-dashed", "Not applicable"] }[status] || ["", "info", status];
  return html`<${Badge} kind=${m[0]}><${Icon} n=${m[1]} cls="sm" />${m[2]}<//>`;
}
function Switch({ on, onChange, label, hint, disabled }) {
  return html`<div class="row between" style="align-items:flex-start;gap:14px">
    <div class="grow"><div class="small strong" style="color:var(--foreground)">${label}</div>${hint && html`<div class="hint">${hint}</div>`}</div>
    <button class="switch" role="switch" aria-checked=${on ? "true" : "false"} aria-label=${label} disabled=${disabled} onClick=${() => onChange(!on)}></button>
  </div>`;
}
function Seg({ value, options, onChange, label }) {
  return html`<div class="seg" role="group" aria-label=${label}>${options.map(([v, l, ic, dis]) => html`<button aria-pressed=${value === v ? "true" : "false"} disabled=${dis} onClick=${() => onChange(v)}>${ic && html`<${Icon} n=${ic} cls="sm" />`}${l}</button>`)}</div>`;
}
function Tabs({ value, options, onChange }) {
  return html`<div class="tabs" role="tablist">${options.map(([v, l, ic, count]) => html`<button role="tab" aria-selected=${value === v ? "true" : "false"} onClick=${() => onChange(v)}>${ic && html`<${Icon} n=${ic} cls="sm" />`}${l}${count != null && html`<span class="badge" style="height:18px">${count}</span>`}</button>`)}</div>`;
}
function Card({ title, sub, icon, actions, children, cls: c = "", bodyCls = "", flat }) {
  return html`<section class=${cls("card", flat && "flat", c)}>
    ${(title || actions) && html`<div class="hd"><div class="grow row" style="gap:10px">${icon && html`<${Icon} n=${icon} cls="lg" />`}<div><h2>${title}</h2>${sub && html`<div class="sub">${sub}</div>`}</div></div>${actions}</div>`}
    <div class=${cls("bd", bodyCls)}>${children}</div></section>`;
}
function Stat({ k, v, d, icon, color, tip }) {
  return html`<div class="card stat" data-tip=${tip}><div class="k">${icon && html`<${Icon} n=${icon} cls="sm" />`}${k}</div><div class="v" style=${color ? `color:${color}` : ""}>${v}</div>${d && html`<div class="d">${d}</div>`}</div>`;
}
function Progress({ value, indeterminate }) { return html`<div class=${cls("progress", indeterminate && "indeterminate")} role="progressbar" aria-valuenow=${Math.round((value || 0) * 100)} aria-valuemin="0" aria-valuemax="100"><i style=${"width:" + Math.round((value || 0) * 100) + "%"}></i></div>`; }
function Empty({ icon = "circle-dashed", title, children }) { return html`<div class="empty"><${Icon} n=${icon} /><div class="strong" style="color:var(--foreground)">${title}</div><div class="small" style="max-width:420px">${children}</div></div>`; }
function Banner({ kind = "info", icon, children }) { return html`<div class=${cls("banner", kind)}><${Icon} n=${icon || { info: "info", warn: "triangle-alert", err: "circle-x", ok: "circle-check" }[kind]} />
  <div class="grow">${children}</div></div>`; }
function Chip({ children, kind }) { return html`<span class=${cls("chip", kind)}>${children}</span>`; }
function EvChip({ id }) { return id ? html`<span class="chip ev" data-tip="evidence cited for this step">${id}</span>` : html`<span class="chip empty" data-tip="future work: no evidence by contract">-</span>`; }

function Drawer({ title, sub, onClose, children, actions }) {
  useEffect(() => { const f = (e) => e.key === "Escape" && onClose(); addEventListener("keydown", f); return () => removeEventListener("keydown", f); }, []);
  return html`<${Fragment}><div class="scrim" onClick=${onClose}></div>
    <aside class="drawer" role="dialog" aria-modal="true" aria-label=${title}>
      <div class="dh"><div class="grow"><h2>${title}</h2>${sub && html`<div class="small muted">${sub}</div>`}</div>${actions}<button class="btn ghost icon-only sm" aria-label="Close" onClick=${onClose}><${Icon} n="x" /></button></div>
      <div class="db">${children}</div></aside><//>`;
}
function Dialog({ title, onClose, children }) {
  useEffect(() => { const f = (e) => e.key === "Escape" && onClose(); addEventListener("keydown", f); return () => removeEventListener("keydown", f); }, []);
  return html`<${Fragment}><div class="scrim" onClick=${onClose}></div><div class="dialog" role="dialog" aria-modal="true" aria-label=${title}>
    <div class="row between" style="margin-bottom:14px"><h2>${title}</h2><button class="btn ghost icon-only sm" aria-label="Close" onClick=${onClose}><${Icon} n="x" /></button></div>${children}</div><//>`;
}

/* ---------- global tooltip (data-tip) ---------- */
function installTooltips() {
  const el = document.createElement("div"); el.className = "tip"; el.style.display = "none"; document.body.appendChild(el);
  let cur = null;
  const show = (t, x, y) => {
    el.textContent = t; el.style.display = "block";
    const r = el.getBoundingClientRect();
    el.style.left = Math.min(innerWidth - r.width - 8, Math.max(8, x + 12)) + "px"; el.style.top = Math.min(innerHeight - r.height - 8, y + 14) + "px";
  };
  document.addEventListener("pointermove", (e) => {
    const t = e.target.closest ? e.target.closest("[data-tip]") : null;
    if (t && t.getAttribute("data-tip")) { cur = t; show(t.getAttribute("data-tip"), e.clientX, e.clientY); } else if (cur) { cur = null; el.style.display = "none"; }
  });
  document.addEventListener("pointerleave", () => { el.style.display = "none"; });
  document.addEventListener("scroll", () => { el.style.display = "none"; }, true);
}

/* ---------- charts ---------- */
function StackBar({ parts, height = 10 }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  return html`<div class="bar" style=${"height:" + height + "px"} role="img" aria-label=${parts.map((p) => p.label + " " + p.value).join(", ")}>${parts.filter((p) => p.value > 0).map((p) => html`<i style=${`width:${(p.value / total) * 100}%;background:${p.color}`} data-tip=${p.label + ": " + p.value + " (" + fmt.pct(p.value / total) + ")"}></i>`)}</div>`;
}
function Legend({ items }) { return html`<div class="legend">${items.map((i) => html`<span><i style=${"background:" + i.color}></i>${i.label}${i.value != null ? " " + i.value : ""}</span>`)}</div>`; }
function HBars({ rows, max, fmtv = (v) => v, unit }) {
  const m = max || Math.max(1, ...rows.map((r) => r.value));
  return html`<div class="col" style="gap:9px">${rows.map((r) => html`<div data-tip=${r.tip || r.label + ": " + fmtv(r.value)}>
    <div class="row between small" style="margin-bottom:3px"><span class="trunc" style="max-width:70%">${r.label}</span><span class="mono muted">${fmtv(r.value)}${unit || ""}</span></div>
    <div class="bar"><i style=${`width:${Math.max(0.5, (r.value / m) * 100)}%;background:${r.color || "var(--primary)"};border-radius:4px`}></i></div></div>`)}</div>`;
}
function Donut({ parts, size = 132, label, sub }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1, r = size / 2 - 11, c = 2 * Math.PI * r;
  let off = 0;
  return html`<svg class="chart" width=${size} height=${size} viewBox=${`0 0 ${size} ${size}`} role="img" aria-label=${parts.map((p) => p.label + " " + p.value).join(", ")}>
    <circle cx=${size / 2} cy=${size / 2} r=${r} fill="none" stroke="var(--muted)" stroke-width="12" />
    ${parts.filter((p) => p.value > 0).map((p) => { const len = (p.value / total) * c, el = html`<circle cx=${size / 2} cy=${size / 2} r=${r} fill="none" stroke=${p.color} stroke-width="12" stroke-dasharray=${`${Math.max(0, len - 2)} ${c}`} stroke-dashoffset=${-off} transform=${`rotate(-90 ${size / 2} ${size / 2})`} data-tip=${p.label + ": " + p.value + " (" + fmt.pct(p.value / total) + ")"}><//>`; off += len; return el; })}
    <text x="50%" y="48%" text-anchor="middle" style="font-size:20px;font-weight:600;fill:var(--foreground)">${label}</text>
    ${sub && html`<text x="50%" y="62%" text-anchor="middle">${sub}</text>`}</svg>`;
}
function Spark({ values, w = 120, h = 28, color = "var(--primary)" }) {
  if (!values.length) return null;
  const mx = Math.max(...values, 1), step = w / Math.max(values.length - 1, 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(h - 3 - (v / mx) * (h - 6)).toFixed(1)}`).join(" ");
  return html`<svg class="chart" width=${w} height=${h} viewBox=${`0 0 ${w} ${h}`} aria-hidden="true"><polyline points=${pts} fill="none" stroke=${color} stroke-width="2" stroke-linejoin="round" stroke-linecap="round" /></svg>`;
}
/** Stage waterfall: one bar per stage positioned on the run's timeline. */
function Waterfall({ stages, order }) {
  const items = order.map((s) => ({ s, st: stages[s.id] })).filter((x) => x.st && x.st.startedAt);
  if (!items.length) return html`<div class="muted small">No stage timings yet.</div>`;
  const t0 = Math.min(...items.map((x) => x.st.startedAt)), t1 = Math.max(...items.map((x) => x.st.endedAt || Date.now() / 1000));
  const span = Math.max(t1 - t0, 0.001);
  return html`<div class="col" style="gap:7px">${items.map(({ s, st }, i) => {
    const left = ((st.startedAt - t0) / span) * 100, w = Math.max(0.8, (((st.endedAt || Date.now() / 1000) - st.startedAt) / span) * 100);
    return html`<div class="row" style="gap:10px"><div class="small trunc" style="width:150px;flex:none">${s.name}</div>
      <div class="grow" style="position:relative;height:14px;background:var(--muted);border-radius:4px" data-tip=${s.name + ": " + fmt.ms(st.ms ?? ((Date.now() / 1000 - st.startedAt) * 1000))}>
        <i style=${`position:absolute;left:${left}%;width:${Math.min(w, 100 - left)}%;top:0;bottom:0;border-radius:4px;background:${SERIES[i % 8]};opacity:${st.status === "running" ? 0.65 : 1}`}></i></div>
      <div class="mono small muted" style="width:70px;text-align:right;flex:none">${st.ms != null ? fmt.ms(st.ms) : "…"}</div></div>`;
  })}</div>`;
}
function Heat({ rows, cols, matrix, label }) {
  const mx = Math.max(1, ...matrix.flat());
  return html`<div class="table-wrap"><table class="t heat" aria-label=${label}><thead><tr><th>actual \\ predicted</th>${cols.map((c) => html`<th style="text-align:center">${c}</th>`)}</tr></thead>
    <tbody>${rows.map((r, i) => html`<tr><td class="muted">${r}</td>${matrix[i].map((v, j) => html`<td style=${`background:color-mix(in srgb, ${i === j ? "var(--ok)" : "var(--err)"} ${Math.round((v / mx) * 38)}%, transparent);font-weight:${v ? 600 : 400}`}>${v || html`<span class="faint">0</span>`}</td>`)}</tr>`)}</tbody></table></div>`;
}
