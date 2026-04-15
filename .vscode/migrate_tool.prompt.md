---
description: "Migrate an ArcGIS tool to a QGIS 3.44 Processing Plugin"
agent: migrate-arc
---

# Migrate ArcGIS Tool → QGIS 3.44 Processing Algorithm

Migrate the attached ArcGIS source file to a **production-ready QGIS 3.44.0 LTR Processing
algorithm**. Follow the steps below in sequence. Do not skip steps.

---

## ⛔ FILE SCOPE MANDATE — Read This Before Any Other Step

This migration is scoped **exclusively** to the **single file the user named or attached**.
This rule applies from the very first tool call and governs every file-access decision
throughout all steps.

- **DO NOT** call `list_dir`, `file_search`, `grep_search`, or `read_file` on any file other
  than the one explicitly named — not for context, not to infer execute logic, not out of
  general helpfulness.
- **DO NOT** associate sibling files in the same folder as the named file. A `.py` file
  sitting next to a `.tbx` is **not** assumed to be related, regardless of how similar the
  names look.
- **Script tools (`tool_type == 3`):** A companion script is only in scope if
  `tool.script_path` in the parser output **exactly** names it. If `script_path` is empty or
  null, **stop and ask the user** — do not search.
- **ModelBuilder tools (`tool_type == 1` or `2`):** Execute logic is structurally absent from
  the binary. **Do not search for any file to recover it.** Stub `processAlgorithm()` with
  TODOs and direct the user to export via ModelBuilder → Export → To Python Script.
- If you need a file that is not the named file, **ask the user to provide it explicitly**.
  Never guess, infer, or explore.

Violating this mandate produces incorrect output. When in doubt: stub and ask.

---

## Step 0 — Binary `.tbx` Detection Gate

**Run this check first, before any other step, whenever a `.tbx` file is provided.**

Inspect the first four bytes of the file:

| First bytes (hex) | Format | Action |
|---|---|---|
| `3C 47 50 54` or `3C 3F 78 6D` | XML (ArcGIS Pro / ModelBuilder XML) | Skip to Step 1 — file is readable |
| `D0 CF 11 E0` | Binary OLE Compound File (ArcGIS Desktop / ArcMap) | **Run `tbx_parser.py` fast-path below** |

### If binary OLE — run `tbx_parser.py` immediately (no ArcGIS required)

This workspace contains a standalone binary `.tbx` parser at `research/tbx_parser.py`.
**Always try this first.** It requires no ArcGIS installation, no COM layer, and runs in the
workspace `.venv`:

```python
import sys
sys.path.insert(0, 'research')
from tbx_parser import parse_tbx

tbx = parse_tbx('<path_to_named_file>')
for tool in tbx.tools:
    print(tool.display_name, tool.tool_type, [p.internal_name for p in tool.parameters])
```

**If `parse_tbx()` succeeds** (no exception, at least one tool parsed without all-error
parameters) — skip the fallback paths below and proceed directly to **Step 1**.

### Fallback paths — only if `tbx_parser.py` fails

Use these paths **only if** `parse_tbx()` raises an exception or every tool in the result
carries `__parse_error_` parameters indicating the stream could not be decoded.

**Path A — ArcMap available: `tbx-pyt-translator` (automated)**

```cmd
git clone https://github.com/Esri/tbx-pyt-translator.git C:\Tools\tbx-pyt-translator
"<C:\Python27\ArcGIS10.8\python.exe>" -c "import sys; sys.path.insert(0, r'C:\Tools\tbx-pyt-translator'); import tbxtopyt; tbxtopyt.export_tbx_to_pyt(r'<full_path.tbx>', r'<workspace_folder>\<tool_name>.pyt')"
```

Requires ArcGIS Desktop 10.1+ and Python 2.7. Does NOT work with ArcGIS Pro, Linux, or Docker.
Once the `.pyt` is saved, re-run with that file → Step 1 (Phase 1.4 `.pyt` parser).

**Path B — ArcMap unavailable: Manual ModelBuilder export**

In ArcMap/ArcCatalog: right-click model → **Edit** → **Model menu → Export → To Python Script…**  
In ArcGIS Pro: ModelBuilder ribbon → **Export → Export To Python Script**  
Save the `.py` to the workspace → re-run with that file → Step 1 (Phase 1.5 standalone `.py` parser).

