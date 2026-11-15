// Resolve every path this bundle needs at runtime from its own location plus a
// small JSON file under ~/.dsh. Nothing is pinned to one machine: the COMSOL
// launcher and the MPh interpreter are discovered (lib/detect.mjs) or set in
// the config file.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CONFIG_FILE as DETECT_CONFIG_FILE, DSH_HOME as DETECT_DSH_HOME, detectComsol, findMphPython } from "./detect.mjs";

export const PKG_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const PKG = JSON.parse(fs.readFileSync(path.join(PKG_ROOT, "package.json"), "utf8"));

export const DSH_HOME = DETECT_DSH_HOME;
export const CONFIG_FILE = DETECT_CONFIG_FILE;
export const DEFAULT_PROJECT_ROOT =
  process.env.COMSOL_PROJECT_ROOT || "E:\\ICE\\COMSOL-Arc-Reproduction\\03_Models\\arc model";
export const DEFAULT_PORT = 2036;
export const DEFAULT_MODE = "mphserver";

export function exists(p) {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

// COMSOL work directory: an explicit override, else <drive>:\COMSOL\work on the
// first fixed drive that looks like a data drive (E: preferred, then D:).
export function defaultWorkDir() {
  if (process.env.COMSOL_MCP_WORKDIR) return process.env.COMSOL_MCP_WORKDIR;
  for (const drive of ["E:", "D:", "C:", "F:"]) {
    if (exists(drive + "\\")) return path.join(drive + "\\", "COMSOL", "work");
  }
  return path.join(os.homedir(), "COMSOL", "work");
}

export function findComsolExe() {
  if (process.env.COMSOL_EXE && exists(process.env.COMSOL_EXE)) return process.env.COMSOL_EXE;
  const cfg = readConfig();
  if (cfg.comsolExe && exists(cfg.comsolExe)) return cfg.comsolExe;
  const detected = detectComsol();
  return detected.comsolExe || "comsol";
}

export function readConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_FILE, "utf8"));
  } catch {
    return {};
  }
}

export function writeConfig(cfg) {
  fs.mkdirSync(path.dirname(CONFIG_FILE), { recursive: true });
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(cfg, null, 2) + "\n", "utf8");
}

// Fill the config from the resolved layout without touching the disk. Returns
// {cfg, changed}; ensureConfig() persists it.
export function computeConfig(layout) {
  const cfg = readConfig();
  let changed = false;
  const set = (key, value) => {
    if (value === undefined || value === null || value === "") return;
    if (cfg[key] !== value) {
      cfg[key] = value;
      changed = true;
    }
  };

  set("workDir", layout.workDir);
  set("python", layout.python);
  set("comsolExe", layout.comsolExe);
  set("mphserverExe", layout.mphserverExe);
  set("batchExe", layout.batchExe);
  set("port", cfg.port || layout.port || DEFAULT_PORT);
  set("mode", cfg.mode || layout.mode || DEFAULT_MODE);
  // Project folder the workbench panel scans for models / reports / figures.
  set("workbenchProjectRoot", cfg.workbenchProjectRoot || process.env.COMSOL_PROJECT_ROOT || DEFAULT_PROJECT_ROOT);

  const d = layout.detection;
  if (d && d.found) {
    set("comsolVersion", d.version);
    set("comsolInstallRoot", d.installRoot);
    set("minVersion", d.minVersion);
    if (d.python) {
      set("mphVersion", d.python.mphVersion);
      set("pythonVersion", d.python.version);
    }
  }
  return { cfg, changed };
}

export function ensureConfig(layout) {
  const { cfg, changed } = computeConfig(layout);
  if (changed) writeConfig(cfg);
  return cfg;
}

export function resolveLayout(overrides = {}) {
  const cfg = readConfig();
  const detection = overrides.detection || detectComsol();

  const python =
    overrides.python ||
    (detection && detection.python && detection.python.path) ||
    (cfg.python && exists(cfg.python) ? cfg.python : null) ||
    ((findMphPython({ cfg }) || {}).path ?? null) ||
    "python";

  const workDir = path.resolve(
    overrides.workDir || process.env.COMSOL_MCP_WORKDIR || cfg.workDir || defaultWorkDir(),
  );

  return {
    workDir,
    detection,
    python,
    comsolExe: overrides.comsolExe || (detection && detection.comsolExe) || findComsolExe(),
    mphserverExe: overrides.mphserverExe || (detection && detection.mphserverExe) || null,
    batchExe: overrides.batchExe || (detection && detection.batchExe) || null,
    port: overrides.port || cfg.port || DEFAULT_PORT,
    mode: overrides.mode || cfg.mode || DEFAULT_MODE,
    serverScript: path.join(PKG_ROOT, "mcp-server", "server.py"),
    skillSrc: path.join(PKG_ROOT, "skills", "comsol"),
    skillDest: path.join(DSH_HOME, "skills", "comsol"),
    configFile: CONFIG_FILE,
    cfg,
  };
}
