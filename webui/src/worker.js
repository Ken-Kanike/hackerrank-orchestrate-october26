/* Engine worker: Pyodide (CPython in WebAssembly) running the real auditor package. Synchronous I/O is fine here (no UI thread). */
const PYODIDE_VERSION = "0.27.7";
let pyodide = null;
let service = null;

function post(o) { self.postMessage(o); }
function boot(step, detail) { post({ type: "boot", step, detail }); }

function mkdirp(path) {
  const parts = path.split("/").filter(Boolean);
  let cur = "";
  for (const p of parts) { cur += "/" + p; try { pyodide.FS.mkdir(cur); } catch (e) { /* exists */ } }
}

async function init(pysrc) {
  boot("runtime", "Loading Python runtime (Pyodide " + PYODIDE_VERSION + ")");
  importScripts("https://cdn.jsdelivr.net/pyodide/v" + PYODIDE_VERSION + "/full/pyodide.js");
  pyodide = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v" + PYODIDE_VERSION + "/full/" });
  boot("sources", "Installing the auditor package");
  for (const [path, text] of Object.entries(pysrc)) {
    const full = "/app/" + path;
    mkdirp(full.substring(0, full.lastIndexOf("/")));
    pyodide.FS.writeFile(full, text);
  }
  boot("deps", "Loading sqlite3 (SQL snapshot evidence)");
  await pyodide.loadPackage("sqlite3");
  let pdf = true;
  boot("deps", "Installing pypdf (PDF evidence)");
  try {
    await pyodide.loadPackage("micropip");
    await pyodide.runPythonAsync("import micropip\nawait micropip.install('pypdf')");
  } catch (e) {
    pdf = false;
    boot("deps-warn", "pypdf unavailable - PDF evidence will be skipped (" + String(e).slice(0, 120) + ")");
  }
  boot("engine", "Starting the engine");
  pyodide.runPython(`
import sys, json, js
sys.path[:0] = ['/app', '/app/code']
import browser_io
browser_io.install()
from auditor import events
def _sink(e):
    js.postMessage(json.dumps({"type": "event", "e": e}))
events.set_sink(_sink)
import service as S
`);
  if (!pdf) {
    pyodide.runPython(`
from auditor import evidence
evidence.pdf_text = lambda path: ""
`);
  }
  service = pyodide.globals.get("S");
  boot("ready", "Engine ready");
  return { pdf, python: pyodide.runPython("import sys; sys.version.split()[0]") };
}

self.onmessage = async (ev) => {
  const m = ev.data;
  try {
    let result;
    if (m.cmd === "init") result = await init(m.pysrc);
    else if (m.cmd === "write") {
      for (const f of m.files) {
        const full = "/app/data/" + f.path;
        mkdirp(full.substring(0, full.lastIndexOf("/")));
        pyodide.FS.writeFile(full, new Uint8Array(f.data));
      }
      result = m.files.length;
    } else if (m.cmd === "remove") {
      pyodide.runPython("import shutil; shutil.rmtree('/app/data/" + m.dir.replace(/[^\w\-./]/g, "") + "', ignore_errors=True)");
      result = true;
    } else if (m.cmd === "call") {
      result = service[m.fn](...m.args);
    } else throw new Error("unknown command " + m.cmd);
    post({ id: m.id, ok: true, result });
  } catch (e) {
    post({ id: m.id, ok: false, error: String((e && e.message) || e) });
  }
};
