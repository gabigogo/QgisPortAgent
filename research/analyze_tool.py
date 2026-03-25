"""
analyze_tool.py — Workspace-aware ArcGIS tool analyzer for the QgisPortAgent VS Code extension.

Accepts a single ArcGIS source file path as argv[1], introspects its content, and prints a
single JSON object to stdout describing:
  - file_format       : detected source format
  - tool_names        : list of tool display names
  - tool_count        : number of tools found
  - python_version    : "2.7" | "3.x" | "unknown"
  - py27_patterns     : list of Py27 pattern matches (strings)
  - license_tiers     : list of ArcGIS license tier / extension names required
  - arcpy_namespaces  : list of unique arcpy.* sub-namespaces used
  - param_qgis_types  : dict mapping tool_name -> list of {name, display_name, direction, qgis_type}
  - confidence_ceilings: dict mapping namespace -> float ceiling score
  - parse_errors      : list of error strings
  - analysis_ok       : bool — False if a fatal error occurred

All errors and warnings are written to stderr only. stdout carries ONLY valid JSON.

Usage:
    python research/analyze_tool.py "path/to/tool.tbx"
    python research/analyze_tool.py "path/to/script.py"
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import struct
import sys
import zipfile
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARCPY_NS_CEILINGS: dict[str, float] = {
    "arcpy.sa":       0.90,
    "arcpy.ia":       0.70,
    "arcpy.sharing":  0.60,
    "arcpy.interop":  0.75,
    "arcpy.na":       0.80,
    "arcpy.3d":       0.80,
    "arcpy.cartography": 0.85,
    "arcpy.conversion":  0.88,
    "arcpy.management":  0.90,
    "arcpy.analysis":    0.92,
}

LICENSE_TIER_PATTERNS: dict[str, str] = {
    "Spatial Analyst":        r"arcpy\.sa\.",
    "Image Analyst":          r"arcpy\.ia\.",
    "Network Analyst":        r"arcpy\.na\.",
    "3D Analyst":             r"arcpy\.3d\.|arcpy\.Slope\b|arcpy\.HillShade\b|arcpy\.Aspect\b",
    "Data Interoperability":  r"arcpy\.interop\.",
    "Publisher":              r"arcpy\.sharing\.",
    "Advanced (ArcInfo)":     r'arcpy\.CheckExtension\(\s*["\']Advance|arcpy\.CheckExtension\(\s*["\']ArcInfo',
    "Standard (ArcEditor)":   r'arcpy\.CheckExtension\(\s*["\']Standard|arcpy\.CheckExtension\(\s*["\']ArcEditor',
}

PY27_PATTERNS: dict[str, str] = {
    "print statement":         r"^\s*print\s+[^(=\n]",
    "unicode() builtin":       r"\bunicode\(",
    "basestring type":         r"\bbasestring\b",
    "xrange builtin":          r"\bxrange\(",
    "dict.iteritems()":        r"\.iteritems\(\)",
    "dict.itervalues()":       r"\.itervalues\(\)",
    "dict.iterkeys()":         r"\.iterkeys\(\)",
    "except Exception, e:":    r"except\s+\w+\s*,\s*\w+\s*:",
    "arcpy.mapping (legacy)":  r"arcpy\.mapping\.",
}

ARCPY_NS_RE = re.compile(r"arcpy(?:\.([a-zA-Z0-9_]+))?(?:\.\w+)?")


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_format(path: pathlib.Path) -> str:
    """Return one of: tbx_binary, tbx_xml, atbx, pyt, py, unknown."""
    ext = path.suffix.lower()

    if ext == ".atbx":
        return "atbx"

    if ext == ".tbx":
        with open(path, "rb") as fh:
            magic = fh.read(4)
        if magic == b"\xd0\xcf\x11\xe0":
            return "tbx_binary"
        if magic[:1] == b"<":
            return "tbx_xml"
        return "tbx_xml"  # assume XML if not OLE

    if ext in (".py", ".pyt"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "getParameterInfo" in text:
            return "pyt"
        return "py"

    return "unknown"


# ---------------------------------------------------------------------------
# Python text analysis helpers (shared by py/pyt/atbx)
# ---------------------------------------------------------------------------

def scan_py_text(text: str) -> tuple[str, list[str], list[str], list[str]]:
    """
    Scan Python source text and return:
        python_version, py27_patterns, license_tiers, arcpy_namespaces
    """
    py27_hits: list[str] = []
    for label, pattern in PY27_PATTERNS.items():
        if re.search(pattern, text, re.MULTILINE):
            py27_hits.append(label)

    python_version = "2.7" if py27_hits else "unknown"
    if re.search(r"\bfrom\s+__future__\s+import\b|f\".*\"", text):
        python_version = "3.x"
    if py27_hits:
        python_version = "2.7"

    license_tiers: list[str] = []
    for tier, pattern in LICENSE_TIER_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            license_tiers.append(tier)
    if not license_tiers:
        if re.search(r"import arcpy", text):
            license_tiers.append("Basic (ArcView)")

    # Collect arcpy sub-namespaces
    ns_set: set[str] = set()
    for m in ARCPY_NS_RE.finditer(text):
        sub = m.group(1)
        if sub:
            ns_set.add(f"arcpy.{sub}")
        else:
            ns_set.add("arcpy")
    arcpy_namespaces = sorted(ns_set)

    return python_version, py27_hits, license_tiers, arcpy_namespaces


# ---------------------------------------------------------------------------
# .py / .pyt analyzer
# ---------------------------------------------------------------------------

def analyze_py(path: pathlib.Path, fmt: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    python_version, py27_hits, license_tiers, arcpy_namespaces = scan_py_text(text)

    tool_names: list[str] = []
    param_qgis_types: dict[str, list[dict]] = {}

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return {
            "file_format": fmt,
            "tool_names": [path.stem],
            "tool_count": 1,
            "python_version": python_version,
            "py27_patterns": py27_hits,
            "license_tiers": license_tiers,
            "arcpy_namespaces": arcpy_namespaces,
            "param_qgis_types": {},
            "confidence_ceilings": _compute_ceilings(arcpy_namespaces),
            "parse_errors": [f"SyntaxError: {exc}"],
            "analysis_ok": True,
        }

    if fmt == "pyt":
        tool_names = _extract_pyt_tools(tree)
        param_qgis_types = _extract_pyt_params(tree, tool_names)
    else:
        # Standalone .py — use filename as tool name
        tool_names = [path.stem]
        param_qgis_types = {path.stem: _extract_py_params(tree)}

    return {
        "file_format": fmt,
        "tool_names": tool_names,
        "tool_count": len(tool_names),
        "python_version": python_version,
        "py27_patterns": py27_hits,
        "license_tiers": license_tiers,
        "arcpy_namespaces": arcpy_namespaces,
        "param_qgis_types": param_qgis_types,
        "confidence_ceilings": _compute_ceilings(arcpy_namespaces),
        "parse_errors": [],
        "analysis_ok": True,
    }


def _extract_pyt_tools(tree: ast.Module) -> list[str]:
    tool_names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in ast.walk(node):
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                for stmt in ast.walk(item):
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Attribute) and target.attr == "label":
                                if isinstance(stmt.value, ast.Constant):
                                    tool_names.append(str(stmt.value.value))
    if not tool_names:
        # Fall back to class names that look like tools
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name != "Toolbox":
                tool_names.append(node.name)
    return tool_names or ["(unnamed tool)"]


def _extract_pyt_params(tree: ast.Module, tool_names: list[str]) -> dict[str, list[dict]]:
    """Best-effort extraction of arcpy.Parameter() kwargs from getParameterInfo methods."""
    result: dict[str, list[dict]] = {}
    tool_idx = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name == "Toolbox":
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "getParameterInfo":
                params = _parse_get_parameter_info(item)
                name = tool_names[tool_idx] if tool_idx < len(tool_names) else node.name
                result[name] = params
        tool_idx += 1
    return result


def _parse_get_parameter_info(func_node: ast.FunctionDef) -> list[dict]:
    params = []
    for stmt in ast.walk(func_node):
        if not isinstance(stmt, ast.Call):
            continue
        # Look for arcpy.Parameter(...)
        func = stmt.func
        if not (isinstance(func, ast.Attribute) and func.attr == "Parameter"):
            continue
        kwargs = {kw.arg: kw.value for kw in stmt.keywords if kw.arg}
        name = _ast_str(kwargs.get("name", kwargs.get("displayName")))
        display_name = _ast_str(kwargs.get("displayName", kwargs.get("name")))
        direction = _ast_str(kwargs.get("direction")) or "Input"
        datatype = _ast_str(kwargs.get("datatype")) or "GPString"
        from research.tbx_parser import GP_TYPE_MAP  # type: ignore[import]
        entry = GP_TYPE_MAP.get(datatype, {})
        if direction.lower() == "output":
            qgis_type = entry.get("qgis_output", entry.get("qgis", "QgsProcessingParameterFileDestination"))
        else:
            qgis_type = entry.get("qgis", "QgsProcessingParameterString")
        params.append({"name": name, "display_name": display_name, "direction": direction, "qgis_type": qgis_type})
    return params


def _extract_py_params(tree: ast.Module) -> list[dict]:
    """Extract argparse arguments as a best-effort param list."""
    params = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "add_argument":
                args = [_ast_str(a) for a in node.args if isinstance(a, ast.Constant)]
                kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                name = args[0].lstrip("-") if args else "(param)"
                help_str = _ast_str(kwargs.get("help")) or ""
                params.append({"name": name, "display_name": name, "direction": "Input", "qgis_type": "QgsProcessingParameterString", "help": help_str})
    return params


def _ast_str(node: Any) -> str:
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Str):  # Python 3.7 compat
        return node.s
    return ""


# ---------------------------------------------------------------------------
# .atbx analyzer
# ---------------------------------------------------------------------------

def analyze_atbx(path: pathlib.Path) -> dict[str, Any]:
    tool_names: list[str] = []
    param_qgis_types: dict[str, list[dict]] = {}
    arcpy_namespaces: list[str] = []
    license_tiers: list[str] = []
    py27_hits: list[str] = []
    python_version = "3.x"
    parse_errors: list[str] = []

    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            tool_dirs = sorted({n.split("/")[0] for n in names if "/" in n and n.split("/")[0].endswith(".tool")})
            for tool_dir in tool_dirs:
                # Read tool metadata JSON
                meta_candidates = [n for n in names if n.startswith(tool_dir + "/") and n.endswith("esri_toolinfo.json")]
                display_name = tool_dir.removesuffix(".tool")
                if meta_candidates:
                    try:
                        raw = zf.read(meta_candidates[0]).decode("utf-8", errors="replace")
                        meta = json.loads(raw)
                        display_name = meta.get("displayName") or meta.get("name") or display_name
                    except Exception:
                        pass
                tool_names.append(display_name)

                # Try to scan embedded execute script for arcpy usage
                script_candidates = [n for n in names if n.startswith(tool_dir + "/") and n.endswith(".py")]
                for sc in script_candidates:
                    try:
                        text = zf.read(sc).decode("utf-8", errors="replace")
                        pv, ph, lt, ns = scan_py_text(text)
                        if ph:
                            py27_hits.extend(ph)
                        license_tiers.extend(lt)
                        arcpy_namespaces.extend(ns)
                    except Exception:
                        pass

    except Exception as exc:
        parse_errors.append(f".atbx read error: {exc}")

    arcpy_namespaces = sorted(set(arcpy_namespaces))
    license_tiers = sorted(set(license_tiers))

    return {
        "file_format": "atbx",
        "tool_names": tool_names or [path.stem],
        "tool_count": len(tool_names) or 1,
        "python_version": python_version,
        "py27_patterns": list(set(py27_hits)),
        "license_tiers": license_tiers or ["Basic (ArcView)"],
        "arcpy_namespaces": arcpy_namespaces,
        "param_qgis_types": param_qgis_types,
        "confidence_ceilings": _compute_ceilings(arcpy_namespaces),
        "parse_errors": parse_errors,
        "analysis_ok": True,
    }


# ---------------------------------------------------------------------------
# .tbx binary analyzer — delegates to tbx_parser
# ---------------------------------------------------------------------------

def analyze_tbx_binary(path: pathlib.Path) -> dict[str, Any]:
    parse_errors: list[str] = []
    tool_names: list[str] = []
    param_qgis_types: dict[str, list[dict]] = {}
    license_tiers: list[str] = ["Basic (ArcView)"]
    arcpy_namespaces: list[str] = []
    python_version = "2.7"  # ArcMap toolboxes are always Python 2.7

    try:
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from tbx_parser import parse_tbx  # type: ignore[import]
        tbx = parse_tbx(str(path))
        for tool in tbx.tools:
            tool_names.append(tool.display_name or tool.internal_name or f"Tool{tool.index}")
            params = []
            for p in tool.parameters:
                params.append({
                    "name": p.internal_name,
                    "display_name": p.display_name,
                    "direction": p.direction,
                    "qgis_type": p.qgis_type,
                    "qgis_note": p.qgis_note,
                })
                if p.internal_name.startswith("__parse_error_"):
                    parse_errors.append(f"Parse error in '{tool.display_name}': {p.display_name}")
            param_qgis_types[tool.display_name or tool.internal_name] = params

    except ImportError:
        parse_errors.append("olefile not installed — run: pip install olefile")
    except Exception as exc:
        parse_errors.append(f"tbx_parser error: {exc}")
        # Fallback: just record the filename as the tool name
        if not tool_names:
            tool_names = [path.stem]

    return {
        "file_format": "tbx_binary",
        "tool_names": tool_names or [path.stem],
        "tool_count": len(tool_names) or 1,
        "python_version": python_version,
        "py27_patterns": ["Python 2.7 (ArcMap toolbox implicit)"],
        "license_tiers": license_tiers,
        "arcpy_namespaces": arcpy_namespaces,
        "param_qgis_types": param_qgis_types,
        "confidence_ceilings": {"arcpy": 0.85},
        "parse_errors": parse_errors,
        "analysis_ok": len(parse_errors) == 0 or bool(tool_names),
    }


# ---------------------------------------------------------------------------
# .tbx XML analyzer
# ---------------------------------------------------------------------------

def analyze_tbx_xml(path: pathlib.Path) -> dict[str, Any]:
    parse_errors: list[str] = []
    tool_names: list[str] = []

    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(path)
        root = tree.getroot()
        # <GPToolbox> / <GPGraph> structures — best-effort name extraction
        for tag in ("ToolName", "displayname", "Name", "name", "label"):
            for el in root.iter(tag):
                val = (el.text or "").strip()
                if val and val not in tool_names:
                    tool_names.append(val)
        if not tool_names:
            tool_names = [path.stem]
    except Exception as exc:
        parse_errors.append(f"XML parse error: {exc}")
        tool_names = [path.stem]

    return {
        "file_format": "tbx_xml",
        "tool_names": tool_names,
        "tool_count": len(tool_names),
        "python_version": "unknown",
        "py27_patterns": [],
        "license_tiers": ["Basic (ArcView)"],
        "arcpy_namespaces": [],
        "param_qgis_types": {},
        "confidence_ceilings": {},
        "parse_errors": parse_errors,
        "analysis_ok": True,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_ceilings(arcpy_namespaces: list[str]) -> dict[str, float]:
    ceilings: dict[str, float] = {}
    for ns in arcpy_namespaces:
        if ns in ARCPY_NS_CEILINGS:
            ceilings[ns] = ARCPY_NS_CEILINGS[ns]
    return ceilings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"analysis_ok": False, "parse_errors": ["Usage: analyze_tool.py <file_path>"]}))
        sys.exit(1)

    path = pathlib.Path(sys.argv[1])
    if not path.exists():
        print(json.dumps({"analysis_ok": False, "parse_errors": [f"File not found: {path}"]}))
        sys.exit(1)

    fmt = detect_format(path)
    print(f"[analyze_tool] detected format: {fmt}", file=sys.stderr)

    try:
        if fmt == "tbx_binary":
            result = analyze_tbx_binary(path)
        elif fmt == "tbx_xml":
            result = analyze_tbx_xml(path)
        elif fmt == "atbx":
            result = analyze_atbx(path)
        elif fmt in ("py", "pyt"):
            result = analyze_py(path, fmt)
        else:
            result = {
                "file_format": "unknown",
                "tool_names": [path.stem],
                "tool_count": 1,
                "python_version": "unknown",
                "py27_patterns": [],
                "license_tiers": [],
                "arcpy_namespaces": [],
                "param_qgis_types": {},
                "confidence_ceilings": {},
                "parse_errors": [f"Unsupported file extension: {path.suffix}"],
                "analysis_ok": False,
            }

        result["file_path"] = str(path)
        result["file_name"] = path.name
        print(json.dumps(result, indent=2))

    except Exception as exc:
        import traceback
        print(traceback.format_exc(), file=sys.stderr)
        print(json.dumps({"analysis_ok": False, "file_path": str(path), "parse_errors": [str(exc)]}))
        sys.exit(1)


if __name__ == "__main__":
    main()
