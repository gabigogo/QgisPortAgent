"""
tbx_to_qgis.py — Generate a QGIS 3.44 Processing Plugin scaffold from a parsed TbxToolbox.

Usage:
    python research/tbx_to_qgis.py arcgis-tools/MyToolbox.tbx [--out qgis-tools] [--scope full]

Scopes:
    full          Plugin scaffold + algorithm + tests + migration_report + requirements.txt (default)
    scaffold-only Plugin directory only (no tests, no report)
    report-only   migration_report.md only
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import textwrap
from dataclasses import dataclass
from datetime import date

# Ensure tbx_parser is importable when called from repo root
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from tbx_parser import TbxParameter, TbxTool, TbxToolbox, parse_tbx


# ── Confidence scoring ─────────────────────────────────────────────────────────

# Default confidence per QGIS parameter type (output types carry same score as input)
_PARAM_CONFIDENCE: dict[str, float] = {
    "QgsProcessingParameterFeatureSource":      0.95,
    "QgsProcessingParameterFeatureSink":        0.95,
    "QgsProcessingParameterRasterLayer":        0.95,
    "QgsProcessingParameterRasterDestination":  0.95,
    "QgsProcessingParameterVectorLayer":        0.90,
    "QgsProcessingParameterVectorDestination":  0.90,
    "QgsProcessingParameterField":              0.90,
    "QgsProcessingParameterString":             0.85,
    "QgsProcessingParameterNumber":             0.90,
    "QgsProcessingParameterBoolean":            0.95,
    "QgsProcessingParameterDistance":           0.85,
    "QgsProcessingParameterCrs":                0.90,
    "QgsProcessingParameterExtent":             0.90,
    "QgsProcessingParameterPoint":              0.90,
    "QgsProcessingParameterFile":               0.80,
    "QgsProcessingParameterFolderDestination":  0.80,
    "QgsProcessingParameterExpression":         0.85,
    "QgsProcessingParameterMatrix":             0.70,
    "QgsProcessingParameterMultipleLayers":     0.75,
    "QgsProcessingParameterMapLayer":           0.80,
    "QgsProcessingParameterBand":               0.85,
    "QgsProcessingParameterGeometry":           0.80,
}

# Types that need a migration note even when mapped
_NEEDS_REVIEW_PREFIXES = ("⚠", "QgsProcessingParameterString")


def _param_confidence(p: TbxParameter) -> float:
    if p.qgis_type.startswith("⚠"):
        return 0.30
    if p.internal_name.startswith("__parse_error"):
        return 0.10
    base = _PARAM_CONFIDENCE.get(p.qgis_type, 0.70)
    # Downgrade if there's a caveated migration note
    if p.qgis_note and ("no" in p.qgis_note.lower() or "manual" in p.qgis_note.lower() or "review" in p.qgis_note.lower()):
        base = min(base, 0.70)
    return base


def _tool_confidence(tool: TbxTool) -> float:
    if not tool.parameters:
        return 0.60  # No params extracted — ModelBuilder with no exposed params
    confidences = [_param_confidence(p) for p in tool.parameters]
    avg = sum(confidences) / len(confidences)
    # ModelBuilder tools (type 1/2) can't recover execute logic — cap at 0.65
    if tool.tool_type in (1, 2):
        avg = min(avg, 0.65)
    return round(avg, 2)


# ── Code generation helpers ────────────────────────────────────────────────────

def _safe_id(name: str) -> str:
    """Convert an ArcGIS internal name to a safe Python identifier."""
    s = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    if s and s[0].isdigit():
        s = "_" + s
    return s or "param"


def _to_snake(name: str) -> str:
    return _safe_id(name).lower()


def _to_pascal(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    return "".join(p.capitalize() for p in parts if p)


def _qgis_param_constant(p: TbxParameter, tool: TbxTool) -> str:
    """Return the constant name used as the parameter ID, e.g. INPUT_FEATURES."""
    prefix = "OUTPUT" if p.direction == "Output" else "INPUT"
    base = _safe_id(p.internal_name).upper()
    # Avoid INPUT_INPUT or OUTPUT_OUTPUT redundancy
    if base.startswith(prefix + "_"):
        return base
    return f"{prefix}_{base}" if not base.startswith(prefix) else base


# ── Parameter definition code ──────────────────────────────────────────────────

_QGIS_PARAM_CONSTRUCTORS: dict[str, str] = {
    "QgsProcessingParameterFeatureSource":
        "QgsProcessingParameterFeatureSource(\n            self.{const}, self.tr({disp!r}), [QgsProcessing.TypeVectorAnyGeometry])",
    "QgsProcessingParameterFeatureSink":
        "QgsProcessingParameterFeatureSink(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterRasterLayer":
        "QgsProcessingParameterRasterLayer(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterRasterDestination":
        "QgsProcessingParameterRasterDestination(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterVectorLayer":
        "QgsProcessingParameterVectorLayer(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterVectorDestination":
        "QgsProcessingParameterVectorDestination(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterField":
        "QgsProcessingParameterField(\n            self.{const}, self.tr({disp!r}), parentLayerParameterName='')",
    "QgsProcessingParameterString":
        "QgsProcessingParameterString(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterNumber":
        "QgsProcessingParameterNumber(\n            self.{const}, self.tr({disp!r}), QgsProcessingParameterNumber.Double)",
    "QgsProcessingParameterBoolean":
        "QgsProcessingParameterBoolean(\n            self.{const}, self.tr({disp!r}), defaultValue=False)",
    "QgsProcessingParameterDistance":
        "QgsProcessingParameterDistance(\n            self.{const}, self.tr({disp!r}), defaultValue=0.0)",
    "QgsProcessingParameterCrs":
        "QgsProcessingParameterCrs(\n            self.{const}, self.tr({disp!r}), optional=True)",
    "QgsProcessingParameterExtent":
        "QgsProcessingParameterExtent(\n            self.{const}, self.tr({disp!r}), optional=True)",
    "QgsProcessingParameterPoint":
        "QgsProcessingParameterPoint(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterFile":
        "QgsProcessingParameterFile(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterFolderDestination":
        "QgsProcessingParameterFolderDestination(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterExpression":
        "QgsProcessingParameterExpression(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterMatrix":
        "QgsProcessingParameterMatrix(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterMultipleLayers":
        "QgsProcessingParameterMultipleLayers(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterMapLayer":
        "QgsProcessingParameterMapLayer(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterBand":
        "QgsProcessingParameterBand(\n            self.{const}, self.tr({disp!r}))",
    "QgsProcessingParameterGeometry":
        "QgsProcessingParameterGeometry(\n            self.{const}, self.tr({disp!r}))",
}

_FALLBACK_CONSTRUCTOR = (
    "QgsProcessingParameterString(\n"
    "            self.{const}, self.tr({disp!r})  "
    "# TODO: ⚠ unmapped type {gp_class!r} — replace with correct parameter class"
    ")"
)


def _build_param_addparam(p: TbxParameter, const: str) -> str:
    qtype = p.qgis_type
    tmpl = _QGIS_PARAM_CONSTRUCTORS.get(qtype)
    if tmpl is None:
        constructor = _FALLBACK_CONSTRUCTOR.format(
            const=const, disp=p.display_name, gp_class=p.gp_class
        )
    else:
        constructor = tmpl.format(const=const, disp=p.display_name, gp_class=p.gp_class)

    optional = "True" if p.direction == "Output" else "False"
    lines = [f"        param = {constructor}"]
    if p.direction == "Output":
        lines.append("        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)")
    if p.qgis_note:
        lines.append(f"        # Migration note: {p.qgis_note}")
    lines.append("        self.addParameter(param)")
    return "\n".join(lines)


def _build_process_snippet(p: TbxParameter, const: str) -> str:
    """Return the processAlgorithm() retrieval snippet for a parameter."""
    qtype = p.qgis_type
    if qtype in ("QgsProcessingParameterFeatureSource",):
        return f"        {_to_snake(p.internal_name)} = self.parameterAsSource(parameters, self.{const}, context)"
    if qtype == "QgsProcessingParameterFeatureSink":
        return (
            f"        ({_to_snake(p.internal_name)}, {_to_snake(p.internal_name)}_id) = "
            f"self.parameterAsSink(\n"
            f"            parameters, self.{const}, context,\n"
            f"            source.fields(), source.wkbType(), source.sourceCrs()\n"
            f"        )"
        )
    if qtype in ("QgsProcessingParameterRasterLayer", "QgsProcessingParameterVectorLayer", "QgsProcessingParameterMapLayer"):
        return f"        {_to_snake(p.internal_name)} = self.parameterAsLayer(parameters, self.{const}, context)"
    if qtype == "QgsProcessingParameterRasterDestination":
        return f"        {_to_snake(p.internal_name)} = self.parameterAsOutputLayer(parameters, self.{const}, context)"
    if qtype == "QgsProcessingParameterVectorDestination":
        return f"        {_to_snake(p.internal_name)} = self.parameterAsOutputLayer(parameters, self.{const}, context)"
    if qtype in ("QgsProcessingParameterNumber", "QgsProcessingParameterDistance"):
        return f"        {_to_snake(p.internal_name)} = self.parameterAsDouble(parameters, self.{const}, context)"
    if qtype == "QgsProcessingParameterBoolean":
        return f"        {_to_snake(p.internal_name)} = self.parameterAsBool(parameters, self.{const}, context)"
    if qtype == "QgsProcessingParameterField":
        return f"        {_to_snake(p.internal_name)} = self.parameterAsString(parameters, self.{const}, context)"
    if qtype == "QgsProcessingParameterCrs":
        return f"        {_to_snake(p.internal_name)} = self.parameterAsCrs(parameters, self.{const}, context)"
    if qtype == "QgsProcessingParameterExtent":
        return f"        {_to_snake(p.internal_name)} = self.parameterAsExtent(parameters, self.{const}, context)"
    if qtype == "QgsProcessingParameterPoint":
        return f"        {_to_snake(p.internal_name)} = self.parameterAsPoint(parameters, self.{const}, context)"
    # Default — string
    return f"        {_to_snake(p.internal_name)} = self.parameterAsString(parameters, self.{const}, context)"


# ── File generators ────────────────────────────────────────────────────────────

def _generate_algorithm(tool: TbxTool, plugin_name: str, tool_class: str) -> str:
    """Generate the <tool_name>_algorithm.py content."""
    confidence = _tool_confidence(tool)

    # Build constant declarations
    constants = []
    param_map: list[tuple[TbxParameter, str]] = []
    for p in tool.parameters:
        const = _qgis_param_constant(p, tool)
        param_map.append((p, const))
        constants.append(f"    {const} = '{_to_snake(p.internal_name)}'")

    # Build addParameter calls
    add_params = [_build_param_addparam(p, c) for p, c in param_map]

    # Build processAlgorithm retrieval
    process_snippets = [_build_process_snippet(p, c) for p, c in param_map]

    # Identify a primary source for the FeatureSink CRS/schema reference
    has_source = any(p.qgis_type == "QgsProcessingParameterFeatureSource" for p, _ in param_map)

    # All unique imports needed
    qgs_types_used = sorted({p.qgis_type for p, _ in param_map if not p.qgis_type.startswith("⚠")})
    imports = ["from qgis.core import ("] + [f"    {t}," for t in qgs_types_used] + [
        "    QgsProcessing,",
        "    QgsProcessingAlgorithm,",
        "    QgsProcessingParameterDefinition,",
        "    QgsFeatureSink,",
        ")",
        "from PyQt5.QtCore import QCoreApplication",
    ]

    is_model = tool.tool_type in (1, 2)
    execute_todo = (
        "        # TODO: ModelBuilder tool — execute logic not recoverable from binary .tbx.\n"
        "        # Export the model to Python script in ArcMap (Model menu → Export → To Python\n"
        "        # Script…) and port the generated arcpy calls using the Phase 3 crosswalk tables.\n"
        "        raise NotImplementedError('ModelBuilder execute logic requires manual porting.')"
    ) if is_model else (
        "        # TODO: Implement tool logic.\n"
        "        # Use processing.run('native:*', {...}) for standard spatial operations.\n"
        "        # Reference Phase 3 crosswalk tables in .vscode/arcgis_migration.instructions.md\n"
        "        # for ArcPy → QGIS native equivalents.\n"
        "        raise NotImplementedError('processAlgorithm not yet implemented.')"
    )

    result_map = []
    for p, c in param_map:
        if p.direction == "Output":
            result_map.append(f"            self.{c}: {_to_snake(p.internal_name)}_id,")

    results_block = (
        "        return {\n" + "\n".join(result_map) + "\n        }"
        if result_map else
        "        return {}"
    )

    migration_note = (
        'ModelBuilder tool — execute logic must be ported manually (see TODO below).'
        if is_model else
        'Script tool — implement processAlgorithm() from the original script.'
    )

    # Build output line by line — avoids textwrap.dedent failures when embedded
    # multi-line blocks (imports, params) don't share the template's base indentation.
    out: list[str] = []

    out += [
        "# -*- coding: utf-8 -*-",
        f"# AUTO-GENERATED by tbx_to_qgis.py — {date.today().isoformat()}",
        f"# Source: {tool.display_name!r} ({tool.internal_name!r})",
        f"# ArcGIS tool_type: {tool.tool_type} ({'ModelBuilder' if is_model else 'Script'})",
        f"# Migration confidence: {confidence:.2f}",
        "#",
        "# MIGRATION NOTES:",
        f"# {migration_note}",
        "# Review any parameter marked # TODO below before deploying.",
        "",
    ]

    # Imports — already at 0-indent
    out += imports
    out += ["", ""]

    # Class definition
    out += [
        f"class {tool_class}(QgsProcessingAlgorithm):",
        '    """',
        f"    {tool.display_name}",
        "",
        f"    Migrated from ArcGIS {'ModelBuilder' if is_model else 'Script'} tool.",
        f"    Original toolbox: {plugin_name}",
        f"    Migration confidence: {confidence:.2f}",
        '    """',
        "",
    ]

    # Class-level constants — already have 4-space indent from the comprehension above
    out += constants
    out.append("")

    # Methods
    out += [
        "    def tr(self, string: str) -> str:",
        f"        return QCoreApplication.translate('{tool_class}', string)",
        "",
        "    def createInstance(self):",
        f"        return {tool_class}()",
        "",
        "    def name(self) -> str:",
        f"        return '{_to_snake(tool.internal_name)}'",
        "",
        "    def displayName(self) -> str:",
        f"        return self.tr({tool.display_name!r})",
        "",
        "    def group(self) -> str:",
        f"        return self.tr({plugin_name!r})",
        "",
        "    def groupId(self) -> str:",
        f"        return '{_to_snake(plugin_name)}'",
        "",
        "    def shortHelpString(self) -> str:",
        "        return self.tr(",
        f"            {(tool.description or 'No description available.')!r}",
        "        )",
        "",
        "    def initAlgorithm(self, config=None):",
    ]
    if add_params:
        for ap in add_params:
            out += ap.splitlines()
    else:
        out.append("        pass  # No parameters extracted")

    out += [
        "",
        "    def processAlgorithm(self, parameters, context, feedback):",
    ]
    if process_snippets:
        for ps in process_snippets:
            out += ps.splitlines()
    else:
        out.append("        pass")

    out.append("")
    out += execute_todo.splitlines()
    out.append("")
    out += results_block.splitlines()
    out.append("")

    return "\n".join(out)


