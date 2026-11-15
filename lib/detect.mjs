// Detect a local COMSOL Multiphysics installation, its version, and the
// Python interpreter that can drive it through MPh.
//
// COMSOL 6.4 is the supported baseline; older releases are rejected by default
// (override with COMSOL_ALLOW_UNSUPPORTED=1). This file is used by the plugin
// load path and by `bin/dsh-comsol.mjs doctor`, so it must not import anything
// from the dsh runtime.
//
// The important difference from a "load a plugin into the CAE kernel" design:
// COMSOL is driven out of process. MPh (a Python package) talks to
// comsolmphserver.exe through JPype, so the MCP server has to run under the
// interpreter that has `mph` + `jpype` installed — a bare stdlib python will
// import-fail at startup. detectComsol() therefore also resolves that
// interpreter (findMphPython).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

export const MIN_VERSION = process.env.COMSOL_MIN_VERSION || "6.4";
export const DSH_HOME = process.env.DSH_HOME || path.join(os.homedir(), ".dsh");
export const CONFIG_FILE = path.join(DSH_HOME, "comsol.json");

// Known-good MPh environment on this machine (E:\ICE\_tools\...). Tried after
// COMSOL_MCP_PYTHON and the config file, before scanning for other venvs.
export const DEFAULT_MPH_PYTHON =
  "E:\\ICE\\_tools\\COMSOL_Multiphysics_MCP\\.venv\\Scripts\\python.exe";

const COMSOL_EXES = {
  comsol: "comsol.exe",
  mphserver: "comsolmphserver.exe",
  batch: "comsolbatch.exe",
};

function exists(p) {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

function readConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_FILE, "utf8"));
  } catch {
    return {};
  }
}