> ⚠️ `ghcr.io/esri/arcgis-python-api-notebook` (Docker) cannot run Path A — it has no `arcpy`
> and the Windows COM wrappers are unavailable on Linux.

---

## Workspace Directory Convention
- **Source files** — Read **only** the single file explicitly named by the user. Never read,
  open, or list any other file. Never modify originals.
- **All generated output** goes into a `<tool_name>_plugin/` directory. Never write into the
  source file's folder or the workspace root.

## Shared Geoprocessing Guardrails

For migration decisions that involve distance units, CRS handling, schema safety, or
post-run QA, apply the shared policy documents:

- [Authoritative Shared Guardrails](./geoprocessing_guardrails.instructions.md)
- [Repository Mirror](../.github/geoprocessing-guardrails.md)

---

## Output Scope

The user may request a subset. Default is `full`.

| Scope | Deliverables |
|---|---|
| `full` (default) | Plugin scaffold + tests + migration report + `requirements.txt` |
| `scaffold-only` | Plugin directory only (metadata.txt, `__init__.py`, provider, algorithm) |
| `tests-only` | pytest stubs + validation scripts only |
| `report-only` | Migration report with confidence scoring only (no code generation) |

---

## Step 1 — Triage Gate

> **⚠️ FILE SCOPE — Before doing anything else:** This migration is scoped **exclusively** to
> the single file the user named or attached. Do NOT read, open, reference, or associate any
> other file found anywhere in the workspace — for **any reason**: not to identify an embedded
> script, not to infer or reconstruct execute logic, not to understand the tool's purpose,
> not for context. The tool name or display name resembling a sibling file is **not** grounds
> for reading that file.
>
> - **Script tools (`tool_type == 3`):** Only use a script file if `tool.script_path` in the
>   parser output **explicitly** names it. If `script_path` is empty or null, ask the user —
>   do not guess and do not search for files.
> - **ModelBuilder tools (`tool_type == 1` or `2`):** Execute logic is structurally absent.
>   Do NOT search for any file to recover it. Stub with TODOs and direct the user to export.

Before writing any code, classify and report:

1. **File type** — inspect the first 4 bytes and file extension to route correctly:

   | First bytes | Extension | Classification | Parser |
   |---|---|---|---|
   | `D0 CF 11 E0` | `.tbx` | Binary OLE (ArcMap) | `research/tbx_parser.py` — see §1a below |
   | `3C 47 50 54` or `3C 3F 78 6D` | `.tbx` | XML ModelBuilder | XML DAG parser |
   | Valid ZIP | `.atbx` | ArcGIS Pro JSON | ZIP/JSON parser |
   | Python source with `getParameterInfo` | `.pyt` | Python Toolbox | AST parser — see §1b |
   | Python source with `import arcpy` | `.py` | Standalone ArcPy | AST + regex parser |

2. **Python version** — Scan for Python 2.7 patterns (`print x`, `unicode`, `iteritems`,
   `except E, e`, `arcpy.mapping.*`). List every match found.
3. **License tier** — Identify Basic / Standard / Advanced requirements.
4. **Extension dependencies** — Flag Spatial Analyst, 3D Analyst, Network Analyst, Data
   Interoperability, Image Analyst, Publisher, or Geodatabase/SDE usage.
5. **Confidence ceilings** — Set per-extension ceilings from the License Tier Classifier.
6. **Hardcoded paths** — List every string literal matching `[A-Z]:\\` or `\\\\server\\`.

### §1a — Binary `.tbx` fast-path via `tbx_parser`

For binary OLE `.tbx` files, **do not** wait for `tbx-pyt-translator` or manual export.
Use the standalone parser already in this workspace:

```python
import sys
sys.path.insert(0, 'research')
from tbx_parser import parse_tbx

tbx = parse_tbx('<path_to_named_file>')
for tool in tbx.tools:
    print(tool.display_name, [p.internal_name for p in tool.parameters])
```