def _generate_provider(tool_classes: list[str], plugin_name: str, plugin_id: str) -> str:
    provider_class = _to_pascal(plugin_name) + "Provider"
    out = [
        "# -*- coding: utf-8 -*-",
        "from qgis.core import QgsProcessingProvider",
        "from PyQt5.QtGui import QIcon",
    ]
    for tc in tool_classes:
        out.append(f"from .{_to_snake(tc)}_algorithm import {tc}")
    out += [
        "",
        "",
        f"class {provider_class}(QgsProcessingProvider):",
        "",
        "    def loadAlgorithms(self):",
        "        for alg in [",
    ]
    for tc in tool_classes:
        out.append(f"            {tc}(),")
    out += [
        "        ]:",
        "            self.addAlgorithm(alg)",
        "",
        "    def id(self) -> str:",
        f"        return '{plugin_id}'",
        "",
        "    def name(self) -> str:",
        f"        return '{plugin_name}'",
        "",
        "    def longName(self) -> str:",
        "        return self.name()",
        "",
    ]
    return "\n".join(out)


def _generate_main_plugin(plugin_name: str, provider_class: str) -> str:
    return textwrap.dedent(f"""\
        # -*- coding: utf-8 -*-
        from qgis.core import QgsApplication
        from .processing_provider.provider import {provider_class}


        class {_to_pascal(plugin_name)}Plugin:

            def __init__(self):
                self.provider = None

            def initProcessing(self):
                self.provider = {provider_class}()
                QgsApplication.processingRegistry().addProvider(self.provider)

            def initGui(self):
                self.initProcessing()

            def unload(self):
                QgsApplication.processingRegistry().removeProvider(self.provider)
        """)


