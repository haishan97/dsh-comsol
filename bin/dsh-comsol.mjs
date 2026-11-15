#!/usr/bin/env node
// Standalone diagnostics for dsh-comsol.
//
//   dsh-comsol doctor [--json]   detect COMSOL / version / exes / MPh python
//   dsh-comsol where             print resolved paths
//   dsh-comsol version           print package version
//
// `doctor` is safe to run before installing the dsh plugin: it only reads the
// filesystem and runs a tiny `import mph` probe in the candidate interpreters.
// It never starts COMSOL, never starts a solver and never solves a model.
import { detectComsol, probePython } from "../lib/detect.mjs";
import { CONFIG_FILE, DEFAULT_MODE, DEFAULT_PORT, PKG, PKG_ROOT, computeConfig, exists, readConfig, resolveLayout } from "../lib/paths.mjs";

const argv = process.argv.slice(2);
const command = argv[0] || "doctor";

function fmtVersion(v) {
  return v || "?";
}

function printDoctor(asJson) {
  const d = detectComsol();
  const layout = resolveLayout({ detection: d });
  const cfgOnDisk = readConfig();
  const { cfg, changed } = computeConfig(layout);
  const py = d.python;

  if (asJson) {
    process.stdout.write(
      JSON.stringify(
        {
          package: { name: PKG.name, version: PKG.version, root: PKG_ROOT },
          detection: d,
          layout: {
            workDir: layout.workDir,
            python: layout.python,
            comsolExe: layout.comsolExe,
            mphserverExe: layout.mphserverExe,
            batchExe: layout.batchExe,
            port: layout.port,
            mode: layout.mode,
            serverScript: layout.serverScript,
            serverPresent: exists(layout.serverScript),
            skillSrc: layout.skillSrc,
            skillDest: layout.skillDest,
          },
          config: { file: CONFIG_FILE, exists: exists(CONFIG_FILE), values: cfg, wouldWrite: changed },
        },
        null,
        2,
      ) + "\n",
    );
  } else {
    console.log(`dsh-comsol ${PKG.version}`);
    console.log(`COMSOL found : ${d.found ? "yes" : "NO"}`);
    console.log(`Version      : ${fmtVersion(d.version)} (requires ${d.minVersion}+)`);
    console.log(`Supported    : ${d.supported ? "yes" : "NO"}`);
    if (d.reason) console.log(`Reason       : ${d.reason}`);
    console.log(`Install root : ${d.installRoot || "?"}`);
    console.log(`comsol.exe   : ${d.comsolExe || "MISSING"}`);
    console.log(`mphserver    : ${d.mphserverExe || "MISSING"}`);
    console.log(`comsolbatch  : ${d.batchExe || "MISSING"}`);
    if (py) {
      console.log(`MPh python   : ${py.version || "?"} (${py.path})`);
      console.log(`MPh import   : OK - mph ${py.mphVersion || "?"}, jpype ${py.jpype || "?"} [${py.source}]`);
    } else {
      console.log(`MPh python   : NOT FOUND (need a venv where "import mph" works)`);
      console.log(`MPh import   : FAILED`);
    }
    if (d.installations.length > 1) {
      console.log(
        `Installations: ${d.installations.map((i) => `${i.version || "?"} (${i.installRoot})`).join(", ")}`,
      );
    }
    console.log(`Work dir     : ${layout.workDir}`);
    console.log(`Port / mode  : ${layout.port} / ${layout.mode}`);
    console.log(`MCP server   : ${layout.serverScript}${exists(layout.serverScript) ? "" : "  (MISSING)"}`);
    console.log(`Skill        : ${layout.skillSrc} -> ${layout.skillDest}`);
    console.log(`Config       : ${CONFIG_FILE}${exists(CONFIG_FILE) ? "" : "  (not written yet)"}`);
    console.log(
      `Config state : workDir=${cfg.workDir || "?"} python=${cfg.python ? "set" : "?"} ` +
        `port=${cfg.port || DEFAULT_PORT} mode=${cfg.mode || DEFAULT_MODE}` +
        (changed ? "  (defaults, would be written on first load)" : "  (up to date)"),
    );
    if (cfgOnDisk.comsolVersion && cfgOnDisk.comsolVersion !== d.version) {
      console.log(`Config drift : file says COMSOL ${cfgOnDisk.comsolVersion}, detected ${d.version}`);
    }
  }
  process.exitCode = d.found && d.supported && py ? 0 : 1;
}

if (command === "doctor") {
  printDoctor(argv.includes("--json"));
} else if (command === "where") {
  const d = detectComsol();
  const layout = resolveLayout({ detection: d });
  console.log(
    JSON.stringify(
      {
        package: { name: PKG.name, version: PKG.version, root: PKG_ROOT },
        comsol: layout.comsolExe,
        mphserver: layout.mphserverExe,
        batch: layout.batchExe,
        python: layout.python,
        workDir: layout.workDir,
        port: layout.port,
        mode: layout.mode,
        server: layout.serverScript,
        serverPresent: exists(layout.serverScript),
        skill: { src: layout.skillSrc, dest: layout.skillDest },
        config: CONFIG_FILE,
        configPresent: exists(CONFIG_FILE),
        detected: {
          version: d.version,
          supported: d.supported,
          installRoot: d.installRoot,
          mph: d.python ? { version: d.python.version, mph: d.python.mphVersion } : null,
        },
      },
      null,
      2,
    ),
  );
} else if (command === "version") {
  console.log(PKG.version);
} else if (command === "check-python") {
  // Debug helper: probe one interpreter for mph/jpype.
  const exe = argv[1];
  if (!exe) {
    console.error("usage: dsh-comsol check-python <path-to-python.exe>");
    process.exitCode = 2;
  } else {
    const res = probePython(exe);
    if (!res) {
      console.error(`not a runnable interpreter: ${exe}`);
      process.exitCode = 1;
    } else {
      console.log(JSON.stringify(res, null, 2));
      process.exitCode = res.mph ? 0 : 1;
    }
  }
} else if (command === "help" || command === "--help" || command === "-h") {
  console.log(`dsh-comsol ${PKG.version}

  doctor [--json]      detect COMSOL / version / exes / MPh python (exit 1 if unusable)
  where                print resolved paths
  check-python <exe>   probe one interpreter for mph + jpype
  version              print package version

Environment:
  COMSOL_HOME              COMSOL installation root (…\\COMSOL64\\Multiphysics)
  COMSOL_EXE               explicit comsol.exe path
  COMSOL_MPHSERVER_EXE     explicit comsolmphserver.exe path
  COMSOL_MCP_PYTHON        python.exe of the venv that has MPh installed
  COMSOL_MCP_WORKDIR       default work directory for .mph files
  COMSOL_MCP_PORT          COMSOL server port (default ${DEFAULT_PORT})
  COMSOL_MIN_VERSION       minimum accepted version (default 6.4)
  COMSOL_ALLOW_UNSUPPORTED=1  load the plugin below the baseline (experiments)
  DSH_HOME                 dsh home (default ~/.dsh)
`);
} else {
  console.error(`unknown command: ${command}`);
  process.exitCode = 2;
}