`parse_tbx()` returns a `TbxToolbox` with:
- `tbx.name` / `tbx.alias` — toolbox identity
- `tbx.tools` — list of `TbxTool` (index, internal_name, display_name, description, tool_type, parameters)
- `tool.parameters` — list of `TbxParameter` with:
  - `internal_name`, `display_name`, `direction` ("Input"/"Output")
  - `gp_class` — original ArcGIS type string (e.g. `"GPFeatureLayer"`)
  - `qgis_type` — mapped `QgsProcessingParameter*` class name
  - `qgis_note` — migration guidance note
  - Any parameter prefixed `__parse_error_N__` needs manual review

`tool_type` values: `1` = ModelBuilder, `2` = ModelBuilder variant, `3` = Script tool.
Script tools (type 3) have a `tool.script_path` pointing to the embedded `.py`.

**After parsing, skip Path A / Path B of Step 0 and proceed directly to Step 2.**

### §1b — `.pyt` Python Toolbox (pass-through — no binary decoding needed)

`.pyt` files are plain Python. Read them directly — **no pre-processing required**:

```python
import ast, pathlib
tree = ast.parse(pathlib.Path('<path_to_named_file>').read_text(encoding='utf-8'))
# Walk tree to find classes with getParameterInfo methods
```

Extract the `Toolbox` class (`self.tools` list) and each tool class's:
- `getParameterInfo()` — `arcpy.Parameter` objects → map to `QgsProcessingParameter*`
- `execute()` — ArcPy calls → crosswalk against Phase 3 tables
- `isLicensed()`, `updateParameters()`, `updateMessages()` — port as QGIS lifecycle hooks

Proceed directly to Step 2 after AST extraction.

**Output:** Present a triage summary table before proceeding. Wait for confirmation if any
`DL_MODEL_MIGRATION` flags or confidence ceilings below 0.50 are detected.

---

## Step 2 — Parse & Inventory

Extract the tool's structure using the appropriate parser (routed in Step 1):

- **Binary `.tbx`** — Results already in hand from `parse_tbx()` (Step §1a). Use `TbxToolbox` directly.
- **XML `.tbx`** — Parse XML DAG → topological sort of `<GPConnections>` → map `<GPProcesses>`.
- **`.atbx`** — Unzip → read JSON metadata → locate embedded code or linked `.py`.
- **`.pyt`** — AST-parse `getParameterInfo` → map `arcpy.Parameter` objects (Step §1b).
- **`.py`** — Extract parameters (argparse → sys.argv → hardcoded vars) → AST-walk `arcpy.*` calls.

**Output:**
- Tool purpose summary (2–3 sentences).
- Parameter inventory table: name, ArcPy type, direction (input/output), default value.
- Complete list of `arcpy.*` tool calls with line numbers.
- Execution flow diagram (ordered list of operations).

---

## Step 3 — Optimization Strategy

State the migration approach explicitly before generating code:

1. For each `arcpy.*` call, identify the crosswalk entry from the Phase 3 tables.
2. Choose between `native:` C++ algorithms and vectorized Python libraries.
3. Flag any row-wise cursor loops for vectorization with geopandas + pyogrio.
4. Identify any calls with no direct equivalent (confidence < 0.70).
5. For any distance-based operation, explicitly define meter-normalized computational flow,
   CRS-unit conversion path, and display-unit formatting path.

**Output format:**
> "The source uses [License Tier] tools: [list]. I will implement using:
> - `native:difference` for Erase_analysis (confidence: 0.95)
> - geopandas vectorized ops for UpdateCursor loop (confidence: 0.90)
> - [etc.]
>
> Blocks requiring careful review: [list with rationale]."

---

## Step 4 — Generate Plugin Scaffold

Create the full QGIS Processing Plugin directory:

```
<tool_name>_plugin/
├── metadata.txt
├── __init__.py
├── main_plugin.py
├── requirements.txt
├── migration_report.md
├── tests/
└── processing_provider/
    ├── __init__.py
    ├── provider.py
    └── <tool_name>_algorithm.py
```