def _generate_init(plugin_name: str) -> str:
    return textwrap.dedent(f"""\
        # -*- coding: utf-8 -*-
        def classFactory(iface):
            from .main_plugin import {_to_pascal(plugin_name)}Plugin
            return {_to_pascal(plugin_name)}Plugin()
        """)


def _generate_metadata(plugin_name: str, tbx: TbxToolbox) -> str:
    safe_name = plugin_name.replace(" ", "_")
    return textwrap.dedent(f"""\
        [general]
        name={plugin_name}
        qgisMinimumVersion=3.44
        description=QGIS Processing plugin migrated from ArcGIS toolbox '{tbx.name}'
        version=0.1.0
        author=Migrated by tbx_to_qgis.py
        email=
        about=Auto-generated migration scaffold. Review all TODO comments before production use.
        tracker=
        repository=
        hasProcessingProvider=yes
        tags=migration, arcgis
        homepage=
        category=Analysis
        icon=
        experimental=True
        deprecated=False
        """)


def _generate_requirements() -> str:
    return textwrap.dedent("""\
        # Pinned for QGIS 3.44 / Python 3.12
        geopandas>=0.14.0
        pyogrio>=0.7.0
        numpy>=1.26.0
        rasterio>=1.3.0
        """)


def _generate_test(tool: TbxTool, tool_class: str, plugin_dir: pathlib.Path) -> str:
    alg_module = _to_snake(tool_class)  # must match algorithm filename
    fn_name = _to_snake(tool.internal_name)  # concise test function name
    return (
        f"# -*- coding: utf-8 -*-\n"
        f"# AUTO-GENERATED test stub for {tool_class}\n"
        f"# Run with: pytest {plugin_dir.name}/tests/test_{fn_name}.py\n"
        f"import pytest\n"
        f"\n"
        f"\n"
        f"def test_{fn_name}_import():\n"
        f'    \"\"\"Verify the algorithm class can be imported without errors.\"\"\"\n'
        f"    from processing_provider.{alg_module}_algorithm import {tool_class}\n"
        f"    alg = {tool_class}()\n"
        f"    assert alg.name() == '{fn_name}'\n"
        f"\n"
        f"\n"
        f"def test_{fn_name}_parameters():\n"
        f'    \"\"\"Verify parameter count matches expected.\"\"\"\n'
        f"    from processing_provider.{alg_module}_algorithm import {tool_class}\n"
        f"    alg = {tool_class}()\n"
        f"    alg.initAlgorithm()\n"
        f"    assert len(alg.parameterDefinitions()) == {len(tool.parameters)}\n"
    )


