# Third-party notices

`dsh-comsol` is MIT licensed (see `LICENSE`).

## Design reference

The bundle shell (manifest, cordis patch, `lib/detect.mjs`, `lib/paths.mjs`,
`lib/index.js`, `bin/` CLI, skill installation) follows the structure of
**dsh-abaqus-cad** v0.4.0 by Polymerizedcat (MIT licensed):

- https://github.com/Polymerizedcat/dsh-abaqus-cad

Its copyright notice remains with its author. `dsh-comsol` is an independent
implementation for COMSOL Multiphysics: no Abaqus bridge code, CAE plugin loader
or Abaqus-specific logic is included here. COMSOL has no in-CAE plugin mechanism,
so the whole GUI-bridge layer of the reference project is absent by design — the
MCP server drives COMSOL out of process through MPh.

## MPh

The MCP server drives COMSOL through **MPh** (`mph`), an MIT-licensed Python
package by John Hennig:

- https://github.com/MPh-py/MPh

MPh and its dependency **JPype** are installed in the user's own virtual
environment; neither is vendored or redistributed here. `dsh-comsol` only
requires that `import mph` and `import jpype` work in the interpreter it is
configured to launch (`COMSOL_MCP_PYTHON` / `~/.dsh/comsol.json` → `python`).

## COMSOL Multiphysics

COMSOL Multiphysics is a commercial product and a trademark of COMSOL AB.
This repository contains **no COMSOL code, no COMSOL installation files and no
licence material**. It only locates an installation the user has already
licensed and launches its executables (`comsol.exe`, `comsolmphserver.exe`,
`comsolbatch.exe`) on the user's behalf. A valid COMSOL licence is required to
do anything with this plugin.

## DSH

DeepSeek Harness (`@deepseek-ai/dsh-mcp-client`) is the host runtime and is a
peer dependency, not bundled.