function readdirSafe(dir) {
  try {
    return fs.readdirSync(dir);
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------- versions ---

export function versionTuple(v) {
  const m = /^(\d+)\.(\d+)/.exec(String(v || "").trim());
  return m ? [Number(m[1]), Number(m[2])] : null;
}

// Returns <0, 0 or >0 like a comparator; null when either side is unparseable.
export function compareVersions(a, b) {
  const ta = versionTuple(a);
  const tb = versionTuple(b);
  if (!ta || !tb) return null;
  return ta[0] - tb[0] || ta[1] - tb[1];
}

// "6.4" from the folder name COMSOL64, or from about.txt ("... IN COMSOL 6.4").
function readVersion(installRoot) {
  const about = path.join(installRoot, "about.txt");
  if (exists(about)) {
    try {
      const head = fs.readFileSync(about, "utf8").slice(0, 4096);
      const m = /COMSOL\s+(\d+\.\d+)/i.exec(head);
      if (m) return m[1];
    } catch {
      /* fall through to the folder name */
    }
  }
  const parent = path.basename(path.dirname(installRoot)); // "COMSOL64"
  const m = /^COMSOL(\d)(\d)$/i.exec(parent);
  if (m) return `${m[1]}.${m[2]}`;
  const own = /COMSOL(\d)(\d)$/i.exec(path.basename(installRoot));
  if (own) return `${own[1]}.${own[2]}`;
  return null;
}

// ------------------------------------------------------------ installations ---

function makeInstall(installRoot) {
  const binDir = path.join(installRoot, "bin", "win64");
  const comsolExe = path.join(binDir, COMSOL_EXES.comsol);
  const mphserverExe = path.join(binDir, COMSOL_EXES.mphserver);
  const batchExe = path.join(binDir, COMSOL_EXES.batch);
  if (!exists(comsolExe) && !exists(mphserverExe) && !exists(batchExe)) return null;
  const version = readVersion(installRoot);
  return {
    version,
    installRoot,
    binDir,
    comsolExe: exists(comsolExe) ? comsolExe : null,
    mphserverExe: exists(mphserverExe) ? mphserverExe : null,
    batchExe: exists(batchExe) ? batchExe : null,
  };
}

// Turn "...\COMSOL64\Multiphysics\bin\win64\comsol.exe" into the install root.
function rootFromExe(exe) {
  let dir = path.dirname(exe);
  if (path.basename(dir).toLowerCase() === "win64") dir = path.dirname(dir);
  if (path.basename(dir).toLowerCase() === "bin") dir = path.dirname(dir);
  if (path.basename(dir).toLowerCase() === "multiphysics") return dir;
  return path.join(dir, "Multiphysics");
}

function releaseRoots(base) {
  // base\COMSOL64\Multiphysics and base\COMSOL64 (some layouts omit Multiphysics)
  const out = [];
  for (const name of readdirSafe(base)) {
    if (!/^COMSOL\d+$/i.test(name)) continue;
    const top = path.join(base, name);
    out.push(path.join(top, "Multiphysics"));
    out.push(top);
  }
  return out;
}

function candidateRoots() {
  const out = [];
  const push = (p) => {
    if (!p) return;
    const resolved = path.resolve(p);
    if (!out.some((q) => q.toLowerCase() === resolved.toLowerCase())) out.push(resolved);
  };

  // 1. Explicit overrides.
  if (process.env.COMSOL_HOME) {
    const home = process.env.COMSOL_HOME;
    push(home);
    push(path.join(home, "Multiphysics"));
    if (/win64$/i.test(home)) push(rootFromExe(path.join(home, COMSOL_EXES.comsol)));
  }
  for (const exe of [process.env.COMSOL_EXE, readConfig().comsolExe]) {
    if (exe && exists(exe)) push(rootFromExe(exe));
  }

  // 2. The standard Windows layout.
  push("C:\\Program Files\\COMSOL\\COMSOL64\\Multiphysics");
  push("C:\\Program Files\\COMSOL\\COMSOL64");

  // 3. Any release under Program Files, then other drives.
  for (const base of [
    "C:\\Program Files\\COMSOL",
    "C:\\Program Files (x86)\\COMSOL",
  ]) {
    for (const r of releaseRoots(base)) push(r);
  }
  for (const drive of ["C:", "D:", "E:", "F:"]) {
    for (const base of [
      `${drive}\\COMSOL`,
      `${drive}\\Program Files\\COMSOL`,
      `${drive}\\Program Files (x86)\\COMSOL`,
      `${drive}\\COMSOL Multiphysics`,
    ]) {
      for (const r of releaseRoots(base)) push(r);
    }
  }
  return out;
}

export function listInstallations() {
  const seen = new Set();
  const out = [];
  for (const root of candidateRoots()) {
    const key = root.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const install = makeInstall(root);
    if (!install) continue;
    out.push(install);
  }
  out.sort((a, b) => (compareVersions(b.version, a.version) ?? 0));
  return out;
}

// ------------------------------------------------------------ MPh python ---

const PROBE = [
  "import json, sys",
  "out = {'version': sys.version.split()[0], 'mph': None, 'jpype': None, 'error': None}",
  "try:",
  "    import mph",
  "    out['mph'] = getattr(mph, '__version__', '?')",
  "    try:",
  "        import jpype",
  "        out['jpype'] = getattr(jpype, '__version__', '?')",
  "    except Exception as exc:",
  "        out['jpype'] = None",
  "except Exception as exc:",
  "    out['error'] = type(exc).__name__ + ': ' + str(exc)[:200]",
  "print(json.dumps(out))",
].join("\n");

const probeCache = new Map();

// Probe one interpreter. Returns {path, version, mph, mphVersion, jpype, error}
// or null when the path is not a runnable python.
export function probePython(exe) {
  if (!exe) return null;
  const key = exe.toLowerCase();
  if (probeCache.has(key)) return probeCache.get(key);
  let result = null;
  if (exists(exe)) {
    const res = spawnSync(exe, ["-c", PROBE], {
      encoding: "utf8",
      timeout: 30000,
      windowsHide: true,
    });
    const text = `${res.stdout || ""}`.trim();
    if (res.status === 0 && text) {
      const line = text.split(/\r?\n/).filter(Boolean).pop();
      try {
        const parsed = JSON.parse(line);
        result = {
          path: exe,
          version: parsed.version || null,
          mph: Boolean(parsed.mph),
          mphVersion: parsed.mph || null,
          jpype: parsed.jpype || null,
          error: parsed.error || null,
        };
      } catch {
        result = { path: exe, version: null, mph: false, mphVersion: null, jpype: null, error: "unparseable probe output" };
      }
    } else {
      result = {
        path: exe,
        version: null,
        mph: false,
        mphVersion: null,
        jpype: null,
        error: (res.stderr || "interpreter did not run").trim().slice(0, 200),
      };
    }
  }
  probeCache.set(key, result);
  return result;
}

function venvPythons() {
  const out = [];
  const bases = ["E:\\ICE\\_tools", path.join(os.homedir(), "venvs")];
  for (const base of bases) {
    for (const name of readdirSafe(base)) {
      if (out.length >= 16) break;
      for (const venv of [".venv", "venv", "env"]) {
        const exe = path.join(base, name, venv, "Scripts", "python.exe");
        if (exists(exe)) out.push(exe);
      }
    }
  }
  return out;
}

function pathPythons() {
  const out = [];
  for (const name of ["python", "python3", "py"]) {
    const res = spawnSync("where", [name], { encoding: "utf8", timeout: 5000, windowsHide: true });
    if (res.status !== 0 || !res.stdout) continue;
    for (const line of res.stdout.split(/\r?\n/)) {
      const p = line.trim();
      if (p && /\.exe$/i.test(p) && !out.includes(p)) out.push(p);
    }
  }
  return out;
}

// Resolve the interpreter that can drive COMSOL: COMSOL_MCP_PYTHON, then the
// config file, then the known MPh venv, then any venv / PATH python that can
// `import mph`.
export function findMphPython(opts = {}) {
  const cfg = opts.cfg || readConfig();
  const candidates = [];
  const push = (p, source) => {
    if (!p) return;
    const key = p.toLowerCase();
    if (candidates.some((c) => c.path.toLowerCase() === key)) return;
    candidates.push({ path: p, source });
  };

  push(process.env.COMSOL_MCP_PYTHON, "COMSOL_MCP_PYTHON");
  push(cfg.python, "config");
  push(DEFAULT_MPH_PYTHON, "known MPh venv");
  for (const p of venvPythons()) push(p, "venv scan");
  for (const p of pathPythons()) push(p, "PATH");

  const rejected = [];
  for (const cand of candidates) {
    const probed = probePython(cand.path);
    if (probed && probed.mph) {
      return { ...probed, source: cand.source, rejected };
    }
    if (probed) rejected.push({ path: cand.path, source: cand.source, error: probed.error });
    else rejected.push({ path: cand.path, source: cand.source, error: "not found" });
  }
  return null;
}

// ---------------------------------------------------------------- detect ---

export function detectComsol(opts = {}) {
  const cfg = readConfig();
  const installs = listInstallations();
  const min = String(opts.minVersion || process.env.COMSOL_MIN_VERSION || cfg.minVersion || MIN_VERSION);

  // Prefer an explicit exe, else the newest release found.
  let chosen = null;
  const explicit = [process.env.COMSOL_EXE, cfg.comsolExe].find((p) => p && exists(p));
  if (explicit) {
    chosen = makeInstall(rootFromExe(explicit));
  }
  if (!chosen) chosen = installs[0] || null;

  const version = chosen ? chosen.version : null;
  const cmp = version ? compareVersions(version, min) : null;
  const supported = Boolean(version && cmp !== null && cmp >= 0);

  const python = findMphPython({ cfg });

  let reason = null;
  if (!chosen) {
    reason =
      "COMSOL installation not found (no comsol.exe under C:\\Program Files\\COMSOL\\COMSOL*, " +
      "no COMSOL_HOME, no COMSOL_EXE).";
  } else if (!version) {
    reason = "Found a COMSOL bin\\win64 folder but could not determine its version (about.txt / COMSOL<XY> folder name).";
  } else if (!supported) {
    reason = `COMSOL ${version} is older than the supported baseline ${min}.`;
  } else if (!python) {
    reason =
      "COMSOL was found, but no Python interpreter with the MPh package (import mph) was located. " +
      "Set COMSOL_MCP_PYTHON to the MPh venv python.exe.";
  }

  return {
    found: Boolean(chosen),
    version,
    minVersion: min,
    supported,
    reason,
    installRoot: chosen ? chosen.installRoot : null,
    binDir: chosen ? chosen.binDir : null,
    comsolExe: chosen ? chosen.comsolExe : null,
    mphserverExe: chosen ? chosen.mphserverExe : null,
    batchExe: chosen ? chosen.batchExe : null,
    python,
    installations: installs,
  };
}