def _generate_migration_report(tbx: TbxToolbox, out_dir: pathlib.Path) -> str:
    lines = [
        f"# Migration Report — {tbx.name}",
        f"",
        f"**Generated:** {date.today().isoformat()}  ",
        f"**Source:** `{tbx.path.name}`  ",
        f"**Tools:** {len(tbx.tools)}  ",
        f"**Total parameters:** {sum(len(t.parameters) for t in tbx.tools)}  ",
        f"",
        f"---",
        f"",
    ]

    for tool in tbx.tools:
        conf = _tool_confidence(tool)
        is_model = tool.tool_type in (1, 2)
        conf_label = (
            "Production-ready" if conf >= 0.95 else
            "Code + assumptions review" if conf >= 0.85 else
            "Code + manual verification" if conf >= 0.70 else
            "Pseudocode + research required" if conf >= 0.50 else
            "Analysis only"
        )
        lines += [
            f"## Tool: {tool.display_name}",
            f"",
            f"| Property | Value |",
            f"|---|---|",
            f"| Internal name | `{tool.internal_name}` |",
            f"| Tool type | `{tool.tool_type}` ({'ModelBuilder' if is_model else 'Script'}) |",
            f"| Parameters | {len(tool.parameters)} |",
            f"| Confidence | **{conf:.2f}** — {conf_label} |",
            f"",
        ]

        if is_model:
            lines += [
                f"> ⚠ **ModelBuilder tool**: Execute logic is not encoded in the binary `.tbx` stream.",
                f"> The `initAlgorithm()` scaffold has been generated from the parameter inventory.",
                f"> To recover the full logic, export the model in ArcMap:",
                f"> **Model menu → Export → To Python Script…** and port the resulting ArcPy calls",
                f"> using the Phase 3 crosswalk tables in `.vscode/arcgis_migration.instructions.md`.",
                f"",
            ]

        lines += [
            f"### Parameters",
            f"",
            f"| # | Name | Direction | ArcGIS Type | QGIS Type | Confidence | Notes |",
            f"|---|---|---|---|---|---|---|",
        ]
        for p in tool.parameters:
            pc = _param_confidence(p)
            warn = "⚠ " if p.qgis_type.startswith("⚠") else ""
            note = p.qgis_note or ("Parse error — manual review required" if p.internal_name.startswith("__parse_error") else "")
            lines.append(
                f"| {p.index} | `{p.internal_name}` | {p.direction} | `{p.gp_class}` "
                f"| `{warn}{p.qgis_type}` | {pc:.2f} | {note} |"
            )

        lines += ["", "---", ""]

    # Histogram
    all_confs = [_param_confidence(p) for t in tbx.tools for p in t.parameters]
    if all_confs:
        buckets = {"≥0.95": 0, "0.85–0.94": 0, "0.70–0.84": 0, "0.50–0.69": 0, "<0.50": 0}
        for c in all_confs:
            if c >= 0.95:   buckets["≥0.95"] += 1
            elif c >= 0.85: buckets["0.85–0.94"] += 1
            elif c >= 0.70: buckets["0.70–0.84"] += 1
            elif c >= 0.50: buckets["0.50–0.69"] += 1
            else:           buckets["<0.50"] += 1

        lines += [
            "## Confidence Histogram",
            "",
            "```",
        ]
        max_count = max(buckets.values()) or 1
        bar_width = 30
        for tier, count in buckets.items():
            bar = "█" * int(count / max_count * bar_width)
            lines.append(f"  {tier:12s} {bar:<{bar_width}} {count}")
        lines += ["```", ""]

    # Next steps
    lines += [
        "## Next Steps",
        "",
        "- [ ] Review all `# TODO` comments in generated algorithm files",
        "- [ ] Fill in `processAlgorithm()` for each tool using Phase 3 crosswalk tables",
        "- [ ] Run generated test stubs against sample data",
        "- [ ] Execute side-by-side ArcGIS vs. QGIS output comparison",
        "- [ ] Update any parameter types marked ⚠ UNMAPPED",
        "- [ ] Deploy and test in QGIS 3.44 LTR environment",
        "",
    ]

    return "\n".join(lines)


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_plugin(
    tbx_path: str | pathlib.Path,
    out_root: str | pathlib.Path = "qgis-tools",
    scope: str = "full",
) -> pathlib.Path:
    """Parse a binary .tbx and generate a QGIS Processing Plugin scaffold.

    Args:
        tbx_path:  Path to the binary .tbx file.
        out_root:  Root output directory (default: qgis-tools/).
        scope:     One of 'full', 'scaffold-only', 'report-only'.

    Returns:
        Path to the generated plugin directory.
    """
    tbx = parse_tbx(tbx_path)
    tbx_path = pathlib.Path(tbx_path)

    plugin_name = tbx.name or tbx_path.stem
    plugin_id = _to_snake(plugin_name)
    plugin_dir = pathlib.Path(out_root) / f"{plugin_id}_plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)

    provider_class = _to_pascal(plugin_name) + "Provider"
    tool_classes = [_to_pascal(t.display_name or t.internal_name) for t in tbx.tools]

    proc_dir = plugin_dir / "processing_provider"
    proc_dir.mkdir(exist_ok=True)

    tests_dir = plugin_dir / "tests"
    tests_dir.mkdir(exist_ok=True)

    if scope in ("full", "scaffold-only"):
        # metadata.txt
        (plugin_dir / "metadata.txt").write_text(_generate_metadata(plugin_name, tbx), encoding="utf-8")
        # __init__.py (root)
        (plugin_dir / "__init__.py").write_text(_generate_init(plugin_name), encoding="utf-8")
        # main_plugin.py
        (plugin_dir / "main_plugin.py").write_text(_generate_main_plugin(plugin_name, provider_class), encoding="utf-8")
        # processing_provider/__init__.py
        (proc_dir / "__init__.py").write_text("# -*- coding: utf-8 -*-\n", encoding="utf-8")
        # processing_provider/provider.py
        (proc_dir / "provider.py").write_text(_generate_provider(tool_classes, plugin_name, plugin_id), encoding="utf-8")
        # tests/__init__.py
        (tests_dir / "__init__.py").write_text("# -*- coding: utf-8 -*-\n", encoding="utf-8")

        for tool, tool_class in zip(tbx.tools, tool_classes):
            alg_name = _to_snake(tool_class) + "_algorithm"  # matches provider import
            alg_code = _generate_algorithm(tool, plugin_name, tool_class)
            (proc_dir / f"{alg_name}.py").write_text(alg_code, encoding="utf-8")

        if scope == "full":
            # requirements.txt
            (plugin_dir / "requirements.txt").write_text(_generate_requirements(), encoding="utf-8")
            # tests
            for tool, tool_class in zip(tbx.tools, tool_classes):
                test_code = _generate_test(tool, tool_class, plugin_dir)
                (tests_dir / f"test_{_to_snake(tool.internal_name)}.py").write_text(test_code, encoding="utf-8")

    if scope in ("full", "report-only"):
        report = _generate_migration_report(tbx, plugin_dir)
        (plugin_dir / "migration_report.md").write_text(report, encoding="utf-8")

    return plugin_dir


def _cli():
    parser = argparse.ArgumentParser(
        description="Generate a QGIS 3.44 Processing Plugin scaffold from a binary ArcGIS .tbx file."
    )
    parser.add_argument("tbx", help="Path to the binary .tbx file")
    parser.add_argument("--out", default="qgis-tools", help="Output root directory (default: qgis-tools)")
    parser.add_argument(
        "--scope",
        choices=["full", "scaffold-only", "report-only"],
        default="full",
        help="Generation scope (default: full)",
    )
    args = parser.parse_args()

    out_dir = generate_plugin(args.tbx, out_root=args.out, scope=args.scope)
    print(f"✓ Plugin scaffold written to: {out_dir}")

    # Summary
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from tbx_parser import parse_tbx as _pt
    tbx = _pt(args.tbx)
    for tool in tbx.tools:
        conf = _tool_confidence(tool)
        print(f"  Tool: {tool.display_name!r}  confidence={conf:.2f}  params={len(tool.parameters)}")


if __name__ == "__main__":
    _cli()