**Rules for generated code:**
- `metadata.txt`: set `hasProcessingProvider=yes`, `qgisMinimumVersion=3.44`.
- `__init__.py`: include `classFactory()` boilerplate.
- `provider.py`: inherit `QgsProcessingProvider`, register all algorithms.
- Algorithm file:
  - `initAlgorithm()` — all parameters as `QgsProcessingParameter*` classes.
  - `processAlgorithm()` — core logic using `processing.run("native:*", ...)` where possible.
  - `self.parameterAsSource()` / `self.parameterAsRasterLayer()` for data access using QGIS native API.
  - **CRITICAL for Geopandas/Pyogrio**: Do NOT use `self.parameterDefinition().valueAsString()` to get file paths, as it may return stringified tuples like `"('path.shp', True)"`. To pass a QGIS Feature Source to Geopandas, use:
    ```python
    layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
    file_path = layer.dataProvider().dataSourceUri().split('|')[0] 
    ```
  - `self.parameterAsSink()` + `QgsProcessing.TEMPORARY_OUTPUT` for all intermediates.
  - `feedback.pushInfo(...)` for all status messages.
  - **ZERO** hardcoded paths — every path elevated to a Processing parameter.
  - **NO** Python 2 syntax — pure Python 3.12.
  - **NO** row-wise loop transliterations — vectorize with geopandas + pyogrio.
  - **Distance safety is mandatory**:
    - Apply shared guardrail policy from `.vscode/geoprocessing_guardrails.instructions.md`.
    - Normalize computational lengths to meters.
    - When using `QgsDistanceArea.measureLength()`, if `willUseEllipsoid()` is false,
      convert CRS-native units to meters before any threshold/segment math.
    - Use `QgsUnitTypes.fromUnitToUnitFactor` and support US survey units (`FeetUSSurvey`, `MilesUSSurvey`).
    - Never treat degree-based lengths as meters.

---

## Step 5 — Confidence Scoring

Wrap **every** migrated code block in a `<migration_block>` with:

- Block ID and source line range.
- Original ArcPy code.
- Migrated QGIS code.
- Weighted confidence score (API Parity 35%, Parameter Fidelity 25%, Output Compatibility 20%,
  Manual Effort 10%, Testing Complexity 10%).
- Assumptions & caveats (bullet list).
- Suggested validation test.
- Fallback implementation (for blocks scoring ≤ 0.84).

**Threshold actions:**
- ≥ 0.95 → Production-ready code.
- 0.85–0.94 → Code + highlighted assumptions + test stub.
- 0.70–0.84 → Code + side-by-side diff + fallback option.
- 0.50–0.69 → Pseudocode sketch + research links + manual TODO.
- < 0.50 → Analysis only + closest alternative + rationale.

**DL_MODEL_MIGRATION exception:** For `DetectObjectsUsingDeepLearning` or
`ClassifyPixelsUsingDeepLearning`, emit a `DL_MODEL_MIGRATION` block with a model porting
guide instead of standard scoring.

---

## Step 6 — Migration Report

Append a **Migration Quality Summary** at the end:

- Confidence histogram (ASCII bar chart by tier).
- Risk assessment (block counts and percentages per tier).
- Estimated manual review effort (hours).
- Next steps checklist:
  - [ ] Review flagged high-risk blocks
  - [ ] Run provided test suite on sample data
  - [ ] Execute side-by-side ArcGIS vs. QGIS comparison
  - [ ] Update assumptions if field-testing reveals mismatches
  - [ ] Deploy to production QGIS 3.44 environment

---

## Step 7 — Artifacts

Generate these additional files alongside the plugin scaffold:

1. **`requirements.txt`** — All Python dependencies (geopandas, pyogrio, rasterio, numpy, etc.).
   Pin to minimum compatible versions for QGIS 3.44 / Python 3.12.
2. **`tests/`** directory with pytest stubs:
   - One test file per algorithm.
   - Test cases for each `<migration_block>` validation test.
   - Geometry comparison helpers with configurable tolerance.
3. **Side-by-side diff** — For every block scoring ≤ 0.84, include a formatted diff showing
   original ArcPy vs. migrated QGIS code with inline annotations.

---

## Quick Start

1. Attach or reference the ArcGIS source file (`.py`, `.pyt`, `.tbx`, or `.atbx`).
2. Optionally specify an output scope: `scaffold-only`, `tests-only`, `report-only`, or `full`.
3. The agent will execute Steps 1–7 and deliver all artifacts.

> **Example invocation:**
> "Migrate the attached `flood_analysis.pyt` to QGIS. Output scope: full."
