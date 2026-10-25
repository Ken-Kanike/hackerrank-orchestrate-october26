/* ========================================================================================
   actions: everything the UI can execute
   ======================================================================================== */
const ABLATIONS = [
  ["Default (all switches on)", {}],
  ["No workflow-run alignment", { USE_RUN_ALIGNMENT: false }],
  ["Lenient time model", { STRICT_TIME: false }],
  ["No lineage propagation", { USE_LINEAGE: false }],
  ["No activity state checks", { USE_ACTIVITY_CHECKS: false }],
  ["No ghost sweep", { USE_GHOST_SWEEP: false }],
  ["Legacy earlier-request cut-off (all users)", { PARTITION_SINGLE_CASE_USERS_ONLY: false }],
];

function expectedStages(cfg, hasGold) {
  const ids = ["evidence", "catalog", "intent", "linking", "ghost", "solve"];
  if (cfg.mode === "hybrid" && cfg.vision) ids.unshift("vision");
  if (cfg.mode === "hybrid" && cfg.flags.USE_INVESTIGATOR) ids.splice(ids.indexOf("ghost"), 0, "investigator");
  if (hasGold) ids.push("scoring");
  return ids;
}
function resetRun(label, cfg, hasGold) {
  const stages = {};
  expectedStages(cfg, hasGold).forEach((id) => { stages[id] = { status: "pending" }; });
  Store.set({ run: { status: "running", stages, logs: [{ t: Date.now() / 1000, level: "info", msg: label }], llm: [], startedAt: Date.now() / 1000, finishedAt: null, error: null, label } });
}
function resolveGold(cfg, info) {
  if (cfg.gold === "none") return null;
  if (cfg.gold !== "auto") return cfg.gold;
  const g = (info && info.gold) || [];
  const samples = cfg.requestsFile === "sample_deletion_requests.csv";
  return (samples ? g.find((x) => x === "sample_output.csv") : g.find((x) => x !== "sample_output.csv")) || null;
}

