// dsh-comsol entry point.
//
// A real cordis plugin: dsh imports this module by package name, so nothing has
// to be on PATH. On load it resolves the local COMSOL Multiphysics installation
// and the MPh interpreter, writes the default config (~/.dsh/comsol.json),
// installs the comsol skill into ~/.dsh/skills, and registers one stdio MCP
// server.
//
// COMSOL is driven out of process (MPh -> JPype -> comsolmphserver.exe), so
// there is no "in-CAE plugin" to install here: the MCP server process itself is
// the bridge, and it must be launched with the MPh interpreter (layout.python).
//
// The MCP server advertises only search_tools + call_tool. The full tool
// catalogue is searched on demand, so an idle session pays a few hundred tokens
// instead of the whole schema set.
import fs from "node:fs";
import path from "node:path";

import * as McpClient from "@deepseek-ai/dsh-mcp-client";

import { CONFIG_FILE, ensureConfig, exists, resolveLayout } from "./paths.mjs";
import { detectComsol } from "./detect.mjs";

export const name = "dsh-comsol";
export const inject = McpClient.inject;

const LOG = "[dsh-comsol]";

function say(msg) {
  process.stderr.write(`${LOG} ${msg}\n`);
}

// skills/comsol -> <DSH_HOME>/skills/comsol, so dsh can load the skill even when
// the bundle is installed read-only under node_modules.
function installSkill(layout) {
  const src = path.join(layout.skillSrc, "SKILL.md");
  if (!exists(src)) return false;
  try {
    fs.mkdirSync(layout.skillDest, { recursive: true });
    fs.cpSync(layout.skillSrc, layout.skillDest, { recursive: true, force: true });
    return true;
  } catch (err) {
    say(`could not install the comsol skill: ${err.message}`);
    return false;
  }
}

function serverConfig(layout) {
  const detection = layout.detection || {};
  return {
    serverName: "comsol",
    transport: "stdio",
    // Not a bare stdlib python: this interpreter must have mph + jpype.
    command: layout.python,
    args: [layout.serverScript],
    env: {
      COMSOL_MCP_WORKDIR: layout.workDir,
      COMSOL_EXE: layout.comsolExe || "",
      COMSOL_MPHSERVER_EXE: layout.mphserverExe || "",
      COMSOL_BATCH_EXE: layout.batchExe || "",
      COMSOL_VERSION: String(detection.version || ""),
      COMSOL_MIN_VERSION: String(detection.minVersion || ""),
      COMSOL_MCP_PORT: String(layout.port || ""),
      COMSOL_MCP_MODE: String(layout.mode || ""),
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      PYTHONUNBUFFERED: "1",
    },
    // A transient arc/CFD solve or a parameter sweep can run for hours; the
    // default 60 s tool timeout would kill the connection mid-solve.
    toolCallTimeoutMs: 1800000,
    failOnStartupError: true,
    reconnect: { enabled: true, initialDelayMs: 1000, maxDelayMs: 60000, maxAttempts: 8 },
  };
}

export function apply(ctx) {
  if (process.platform !== "win32") {
    throw new Error(`${LOG} COMSOL Multiphysics automation only runs on Windows.`);
  }

  const detection = detectComsol();
  if (!detection.found) {
    throw new Error(
      `${LOG} COMSOL Multiphysics was not found on this machine.\n` +
        `Install COMSOL 6.4, or set COMSOL_HOME / COMSOL_EXE to the installation.\n` +
        `Run "node bin/dsh-comsol.mjs doctor" for details.`,
    );
  }
  if (!detection.comsolExe) {
    throw new Error(
      `${LOG} found COMSOL ${detection.version || "?"} at ${detection.installRoot || "?"} ` +
        `but bin\\win64\\comsol.exe is missing.\n` +
        `Run "node bin/dsh-comsol.mjs doctor" for details.`,
    );
  }
  if (!detection.supported && process.env.COMSOL_ALLOW_UNSUPPORTED !== "1") {
    throw new Error(
      `${LOG} unsupported COMSOL ${detection.version || "?"}: this bundle requires ` +
        `${detection.minVersion}+ (MPh / Java API baseline).\n` +
        `Set COMSOL_ALLOW_UNSUPPORTED=1 only for experiments; features may break.`,
    );
  }
  if (!detection.python) {
    throw new Error(
      `${LOG} no Python interpreter with the MPh package was found.\n` +
        `The MCP server drives COMSOL through MPh (JPype -> comsolmphserver), so it must run ` +
        `under a venv that has "import mph" working.\n` +
        `Set COMSOL_MCP_PYTHON to that python.exe (e.g. ` +
        `E:\\ICE\\_tools\\COMSOL_Multiphysics_MCP\\.venv\\Scripts\\python.exe).\n` +
        `Run "node bin/dsh-comsol.mjs doctor" for details.`,
    );
  }

  const layout = resolveLayout({ detection });

  if (!exists(layout.serverScript)) {
    throw new Error(`${LOG} MCP server is missing at ${layout.serverScript}`);
  }
  say(
    `COMSOL ${detection.version || "?"} detected ` +
      `(root ${detection.installRoot || "?"}, ` +
      `mphserver ${detection.mphserverExe ? "yes" : "no"}, ` +
      `MPh python ${detection.python.version || "?"} / mph ${detection.python.mphVersion || "?"})`,
  );

  const cfg = ensureConfig(layout);
  const skill = installSkill(layout);

  ctx.plugin(McpClient, serverConfig(layout));

  say(
    `registered comsol (python ${path.basename(layout.python)}, work ${cfg.workDir}, ` +
      `mode ${cfg.mode}, port ${cfg.port}, config ${CONFIG_FILE}, ` +
      `skill ${skill ? "installed" : "missing"}`,
  );
}
