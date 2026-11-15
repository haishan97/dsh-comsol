# -*- coding: utf-8 -*-
"""extra_tools.py — the COMSOL 6.4 model-operation groups the inherited 157 tools never exposed.

WHY THIS FILE EXISTS
--------------------
``handlers.py`` reuses 157 tools that already live in
``E:/ICE/_tools/COMSOL_Multiphysics_MCP/src/tools/``.  A live gap analysis of
that surface found five COMSOL model operations with **no reachable tool at
all**, plus one that is license-gated:

1. **Named selection sets** (``model.component(<c>).selection()``) — only two
   *geometry-level* box-selection helpers existed.  A model in real use has 13
   named selections and none of them could be listed, read, edited or deleted.
2. **Component variables** (``model.component(<c>).variable()``) — absent.
3. **Probes** (``model.probe()``) — absent.
4. **Export nodes** (``model.result().export()``) — only two thin wrappers
   (``results_export_data`` / ``results_export_image``) that cannot create,
   configure or delete a node.
5. **Plot groups** (``model.result()`` plot groups) — only ``results_plots_list``.
6. Optimization (``model.opt()``) — **not implemented here**, see the note at
   the bottom of this docstring.

This module implements (1)–(5) natively against the same MPh/JPype handle the
other tools use (``session_manager.get_model(name).java``), and is registered
into the shared ``FastMCP`` by ``handlers._build_registry`` through
``register_extra_tools(mcp)`` — the same ``register_*(mcp)`` signature
convention every ``src/tools/*.py`` module uses.

API FACTS VERIFIED LIVE (COMSOL 6.4 / MPh 1.4 / JPype 1.7, this machine)
-----------------------------------------------------------------------
The task brief carried several API facts that turned out to be **wrong** on
6.4.  These are the measured ones; do not "fix" them back:

* **Selection dimension.** ``model.selection(<tag>).set("entitydim", ...)``
  only exists on *geometric* selection types (Box/Ball/Cylinder/Disk/...).
  ``Explicit`` selections have **no** ``entitydim`` property at all —
  ``properties()`` returns only ``groupcontang/angletol/color/customcolor``.
  The universal call is ``sel.geom(<gtag>, dim)``; this module uses it first
  and falls back to ``set("entitydim", JInt(dim))`` for geometric types.
* **Selection types.** Valid: ``Explicit, Union, Intersection, Difference,
  Complement, Adjacent, Ball, Box, Cylinder, Disk, LogicalExpression``.
  ``"Cumulative"`` is **not** a valid type on 6.4 (COMSOL raises
  ``FlException: unknown selection type``); the GUI's "cumulative selection"
  is a geometry-sequence property, not a ``selection()`` type.
* **Component variables are not auto-created.** ``comp.variable("var1")``
  raises ``FlException: unknown variable tag``; you must
  ``comp.variable().create("var1")`` first (that call takes only the tag).
* **Probe types.** Valid: ``Boundary, Domain, Edge, Point, GlobalVariable``,
  plus the point-probe containers ``BoundaryPoint`` and ``DomainPoint``.
  ``"Global"`` is **invalid** (``cannot create a global probe in this
  scenario``); a global probe is ``"GlobalVariable"``.
* **Probe coordinates are ``coords`` (plural), as a double matrix**
  (``set("coords", double[][]{{x,y,z}})``), and only on
  ``DomainPoint``/``BoundaryPoint``.  There is no ``coord`` property, and the
  ``points`` property is something else entirely (the max/min evaluation
  method: ``node | integration | lagrange``).
* **Point-probe expressions are sub-features.** ``DomainPoint``/``BoundaryPoint``
  have no ``expr`` property; the expression lives in a ``PointExpr`` child
  (``probe(<t>).create("expr1","PointExpr")`` then
  ``feature("expr1").set("expr", ...)``).  Plain ``Domain``/``Boundary``/
  ``Edge``/``Point``/``GlobalVariable`` probes do take ``expr`` directly.
* **Probe values have no ``getValues()``.** Evaluation is
  ``probe(tag).genResult(<soltag>)``, which materialises a numerical result
  feature (e.g. ``pev1``); read it with
  ``model.result().numerical(<that tag>).getReal()``.  ``genResult(None)`` is
  accepted and uses the default solver sequence.
* **Bare Python ints break the overloaded setters.** Every entity number /
  dimension is wrapped in ``jpype.JInt`` (the trap that cost real debugging
  time in this codebase).
* **``model.result().tags()`` is not "plot groups".** It also lists numerical
  and export features, so ``plot_list`` filters with ``isPlotGroup()``.
* **Image export bound to a plot group** uses the three-argument overload
  ``model.result().export().create(<etag>, <pgtag>, "Image")``.  Its
  ``width``/``height`` are **unit strings**, not pixels: the default
  ``size="manualprint"`` preset reads them as cm, so ``640`` means *640 cm*
  and COMSOL answers "width must not exceed 4096 px".  ``size="manualweb"``
  is the pixel preset — that is what ``plot_export`` sets before writing
  ``width``/``height``.

Every tool returns a compact JSON-able dict and **never lets a raw exception
escape** — failures come back as ``{"success": False, "error": ...}`` so the
MCP layer reports them as data instead of killing the dispatch loop.

NOT IMPLEMENTED — OPTIMIZATION (``model.opt()``)
------------------------------------------------
The Optimization Module *is* licensed on this machine (``OPTIMIZATION`` is in
``license/license.dat``) and the 6.4 API is
``model.opt().objective().create(<tag>, "Global"|"LeastSquares")`` /
``model.opt().constr().create(<tag>)`` / ``model.opt().gconstr().create(<tag>)``.
It is deliberately left out: every meaningful check of it needs a *solve*
(objectives and constraints are only interpreted by the optimization solver),
which is out of scope for this change and cannot be verified here.  Adding
unverifiable tools would be worse than omitting them; the three calls above are
the exact entry points for a follow-up.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

try:  # JPype is present in the MPh venv; keep the module importable without it.
    import jpype
except Exception:  # pragma: no cover - env problem only
    jpype = None  # type: ignore[assignment]

LOG = logging.getLogger("dsh_comsol.extra_tools")
LOG.addHandler(logging.NullHandler())

__all__ = ["register_extra_tools", "EXTRA_TOOL_NAMES", "TOOL_GROUPS"]

#: The 22 tools this module registers (used by handlers for accounting/reporting).
EXTRA_TOOL_NAMES: tuple[str, ...] = (
    # selections
    "selection_create",
    "selection_list",
    "selection_info",
    "selection_set_entities",
    "selection_delete",
    # component variables
    "variable_create",
    "variable_list",
    "variable_set",
    "variable_delete",
    # probes
    "probe_create",
    "probe_list",
    "probe_evaluate",
    "probe_delete",
    # export nodes
    "export_create",
    "export_list",
    "export_set",
    "export_run",
    "export_delete",
    # plot groups
    "plot_create",
    "plot_set",
    "plot_delete",
    "plot_export",
)

TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "selection": EXTRA_TOOL_NAMES[0:5],
    "variable": EXTRA_TOOL_NAMES[5:9],
    "probe": EXTRA_TOOL_NAMES[9:13],
    "export": EXTRA_TOOL_NAMES[13:18],
    "plot": EXTRA_TOOL_NAMES[18:22],
}

#: Selection types COMSOL 6.4 actually accepts (see module docstring).
SELECTION_TYPES: tuple[str, ...] = (
    "Explicit",
    "Union",
    "Intersection",
    "Difference",
    "Complement",
    "Adjacent",
    "Ball",
    "Box",
    "Cylinder",
    "Disk",
    "LogicalExpression",
)

#: Probe types COMSOL 6.4 actually accepts.
PROBE_TYPES: tuple[str, ...] = (
    "Boundary",
    "Domain",
    "Edge",
    "Point",
    "GlobalVariable",
    "BoundaryPoint",
    "DomainPoint",
)

#: Probe types whose expression lives in a ``PointExpr`` child feature.
POINT_PROBE_TYPES: tuple[str, ...] = ("BoundaryPoint", "DomainPoint")

#: Plot group types accepted by ``model.result().create(<tag>, <type>)``.
PLOT_GROUP_TYPES: tuple[str, ...] = (
    "PlotGroup1D",
    "PlotGroup2D",
    "PlotGroup3D",
    "PolarGroup",
    "SmithGroup",
)

#: Export node types accepted by ``model.result().export().create(...)``.
EXPORT_TYPES: tuple[str, ...] = ("Data", "Image", "Animation", "Table", "Mesh", "Plot")


# --------------------------------------------------------------------------- #
# Small helpers — no COMSOL logic, only handle/typing plumbing
# --------------------------------------------------------------------------- #


def _ok(**payload: Any) -> dict:
    """Successful tool result."""
    result: dict[str, Any] = {"success": True}
    result.update(payload)
    return result


def _err(message: str, **payload: Any) -> dict:
    """Failed tool result — always a dict, never an exception."""
    result: dict[str, Any] = {"success": False, "error": str(message)}
    result.update(payload)
    return result


def _require_jpype() -> None:
    if jpype is None:  # pragma: no cover - env problem only
        raise RuntimeError(
            "jpype is not importable; run under the MPh venv python "
            "(E:/ICE/_tools/COMSOL_Multiphysics_MCP/.venv/Scripts/python.exe)"
        )


def _jint(value: Any) -> Any:
    """Wrap a Python int so JPype picks the int overload (never the double one)."""
    _require_jpype()
    return jpype.JInt(int(value))


def _jints(values: Any) -> Any:
    """Wrap a sequence of entity numbers as ``int[]`` (JInt each — see docstring)."""
    _require_jpype()
    return [jpype.JInt(int(v)) for v in values]


def _jdouble_matrix(points: Any) -> Any:
    """Wrap ``[[x,y,z], ...]`` as ``double[][]`` (the ``coords`` property type)."""
    _require_jpype()
    rows = [[float(v) for v in row] for row in points]
    return jpype.JArray(jpype.JDouble, 2)(rows)


def _as_point_matrix(coords: Any) -> list:
    """Normalise ``[x,y,z]`` or ``[[x,y,z], ...]`` into a list of points."""
    seq = list(coords)
    if not seq:
        raise ValueError("coords must not be empty")
    if not isinstance(seq[0], (list, tuple)):
        seq = [seq]
    return [[float(v) for v in row] for row in seq]


def _ints(value: Any) -> list:
    """Convert a Java ``int[]`` (or any sequence) into a plain Python int list."""
    try:
        return [int(v) for v in value]
    except TypeError:
        return []


def _doubles(value: Any) -> list:
    """Convert a Java ``double[]`` into a plain Python float list."""
    try:
        return [float(v) for v in value]
    except TypeError:
        return []


def _coerce(value: Any) -> Any:
    """Coerce a JSON value into something a COMSOL ``set`` overload accepts.

    COMSOL lists on/off flags as strings in its own reference, so a Python
    bool becomes ``"on"``/``"off"``; ints/floats are wrapped so the overloaded
    setters resolve predictably; lists become typed Java arrays.
    """
    if jpype is None:  # pragma: no cover
        return value
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, int):
        return jpype.JInt(value)
    if isinstance(value, float):
        return jpype.JDouble(value)
    if isinstance(value, (list, tuple)):
        items = list(value)
        if items and all(isinstance(v, bool) for v in items):
            return jpype.JArray(jpype.JBoolean)(items)
        if items and all(isinstance(v, int) and not isinstance(v, bool) for v in items):
            return jpype.JArray(jpype.JInt)([int(v) for v in items])
        if items and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in items):
            return jpype.JArray(jpype.JDouble)([float(v) for v in items])
        return jpype.JArray(jpype.JString)([str(v) for v in items])
    return value


def _coercion_candidates(value: Any) -> list:
    """Return increasingly permissive JPype coercions for one property value.

    COMSOL's ``ResultsFeature.set()`` is overloaded (int / double / String /
    array) and JPype resolves the overload from the Python type.  A wrong pick
    does not raise a type error - COMSOL reports "未知属性" (unknown property)
    instead, which looks like a bad property *name*.  Arrow/volume features hit
    exactly this: ``xnumber`` / ``ynumber`` / ``znumber`` / ``scale`` are only
    accepted through the numeric overloads, so a bare Python int arrives as a
    String and the property is rejected.

    Trying the coercions in order makes those properties settable while keeping
    the first-choice behaviour for everything that already worked.
    (2026-11-15: verified needed for ``ArrowVolume`` arrow-density properties.)
    """
    if jpype is None:  # pragma: no cover
        return [value]
    if isinstance(value, bool):
        return ["on" if value else "off", bool(value)]
    if isinstance(value, int):
        return [jpype.JInt(value), jpype.JDouble(float(value)), str(value)]
    if isinstance(value, float):
        return [jpype.JDouble(value), str(value)]
    if isinstance(value, (list, tuple)):
        out = [_coerce(value)]
        items = list(value)
        if items and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in items
        ):
            out.append(jpype.JArray(jpype.JDouble)([float(v) for v in items]))
        return out
    return [value]


def _set_properties(node: Any, properties: Optional[dict]) -> list:
    """Apply a ``{property: value}`` dict; returns ``[{property, error}]`` failures.

    Rejected properties are reported, never silently swallowed (a silently
    ignored property is the classic way to "configure" a node that does
    nothing).  Each value is retried with alternative JPype coercions, because
    COMSOL reports a bad overload as an unknown property name.
    """
    failures: list[dict] = []
    if not properties:
        return failures
    for key, value in properties.items():
        key = str(key)
        last_error: Optional[Exception] = None
        accepted = False
        for candidate in _coercion_candidates(value):
            try:
                node.set(key, candidate)
                accepted = True
                break
            except Exception as exc:  # try the next coercion
                last_error = exc
        if not accepted and last_error is not None:
            failures.append(
                {
                    "property": key,
                    "error": "%s: %s" % (type(last_error).__name__, last_error),
                }
            )
    return failures


def _read_string(node: Any, prop: str) -> Optional[str]:
    """Read a string property, returning ``None`` when it is not readable."""
    for getter in ("getString", "get"):
        fn = getattr(node, getter, None)
        if fn is None:
            continue
        try:
            value = fn(prop)
        except Exception:
            continue
        if value is None:
            continue
        try:
            return str(value)
        except Exception:
            continue
    return None


def _model_label(model: Any) -> str:
    """Model name as a plain string (``Model.name`` is a *method* in MPh)."""
    try:
        name = model.name
        if callable(name):
            name = name()
        return str(name or "")
    except Exception:
        return ""


def _absolute_filename(filename: str) -> str:
    """Make a bare filename absolute.

    COMSOL's image exporter tries to create the containing directory and fails
    on an empty one (``cannot create directory``), so ``"out.png"`` must become
    a real path.  Explicit paths (with a directory part) are left untouched.
    """
    text = str(filename)
    if not os.path.dirname(text):
        return os.path.abspath(text)
    return text


def _session_manager() -> Any:
    """The live-session singleton owned by ``src.tools.session``."""
    from src.tools.session import session_manager

    return session_manager


def _model(model_name: Optional[str]) -> Any:
    """Resolve ``model_name`` (or the current model) to an MPh ``Model``."""
    manager = _session_manager()
    model = manager.get_model(model_name)
    if model is None:
        raise RuntimeError(
            "Model not found: %s (start COMSOL with comsol_start / load one with model_load)"
            % (model_name or "no current model")
        )
    return model


def _component(model: Any, component_name: Optional[str]) -> Any:
    """Return the Java component node, or raise a readable error."""
    name = component_name or "comp1"
    try:
        comp = model.java.component(name)
    except Exception as exc:
        raise RuntimeError("Component %r not found (%s)" % (name, exc)) from exc
    if comp is None:
        raise RuntimeError("Component %r not found" % name)
    return comp


def _default_geometry(comp: Any) -> str:
    """First geometry tag of a component (falls back to ``geom1``)."""
    try:
        tags = [str(t) for t in comp.geom().tags()]
        if tags:
            return tags[0]
    except Exception:
        pass
    return "geom1"


def _existing_selection(comp: Any, tag: str) -> Any:
    """Return a selection node or raise a readable error."""
    try:
        sel = comp.selection(tag)
    except Exception as exc:
        raise RuntimeError("Selection %r not found (%s)" % (tag, exc)) from exc
    if sel is None:
        raise RuntimeError("Selection %r not found" % tag)
    return sel


def _apply_dimension(sel: Any, geometry: str, entity_dim: int) -> Optional[str]:
    """Set a selection's geometry + entity dimension.

    ``sel.geom(<gtag>, dim)`` is the documented universal call; geometric
    selection types additionally expose ``entitydim``.  Returns a warning
    string when neither worked.
    """
    try:
        sel.geom(geometry, _jint(entity_dim))
        return None
    except Exception:
        pass
    try:
        sel.set("entitydim", _jint(entity_dim))
        return None
    except Exception as exc:
        return "could not set entity dimension: %s: %s" % (type(exc).__name__, exc)


def _selection_type(sel: Any) -> Optional[str]:
    try:
        return str(sel.getType())
    except Exception:
        return None


def _selection_dim(sel: Any) -> Optional[int]:
    for getter in ("dim", "inputDimension"):
        fn = getattr(sel, getter, None)
        if fn is None:
            continue
        try:
            return int(fn())
        except Exception:
            continue
    return None


def _entities_of(node: Any) -> list:
    try:
        return _ints(node.entities())
    except Exception:
        return []


def _probe_expr(probe: Any) -> Optional[str]:
    """Expression of a probe, transparently following a ``PointExpr`` child."""
    expr = _read_string(probe, "expr")
    if expr is not None:
        return expr
    try:
        feature_tags = [str(t) for t in probe.feature().tags()]
    except Exception:
        return None
    for tag in feature_tags:
        try:
            child = probe.feature(tag)
        except Exception:
            continue
        child_expr = _read_string(child, "expr")
        if child_expr is not None:
            return child_expr
    return None


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def register_extra_tools(mcp: Any) -> None:
    """Register the five missing COMSOL 6.4 model-operation groups.

    Signature contract: exactly one positional parameter named ``mcp``, so
    ``handlers._registration_functions`` recognises it like any
    ``register_*_tools(mcp)`` in ``src/tools/``.
    """

    # ------------------------------------------------------------------ #
    # 1. Named selection sets
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def selection_create(
        tag: str,
        selection_type: str = "Explicit",
        geometry: str = "",
        entity_dim: int = 3,
        entities: Optional[list] = None,
        all_entities: bool = False,
        properties: Optional[dict] = None,
        label: Optional[str] = None,
        component_name: str = "comp1",
        model_name: Optional[str] = None,
    ) -> dict:
        """新建命名选择集（selection set）—— Explicit / Box / Ball / Cylinder / Union / Intersection / Difference / Complement / Adjacent / Disk / LogicalExpression。

        参数：
            tag: 选择集标签（后续物理场/变量用 selection().named(tag) 引用）
            selection_type: 选择类型，默认 Explicit（显式实体列表）
            geometry: 几何标签，留空自动取该组件第一个几何
            entity_dim: 实体维度 3=域 2=边界 1=边 0=点
            entities: 实体编号列表（Explicit 用；数字用 JInt 包装后传入）
            all_entities: 直接选中该维度全部实体（等价 GUI 的"全选"）
            properties: 其它属性，如 Box 的 {xmin,xmax,ymin,ymax,zmin,zmax,condition}
            label: 显示名
            component_name / model_name: 组件名 / 模型名（默认当前模型）

        返回：{success, tag, type, entity_dim, entities, warnings}
        """
        try:
            model = _model(model_name)
            comp = _component(model, component_name)
            geom = geometry or _default_geometry(comp)
            sel = comp.selection().create(tag, selection_type)
            warnings: list[str] = []
            warning = _apply_dimension(sel, geom, int(entity_dim))
            if warning:
                warnings.append(warning)
            if all_entities:
                sel.all()
            if entities:
                sel.set(_jints(entities))
            failures = _set_properties(sel, properties)
            if failures:
                warnings.extend(
                    "property %s rejected: %s" % (f["property"], f["error"]) for f in failures
                )
            if label:
                sel.label(label)
            return _ok(
                tag=str(tag),
                type=_selection_type(sel) or selection_type,
                geometry=geom,
                entity_dim=int(entity_dim),
                entities=_entities_of(sel),
                warnings=warnings,
            )
        except Exception as exc:
            return _err(
                "Failed to create selection %r: %s" % (tag, exc),
                selection_type=selection_type,
                component=component_name,
            )

    @mcp.tool()
    def selection_list(
        component_name: str = "comp1",
        include_entities: bool = False,
        max_entities: int = 200,
        model_name: Optional[str] = None,
    ) -> dict:
        """列出模型中所有命名选择集（tag / 类型 / 维度 / 实体数），可选带实体编号。

        参数：
            component_name: 组件名
            include_entities: 是否同时返回每个选择的实体编号
            max_entities: 每个选择最多返回多少实体编号（超出标记 truncated）
            model_name: 模型名（默认当前模型）

        返回：{success, count, selections: [{tag,type,label,dim,entity_count,entities?}]}
        """
        try:
            model = _model(model_name)
            comp = _component(model, component_name)
            rows: list[dict] = []
            for raw_tag in comp.selection().tags():
                tag = str(raw_tag)
                row: dict[str, Any] = {"tag": tag}
                try:
                    sel = comp.selection(tag)
                except Exception as exc:
                    row["error"] = str(exc)
                    rows.append(row)
                    continue
                row["type"] = _selection_type(sel)
                row["dim"] = _selection_dim(sel)
                try:
                    row["label"] = str(sel.label())
                except Exception:
                    row["label"] = None
                ents = _entities_of(sel)
                row["entity_count"] = len(ents)
                if include_entities:
                    limit = max(0, int(max_entities))
                    row["entities"] = ents[:limit]
                    row["truncated"] = len(ents) > limit
                rows.append(row)
            return _ok(
                count=len(rows),
                selections=rows,
                component=component_name,
                model=_model_label(model),
            )
        except Exception as exc:
            return _err("Failed to list selections: %s" % exc, component=component_name)

    @mcp.tool()
    def selection_info(
        tag: str,
        component_name: str = "comp1",
        model_name: Optional[str] = None,
    ) -> dict:
        """读取单个命名选择集的详情：类型、维度、几何、实体编号、可设属性。

        参数：
            tag: 选择集标签
            component_name / model_name: 组件名 / 模型名

        返回：{success, tag, type, dim, geometry, label, entities, properties}
        """
        try:
            model = _model(model_name)
            comp = _component(model, component_name)
            sel = _existing_selection(comp, tag)
            info: dict[str, Any] = {
                "tag": str(tag),
                "type": _selection_type(sel),
                "dim": _selection_dim(sel),
                "entities": _entities_of(sel),
                "component": component_name,
            }
            for name, getter in (("label", "label"), ("geometry", "geom")):
                fn = getattr(sel, getter, None)
                if fn is None:
                    continue
                try:
                    info[name] = str(fn())
                except Exception:
                    info[name] = None
            try:
                info["properties"] = [str(p) for p in sel.properties()]
            except Exception:
                info["properties"] = []
            return _ok(**info)
        except Exception as exc:
            return _err("Failed to read selection %r: %s" % (tag, exc), tag=tag)

    @mcp.tool()
    def selection_set_entities(
        tag: str,
        entities: Optional[list] = None,
        all_entities: bool = False,
        mode: str = "set",
        component_name: str = "comp1",
        model_name: Optional[str] = None,
    ) -> dict:
        """修改已有命名选择集的实体：set 覆盖 / add 追加 / remove 移除 / clear 清空。

        参数：
            tag: 选择集标签
            entities: 实体编号列表（数字会用 JInt 包装，避免重载误判）
            all_entities: 选中该维度全部实体（mode=set 时）
            mode: set（默认）| add | remove | clear
            component_name / model_name: 组件名 / 模型名

        返回：{success, tag, mode, entities}
        """
        try:
            model = _model(model_name)
            comp = _component(model, component_name)
            sel = _existing_selection(comp, tag)
            action = (mode or "set").strip().lower()
            if action not in ("set", "add", "remove", "clear"):
                return _err(
                    "mode must be one of set|add|remove|clear, got %r" % mode, tag=tag
                )
            if action == "clear":
                sel.clear()
            elif all_entities and action == "set":
                sel.all()
            else:
                if not entities:
                    return _err("entities is required for mode=%s" % action, tag=tag)
                wrapped = _jints(entities)
                if action == "set":
                    sel.set(wrapped)
                elif action == "add":
                    sel.add(wrapped)
                else:
                    sel.remove(wrapped)
            return _ok(tag=str(tag), mode=action, entities=_entities_of(sel))
        except Exception as exc:
            return _err("Failed to update selection %r: %s" % (tag, exc), tag=tag)

    @mcp.tool()
    def selection_delete(
        tag: str,
        component_name: str = "comp1",
        model_name: Optional[str] = None,
    ) -> dict:
        """删除一个命名选择集（引用它的物理场/变量会失去选择，需自行修正）。

        参数：
            tag: 选择集标签
            component_name / model_name: 组件名 / 模型名

        返回：{success, deleted, remaining}
        """
        try:
            model = _model(model_name)
            comp = _component(model, component_name)
            comp.selection().remove(tag)
            remaining = [str(t) for t in comp.selection().tags()]
            return _ok(deleted=str(tag), remaining=remaining)
        except Exception as exc:
            return _err("Failed to delete selection %r: %s" % (tag, exc), tag=tag)

    # ------------------------------------------------------------------ #
    # 2. Component variables
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def variable_create(
        tag: str,
        expr: Optional[str] = None,
        unit: Optional[str] = None,
        descr: Optional[str] = None,
        selection: Optional[str] = None,
        label: Optional[str] = None,
        component_name: str = "comp1",
        model_name: Optional[str] = None,
    ) -> dict:
        """新建组件变量（component variable / 表达式定义）—— comp.variable().create(tag)。

        注意：COMSOL 不会用 comp.variable(tag) 自动创建，必须先 create。
        参数：
            tag: 变量标签
            expr: 表达式，如 "2*T" / "sqrt(u^2+v^2)" / "1[K]"
            unit: 单位，如 "K" / "m/s"（可留空）
            descr: 描述
            selection: 绑定到某个命名选择集标签（只在该选择上定义）
            label: 显示名
            component_name / model_name: 组件名 / 模型名

        返回：{success, tag, expr, unit, selection}
        """
        try:
            model = _model(model_name)
            comp = _component(model, component_name)
            node = comp.variable().create(tag)
            warnings: list[str] = []
            if expr is not None:
                node.set("expr", str(expr))
            if unit is not None:
                node.set("unit", str(unit))
            if descr is not None:
                node.set("descr", str(descr))
            if selection:
                try:
                    node.selection().named(str(selection))
                except Exception as exc:
                    warnings.append("selection %r rejected: %s" % (selection, exc))
            if label:
                node.label(str(label))
            return _ok(
                tag=str(tag),
                expr=expr,
                unit=unit,
                selection=selection,
                warnings=warnings,
            )
        except Exception as exc:
            return _err(
                "Failed to create variable %r: %s" % (tag, exc), component=component_name
            )

    @mcp.tool()
    def variable_list(
        component_name: str = "comp1",
        model_name: Optional[str] = None,
    ) -> dict:
        """列出组件变量（tag / 表达式 / 单位 / 描述）。

        参数：
            component_name / model_name: 组件名 / 模型名

        返回：{success, count, variables: [{tag,expr,unit,descr}]}
        """
        try:
            model = _model(model_name)
            comp = _component(model, component_name)
            rows: list[dict] = []
            for raw_tag in comp.variable().tags():
                tag = str(raw_tag)
                row: dict[str, Any] = {"tag": tag}
                try:
                    node = comp.variable(tag)
                except Exception as exc:
                    row["error"] = str(exc)
                    rows.append(row)
                    continue
                row["expr"] = _read_string(node, "expr")
                row["unit"] = _read_string(node, "unit")
                row["descr"] = _read_string(node, "descr")
                try:
                    row["label"] = str(node.label())
                except Exception:
                    row["label"] = None
                rows.append(row)
            return _ok(count=len(rows), variables=rows, component=component_name)
        except Exception as exc:
            return _err("Failed to list variables: %s" % exc, component=component_name)

    @mcp.tool()
    def variable_set(
        tag: str,
        expr: Optional[str] = None,
        unit: Optional[str] = None,
        descr: Optional[str] = None,
        selection: Optional[str] = None,
        label: Optional[str] = None,
        component_name: str = "comp1",
        model_name: Optional[str] = None,
    ) -> dict:
        """修改已有组件变量的表达式 / 单位 / 描述 / 绑定选择集。

        参数：
            tag: 变量标签（须已存在）
            expr / unit / descr: 要修改的属性（留空则不改）
            selection: 绑定到命名选择集标签
            label: 显示名
            component_name / model_name: 组件名 / 模型名

        返回：{success, tag, expr, unit}
        """
        try:
            model = _model(model_name)
            comp = _component(model, component_name)
            try:
                node = comp.variable(tag)
            except Exception as exc:
                return _err("Variable %r not found (%s)" % (tag, exc), tag=tag)
            if expr is not None:
                node.set("expr", str(expr))
            if unit is not None:
                node.set("unit", str(unit))
            if descr is not None:
                node.set("descr", str(descr))
            if selection:
                node.selection().named(str(selection))
            if label:
                node.label(str(label))
            return _ok(
                tag=str(tag),
                expr=_read_string(node, "expr"),
                unit=_read_string(node, "unit"),
                descr=_read_string(node, "descr"),
            )
        except Exception as exc:
            return _err("Failed to update variable %r: %s" % (tag, exc), tag=tag)

    @mcp.tool()
    def variable_delete(
        tag: str,
        component_name: str = "comp1",
        model_name: Optional[str] = None,
    ) -> dict:
        """删除一个组件变量。

        参数：
            tag: 变量标签
            component_name / model_name: 组件名 / 模型名

        返回：{success, deleted, remaining}
        """
        try:
            model = _model(model_name)
            comp = _component(model, component_name)
            comp.variable().remove(tag)
            return _ok(
                deleted=str(tag),
                remaining=[str(t) for t in comp.variable().tags()],
            )
        except Exception as exc:
            return _err("Failed to delete variable %r: %s" % (tag, exc), tag=tag)

    # ------------------------------------------------------------------ #
    # 3. Probes
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def probe_create(
        tag: str,
        probe_type: str = "DomainPoint",
        expr: Optional[str] = None,
        coords: Optional[list] = None,
        selection: Optional[str] = None,
        probename: Optional[str] = None,
        descr: Optional[str] = None,
        properties: Optional[dict] = None,
        component_name: str = "comp1",
        model_name: Optional[str] = None,
    ) -> dict:
        """新建探针（probe / 监测点）：DomainPoint / BoundaryPoint / Domain / Boundary / Edge / Point / GlobalVariable。

        实测要点（COMSOL 6.4）：
          * 全局探针的类型是 "GlobalVariable"（不是 "Global"）。
          * 坐标属性是 coords（复数，double 矩阵），且只有 DomainPoint / BoundaryPoint 有。
          * DomainPoint / BoundaryPoint 没有 expr 属性，表达式放在 PointExpr 子特征里（本工具自动建）。
        参数：
            tag: 探针标签
            probe_type: 探针类型
            expr: 被监测表达式，如 "comp1.T" / "maxop1(T)"
            coords: 点坐标 [[x,y,z], ...] 或 [x,y,z]
            selection: 绑定命名选择集（Domain/Boundary/Edge 探针用）
            probename: 全局探针的变量名（GlobalVariable 用）
            descr: 描述
            properties: 其它属性
            model_name: 模型名

        返回：{success, tag, type, expr, coords, point_expr_tag}
        """
        try:
            model = _model(model_name)
            probe = model.java.probe().create(tag, probe_type)
            warnings: list[str] = []
            point_expr_tag: Optional[str] = None
            if coords:
                probe.set("coords", _jdouble_matrix(_as_point_matrix(coords)))
            if expr is not None:
                if probe_type in POINT_PROBE_TYPES:
                    point_expr_tag = "%s_expr" % str(tag).replace("-", "_")
                    child = probe.create(point_expr_tag, "PointExpr")
                    child.set("expr", str(expr))
                else:
                    probe.set("expr", str(expr))
            if probename is not None:
                try:
                    probe.set("probename", str(probename))
                except Exception as exc:
                    warnings.append("probename rejected: %s" % exc)
            if descr is not None:
                probe.set("descr", str(descr))
            if selection:
                try:
                    # A probe must know its model component before it can
                    # resolve a named selection (COMSOL: "unsupported geometry"
                    # otherwise) — this is what probe.model(<ctag>) is for.
                    probe.model(component_name or "comp1")
                    probe.selection().named(str(selection))
                except Exception as exc:
                    warnings.append("selection %r rejected: %s" % (selection, exc))
            failures = _set_properties(probe, properties)
            if failures:
                warnings.extend(
                    "property %s rejected: %s" % (f["property"], f["error"]) for f in failures
                )
            read_coords = None
            try:
                matrix = probe.getDoubleMatrix("coords")
                read_coords = [[float(v) for v in row] for row in matrix]
            except Exception:
                read_coords = None
            return _ok(
                tag=str(tag),
                type=probe_type,
                expr=_probe_expr(probe),
                coords=read_coords,
                point_expr_tag=point_expr_tag,
                warnings=warnings,
            )
        except Exception as exc:
            return _err(
                "Failed to create probe %r: %s" % (tag, exc),
                probe_type=probe_type,
                hint="valid types: %s" % ", ".join(PROBE_TYPES),
            )

    @mcp.tool()
    def probe_list(model_name: Optional[str] = None) -> dict:
        """列出模型中的所有探针（tag / 类型 / 表达式 / 坐标 / 探针变量名）。

        参数：
            model_name: 模型名（默认当前模型）

        返回：{success, count, probes: [{tag,type,expr,coords,probename}]}
        """
        try:
            model = _model(model_name)
            probe_list_node = model.java.probe()
            rows: list[dict] = []
            for raw_tag in probe_list_node.tags():
                tag = str(raw_tag)
                row: dict[str, Any] = {"tag": tag}
                try:
                    probe = probe_list_node.get(tag)
                except Exception as exc:
                    row["error"] = str(exc)
                    rows.append(row)
                    continue
                try:
                    row["type"] = str(probe.getType())
                except Exception:
                    row["type"] = None
                row["expr"] = _probe_expr(probe)
                row["probename"] = _read_string(probe, "probename")
                try:
                    matrix = probe.getDoubleMatrix("coords")
                    row["coords"] = [[float(v) for v in r] for r in matrix]
                except Exception:
                    row["coords"] = None
                rows.append(row)
            return _ok(count=len(rows), probes=rows)
        except Exception as exc:
            return _err("Failed to list probes: %s" % exc)

    @mcp.tool()
    def probe_evaluate(
        tag: Optional[str] = None,
        sol: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """求探针值：probe.genResult(sol) 生成结果特征，再读 numerical(...).getReal()。

        注意：探针值来自求解结果，模型未求解时返回空数组（这是 COMSOL 的正常行为）。
        参数：
            tag: 探针标签；留空则评估全部探针
            sol: 求解序列标签（如 "sol1"），留空用默认求解序列
            model_name: 模型名

        返回：{success, values: {tag: [..]}, numerical_tags, note}
        """
        try:
            model = _model(model_name)
            probe_list_node = model.java.probe()
            numerical = model.java.result().numerical()
            targets = (
                [str(tag)]
                if tag
                else [str(t) for t in probe_list_node.tags()]
            )
            if not targets:
                return _err("No probes in the model; create one with probe_create")
            values: dict[str, list] = {}
            numerical_tags: list[str] = []
            for probe_tag in targets:
                try:
                    probe = probe_list_node.get(probe_tag)
                except Exception as exc:
                    values[probe_tag] = []
                    LOG.warning("probe_evaluate: cannot get probe %s: %s", probe_tag, exc)
                    continue
                before = {str(t) for t in numerical.tags()}
                try:
                    probe.genResult(sol if sol else None)
                except Exception as exc:
                    values[probe_tag] = []
                    LOG.warning("probe_evaluate: genResult(%s) failed: %s", probe_tag, exc)
                    continue
                after = [str(t) for t in numerical.tags()]
                created = [t for t in after if t not in before]
                numerical_tags.extend(created)
                collected: list[float] = []
                for num_tag in created:
                    try:
                        collected.extend(_doubles(numerical.get(num_tag).getReal()))
                    except Exception as exc:
                        LOG.warning(
                            "probe_evaluate: getReal(%s) failed: %s", num_tag, exc
                        )
                values[probe_tag] = collected
            return _ok(
                values=values,
                numerical_tags=numerical_tags,
                sol=sol,
                note=(
                    "empty arrays are expected when the model has no solved solution "
                    "(probe values are produced by the solver)"
                ),
            )
        except Exception as exc:
            return _err("Failed to evaluate probe(s): %s" % exc, tag=tag)

    @mcp.tool()
    def probe_delete(tag: str, model_name: Optional[str] = None) -> dict:
        """删除一个探针（同时移除它为结果带来的数值特征）。

        参数：
            tag: 探针标签
            model_name: 模型名

        返回：{success, deleted, remaining}
        """
        try:
            model = _model(model_name)
            probe_list_node = model.java.probe()
            probe_list_node.remove(tag)
            return _ok(
                deleted=str(tag),
                remaining=[str(t) for t in probe_list_node.tags()],
            )
        except Exception as exc:
            return _err("Failed to delete probe %r: %s" % (tag, exc), tag=tag)

    # ------------------------------------------------------------------ #
    # 4. Export nodes
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def export_create(
        tag: str,
        export_type: str = "Data",
        plotgroup: Optional[str] = None,
        filename: Optional[str] = None,
        expr: Optional[list] = None,
        properties: Optional[dict] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """新建结果导出节点：Data / Image / Animation / Table / Mesh / Plot。

        参数：
            tag: 导出节点标签
            export_type: 导出类型
            plotgroup: 绑定到某个绘图组标签（Image/Animation 常用；走三参数 create(etag,pgtag,type)）
            filename: 输出文件名
            expr: 表达式列表（Data/Table 用），如 ["T","u","v"]
            properties: 其它属性，如 Image 的 {imagetype:png, width:800, height:600}
            model_name: 模型名

        返回：{success, tag, type, filename, plotgroup, warnings}
        """
        try:
            model = _model(model_name)
            exports = model.java.result().export()
            if plotgroup:
                try:
                    node = exports.create(tag, plotgroup, export_type)
                except Exception:
                    node = exports.create(tag, export_type)
                    node.set("plotgroup", str(plotgroup))
            else:
                node = exports.create(tag, export_type)
            warnings: list[str] = []
            if filename is not None:
                node.set("filename", _absolute_filename(filename))
            if expr:
                values = list(expr) if isinstance(expr, (list, tuple)) else [expr]
                node.set("expr", [str(v) for v in values])
            failures = _set_properties(node, properties)
            if failures:
                warnings.extend(
                    "property %s rejected: %s" % (f["property"], f["error"]) for f in failures
                )
            return _ok(
                tag=str(tag),
                type=str(export_type),
                filename=_read_string(node, "filename"),
                plotgroup=plotgroup,
                warnings=warnings,
            )
        except Exception as exc:
            return _err(
                "Failed to create export %r: %s" % (tag, exc),
                export_type=export_type,
                hint="valid types: %s" % ", ".join(EXPORT_TYPES),
            )

    @mcp.tool()
    def export_list(model_name: Optional[str] = None) -> dict:
        """列出所有结果导出节点（tag / 类型 / 文件名）。

        参数：
            model_name: 模型名

        返回：{success, count, exports: [{tag,type,filename}]}
        """
        try:
            model = _model(model_name)
            exports = model.java.result().export()
            rows: list[dict] = []
            for raw_tag in exports.tags():
                tag = str(raw_tag)
                row: dict[str, Any] = {"tag": tag}
                try:
                    node = exports.get(tag)
                except Exception as exc:
                    row["error"] = str(exc)
                    rows.append(row)
                    continue
                try:
                    row["type"] = str(node.getType())
                except Exception:
                    row["type"] = None
                row["filename"] = _read_string(node, "filename")
                rows.append(row)
            return _ok(count=len(rows), exports=rows)
        except Exception as exc:
            return _err("Failed to list exports: %s" % exc)

    @mcp.tool()
    def export_set(
        tag: str,
        properties: Optional[dict] = None,
        filename: Optional[str] = None,
        expr: Optional[list] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """修改已有导出节点的属性 / 文件名 / 表达式。

        参数：
            tag: 导出节点标签
            properties: 属性字典，如 {imagetype:png, width:800}
            filename: 输出文件名
            expr: 表达式列表
            model_name: 模型名

        返回：{success, tag, filename, applied, warnings}
        """
        try:
            model = _model(model_name)
            exports = model.java.result().export()
            try:
                node = exports.get(tag)
            except Exception as exc:
                return _err("Export %r not found (%s)" % (tag, exc), tag=tag)
            if filename is not None:
                node.set("filename", _absolute_filename(filename))
            if expr:
                values = list(expr) if isinstance(expr, (list, tuple)) else [expr]
                node.set("expr", [str(v) for v in values])
            failures = _set_properties(node, properties)
            rejected = {f["property"] for f in failures}
            applied = [
                key
                for key, present in (
                    ("filename", filename is not None),
                    ("expr", bool(expr)),
                )
                if present
            ]
            applied.extend(k for k in (properties or {}) if k not in rejected)
            return _ok(
                tag=str(tag),
                filename=_read_string(node, "filename"),
                applied=applied,
                warnings=[
                    "property %s rejected: %s" % (f["property"], f["error"]) for f in failures
                ],
            )
        except Exception as exc:
            return _err("Failed to update export %r: %s" % (tag, exc), tag=tag)

    @mcp.tool()
    def export_run(tag: Optional[str] = None, model_name: Optional[str] = None) -> dict:
        """执行导出节点（写文件）。tag 留空则运行全部导出节点。

        注意：Data/Table 导出需要已求解的结果；无解时 COMSOL 可能静默不写文件。

        参数：
            tag: 导出节点标签；留空运行全部
            model_name: 模型名

        返回：{success, ran, count}
        """
        try:
            model = _model(model_name)
            exports = model.java.result().export()
            if tag:
                try:
                    node = exports.get(tag)
                    node.run()
                except Exception as exc:
                    return _err("Failed to run export %r: %s" % (tag, exc), tag=tag)
                target = _read_string(node, "filename")
                written = bool(target) and os.path.isfile(str(target))
                return _ok(
                    ran=[str(tag)],
                    count=1,
                    filename=target,
                    file_written=written,
                    note=(
                        "file_written=false means COMSOL produced no file - normal when "
                        "the model has no solved solution (Data/Table have no data, a "
                        "plot group has nothing to render)"
                    ),
                )
            exports.run()
            return _ok(ran=[str(t) for t in exports.tags()], count=len(list(exports.tags())))
        except Exception as exc:
            return _err("Failed to run export(s): %s" % exc, tag=tag)

    @mcp.tool()
    def export_delete(tag: str, model_name: Optional[str] = None) -> dict:
        """删除一个导出节点。

        参数：
            tag: 导出节点标签
            model_name: 模型名

        返回：{success, deleted, remaining}
        """
        try:
            model = _model(model_name)
            exports = model.java.result().export()
            exports.remove(tag)
            return _ok(
                deleted=str(tag),
                remaining=[str(t) for t in exports.tags()],
            )
        except Exception as exc:
            return _err("Failed to delete export %r: %s" % (tag, exc), tag=tag)

    # ------------------------------------------------------------------ #
    # 5. Plot groups
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def plot_create(
        tag: str,
        plot_group_type: str = "PlotGroup3D",
        features: Optional[list] = None,
        title: Optional[str] = None,
        properties: Optional[dict] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """新建绘图组（云图/曲线/面图），并可一次挂上绘图特征。

        参数：
            tag: 绘图组标签
            plot_group_type: PlotGroup3D / PlotGroup2D / PlotGroup1D / PolarGroup / SmithGroup
            features: 特征列表 [{tag,type,expr,properties}]，如 [{"tag":"surf1","type":"Surface","expr":"T"}]
            title: 图标题
            properties: 绘图组属性
            model_name: 模型名

        返回：{success, tag, type, features: [{tag,type,expr}], warnings}
        """
        try:
            model = _model(model_name)
            result = model.java.result()
            group = result.create(tag, plot_group_type)
            warnings: list[str] = []
            if title is not None:
                try:
                    group.set("title", str(title))
                except Exception as exc:
                    warnings.append("title rejected: %s" % exc)
            failures = _set_properties(group, properties)
            if failures:
                warnings.extend(
                    "property %s rejected: %s" % (f["property"], f["error"]) for f in failures
                )
            created: list[dict] = []
            for item in features or []:
                if not isinstance(item, dict) or not item.get("tag") or not item.get("type"):
                    warnings.append("feature entry needs tag+type, skipped: %r" % (item,))
                    continue
                feature = group.feature().create(str(item["tag"]), str(item["type"]))
                if item.get("expr") is not None:
                    feature.set("expr", str(item["expr"]))
                feature_failures = _set_properties(feature, item.get("properties"))
                if feature_failures:
                    warnings.extend(
                        "feature %s property %s rejected: %s"
                        % (item["tag"], f["property"], f["error"])
                        for f in feature_failures
                    )
                created.append(
                    {"tag": str(item["tag"]), "type": str(item["type"]), "expr": item.get("expr")}
                )
            return _ok(
                tag=str(tag),
                type=str(plot_group_type),
                features=created,
                warnings=warnings,
            )
        except Exception as exc:
            return _err(
                "Failed to create plot group %r: %s" % (tag, exc),
                plot_group_type=plot_group_type,
                hint="valid types: %s" % ", ".join(PLOT_GROUP_TYPES),
            )

    @mcp.tool()
    def plot_set(
        tag: str,
        properties: Optional[dict] = None,
        title: Optional[str] = None,
        feature_tag: Optional[str] = None,
        feature_type: Optional[str] = None,
        expr: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """修改绘图组或其中某个绘图特征（给特征设表达式 / 属性；特征不存在时按 feature_type 创建）。

        参数：
            tag: 绘图组标签
            properties: 绘图组属性
            title: 图标题
            feature_tag: 绘图特征标签（如 surf1 / line1）
            feature_type: 特征不存在时的类型（如 Surface / Line / Volume）
            expr: 特征表达式（如 "T"）
            model_name: 模型名

        返回：{success, tag, feature, created_feature, warnings}
        """
        try:
            model = _model(model_name)
            result = model.java.result()
            try:
                group = result.get(tag)
            except Exception as exc:
                return _err("Plot group %r not found (%s)" % (tag, exc), tag=tag)
            warnings: list[str] = []
            if title is not None:
                group.set("title", str(title))
            failures = _set_properties(group, properties)
            if failures:
                warnings.extend(
                    "property %s rejected: %s" % (f["property"], f["error"]) for f in failures
                )
            created_feature = False
            if feature_tag:
                existing = False
                try:
                    existing = str(feature_tag) in [str(t) for t in group.feature().tags()]
                except Exception:
                    existing = False
                if existing:
                    feature = group.feature(str(feature_tag))
                elif feature_type:
                    feature = group.feature().create(str(feature_tag), str(feature_type))
                    created_feature = True
                else:
                    return _err(
                        "Feature %r does not exist and feature_type was not given"
                        % feature_tag,
                        tag=tag,
                    )
                if expr is not None:
                    feature.set("expr", str(expr))
                feature_failures = _set_properties(feature, properties)
                if feature_failures:
                    warnings.extend(
                        "feature property %s rejected: %s"
                        % (f["property"], f["error"])
                        for f in feature_failures
                    )
            return _ok(
                tag=str(tag),
                feature=feature_tag,
                created_feature=created_feature,
                warnings=warnings,
            )
        except Exception as exc:
            return _err("Failed to update plot group %r: %s" % (tag, exc), tag=tag)

    @mcp.tool()
    def plot_delete(tag: str, model_name: Optional[str] = None) -> dict:
        """删除一个绘图组（连同其绘图特征）。

        参数：
            tag: 绘图组标签
            model_name: 模型名

        返回：{success, deleted, remaining}
        """
        try:
            model = _model(model_name)
            result = model.java.result()
            result.remove(tag)
            remaining = []
            for raw_tag in result.tags():
                try:
                    node = result.get(str(raw_tag))
                    if bool(node.isPlotGroup()):
                        remaining.append(str(raw_tag))
                except Exception:
                    continue
            return _ok(deleted=str(tag), remaining=remaining)
        except Exception as exc:
            return _err("Failed to delete plot group %r: %s" % (tag, exc), tag=tag)

    @mcp.tool()
    def plot_export(
        tag: str,
        filename: str,
        image_type: str = "png",
        width: int = 800,
        height: int = 600,
        properties: Optional[dict] = None,
        keep_export: bool = False,
        model_name: Optional[str] = None,
    ) -> dict:
        """把绘图组导出成图片（云图/曲线出图）：临时建一个 Image 导出节点并 run()。

        参数：
            tag: 绘图组标签
            filename: 输出图片路径
            image_type: png / jpeg / bmp / tiff / gif / eps
            width / height: 图片像素尺寸
            properties: 其它 Image 导出属性（如 {size:"current"}）
            keep_export: 是否保留临时导出节点（默认导出后删除，保持模型干净）
            model_name: 模型名

        返回：{success, tag, filename, export_tag, kept, warnings}
        """
        try:
            model = _model(model_name)
            result = model.java.result()
            try:
                group = result.get(tag)
            except Exception as exc:
                return _err("Plot group %r not found (%s)" % (tag, exc), tag=tag)
            if not bool(group.isPlotGroup()):
                return _err("%r is not a plot group" % tag, tag=tag)
            exports = result.export()
            export_tag = "img_%s" % str(tag)
            try:
                node = exports.create(export_tag, str(tag), "Image")
            except Exception:
                node = exports.create(export_tag, "Image")
                node.set("plotgroup", str(tag))
            warnings: list[str] = []
            node.set("filename", _absolute_filename(filename))
            # width/height are UNIT STRINGS on an Image export: the default
            # "manualprint" preset reads them as cm, so 640 would mean 640 cm
            # ("width must not exceed 4096 px").  "manualweb" is the pixel
            # preset — that is the only mode where 640 means 640 px.
            try:
                node.set("imagetype", str(image_type))
                node.set("size", "manualweb")
                node.set("width", str(int(width)))
                node.set("height", str(int(height)))
            except Exception as exc:
                warnings.append("imagetype/size/width/height rejected: %s" % exc)
            failures = _set_properties(node, properties)
            if failures:
                warnings.extend(
                    "property %s rejected: %s" % (f["property"], f["error"]) for f in failures
                )
            node.run()
            written = os.path.isfile(_absolute_filename(filename))
            if not keep_export:
                try:
                    exports.remove(export_tag)
                except Exception as exc:
                    warnings.append("could not remove temp export: %s" % exc)
            return _ok(
                tag=str(tag),
                filename=_absolute_filename(filename),
                export_tag=export_tag,
                kept=bool(keep_export),
                file_written=written,
                warnings=warnings,
            )
        except Exception as exc:
            return _err("Failed to export plot group %r: %s" % (tag, exc), tag=tag)