const Actions = {
  async prepare(mode) {
    await Engine.start();
    if (mode === "hybrid") await Vault.pushEnv();
  },

  async runAudit() {
    const s = Store.get();
    if (s.run.status === "running") return;
    const ds = s.datasets[s.activeDataset];
    if (!ds || !ds.info || !ds.info.ok) { toast("Select a complete dataset first (deletion_requests, identities, audit log, activity, rules, manifest).", "error"); return; }
    const cfg = s.cfg, gold = resolveGold(cfg, ds.info);
    resetRun(`Audit: ${ds.name} (${cfg.mode})`, cfg, !!gold);
    try {
      await Actions.prepare(cfg.mode);
      await Datasets.ensure(ds.id);
      const opts = { data: "/app/data/" + ds.id, requests_file: cfg.requestsFile, mode: cfg.mode, vision: cfg.vision, flags: cfg.flags, gold, limit: cfg.limit ? Number(cfg.limit) : null, refresh_llm: cfg.refresh, sort: cfg.sort, pool_samples: cfg.poolSamples };
      const res = await Engine.callJson("run_audit", JSON.stringify(opts));
      res.meta = { dataset: ds.name, finishedAt: Date.now() / 1000, gold, cfg: { ...cfg, flags: { ...cfg.flags } } };
      Store.set((st) => ({ result: res, run: { ...st.run, status: "done", finishedAt: Date.now() / 1000 }, history: [{ id: uid(), at: Date.now(), dataset: ds.name, mode: cfg.mode, summary: res.summary, metrics: res.metrics }, ...st.history].slice(0, 20) }));
      toast(`Audit finished: ${res.summary.cases} ${res.summary.cases === 1 ? "case" : "cases"} in ${fmt.ms(res.summary.duration_ms)}`, "ok");
    } catch (e) {
      if (String(e.message) === "cancelled") return;
      Store.set((st) => ({ run: { ...st.run, status: "error", error: e.message, finishedAt: Date.now() / 1000 } }));
      toast("Run failed: " + e.message.split("\n").slice(-2)[0], "error", 8000);
    }
  },

  async cancel() {
    Store.set((st) => ({ run: { ...st.run, status: "cancelled", finishedAt: Date.now() / 1000, logs: [...st.run.logs, { t: Date.now() / 1000, level: "warn", msg: "Cancelled - restarting the engine worker" }] }, tools: { ...st.tools, busy: null } }));
    toast("Cancelled. Restarting the engine (Python runs in a worker and can only be stopped by restarting it).", "info", 6000);
    Engine.restart().then(async () => { await Vault.pushEnv(); const id = Store.get().activeDataset; if (id) Datasets.ensure(id).catch(() => {}); }).catch(() => {});
  },

  async ensureDemoSuite() {
    await Engine.start();
    if (Engine.loaded.has("__demo_suite")) return;
    const enc = new TextEncoder(), files = [];
    for (const [name, fs] of Object.entries(DEMO)) for (const [p, t] of Object.entries(fs)) files.push({ path: "demo_suite/" + name + "/" + p, data: enc.encode(t).buffer });
    await Engine.write(files);
    Engine.loaded.add("__demo_suite");
  },

  async runSuite() {
    if (Store.get().tools.busy) return;
    Store.set((st) => ({ tools: { ...st.tools, busy: "suite" } }));
    resetRun("Demo suite: 8 end-to-end scenarios", { mode: "offline", flags: FLAG_DEFAULTS, vision: false }, true);
    try {
      await Actions.ensureDemoSuite();
      const res = await Engine.callJson("run_custom_suite", "/app/data/demo_suite");
      Store.set((st) => ({ tools: { ...st.tools, suite: res, busy: null }, run: { ...st.run, status: "done", finishedAt: Date.now() / 1000 } }));
      const ok = res.datasets.filter((d) => d.exact).length;
      toast(`Demo suite: ${ok}/${res.datasets.length} scenarios exactly match their expected output`, ok === res.datasets.length ? "ok" : "error");
    } catch (e) { Store.set((st) => ({ tools: { ...st.tools, busy: null }, run: { ...st.run, status: "error", error: e.message } })); toast("Suite failed: " + e.message.slice(-120), "error"); }
  },

  async runAblation() {
    const s = Store.get(); const ds = s.datasets[s.activeDataset];
    if (!ds || !ds.info?.ok) { toast("Select a dataset first", "error"); return; }
    const gold = resolveGold(s.cfg, ds.info);
    if (s.tools.busy) return;
    Store.set((st) => ({ tools: { ...st.tools, busy: "ablation", ablation: null } }));
    resetRun("Ablation: " + ds.name, { mode: "offline", flags: FLAG_DEFAULTS, vision: false }, !!gold);
    try {
      await Datasets.ensure(ds.id);
      const configs = ABLATIONS.map(([name, flags]) => ({ name, flags }));
      const res = await Engine.callJson("run_ablation", JSON.stringify({ data: "/app/data/" + ds.id, gold, requests_file: s.cfg.requestsFile, configs }));
      Store.set((st) => ({ tools: { ...st.tools, ablation: { ...res, dataset: ds.name, gold }, busy: null }, run: { ...st.run, status: "done", finishedAt: Date.now() / 1000 } }));
      toast("Ablation finished", "ok");
    } catch (e) { Store.set((st) => ({ tools: { ...st.tools, busy: null }, run: { ...st.run, status: "error", error: e.message } })); toast("Ablation failed: " + e.message.slice(-120), "error"); }
  },

  async runRecovery(folds, repeats) {
    const s = Store.get(); const ds = s.datasets[s.activeDataset];
    if (!ds || !ds.info?.ok) { toast("Select a dataset first", "error"); return; }
    if (s.tools.busy) return;
    Store.set((st) => ({ tools: { ...st.tools, busy: "recovery", recovery: null } }));
    resetRun("Link-recovery test: " + ds.name, { mode: "offline", flags: FLAG_DEFAULTS, vision: false }, false);
    try {
      await Datasets.ensure(ds.id);
      const res = await Engine.callJson("run_recovery", JSON.stringify({ data: "/app/data/" + ds.id, folds, repeats, flags: s.cfg.flags }));
      Store.set((st) => ({ tools: { ...st.tools, recovery: { ...res, dataset: ds.name }, busy: null }, run: { ...st.run, status: "done", finishedAt: Date.now() / 1000 } }));
      toast("Link-recovery test finished", "ok");
    } catch (e) { Store.set((st) => ({ tools: { ...st.tools, busy: null }, run: { ...st.run, status: "error", error: e.message } })); toast("Recovery test failed: " + e.message.slice(-120), "error"); }
  },

  async testKey(item) {
    try {
      await Engine.start();
      const r = JSON.parse(await Engine.call("test_key", item.provider, item.secret || "none", item.base_url || ""));
      return r;
    } catch (e) { return { ok: false, error: e.message.slice(-140) }; }
  },
};
