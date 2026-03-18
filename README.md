# QgisPortAgent

A VS Code GitHub Copilot agent that autonomously migrates ArcGIS tools to
**QGIS 3.44 LTR Processing algorithms** — from source file to deployable plugin,
with no ArcGIS installation required.

---

## What it does

Point the agent at any ArcGIS tool file and it produces a ready-to-install QGIS
Processing Plugin with:

- Full `QgsProcessingAlgorithm` scaffold (`initAlgorithm`, `processAlgorithm`, lifecycle hooks)
- Per-block confidence scores using a 5-component weighted model
- Vectorised data access (geopandas + pyogrio — no row-wise cursor transliterations)
- Open-source replacements for every licensed ArcGIS extension
- Migration report with risk assessment and estimated review effort

---

## Supported Source Formats

| Format | Extension | Parser | Notes |
|---|---|---|---|
| ArcGIS Pro Modern Toolbox | `.atbx` | ZIP + JSON | Full parameter + execute logic |
| ArcMap Binary Toolbox | `.tbx` (OLE) | `research/tbx_parser.py` | No ArcGIS required; 143-entry GP type map |
| ArcGIS Desktop XML Toolbox | `.tbx` (XML) | ElementTree | ModelBuilder DAGs |
| Python Toolbox | `.pyt` | `ast.parse()` | Full parameter + execute logic |
| Standalone ArcPy Script | `.py` | AST + regex | Full execute logic |

All five formats are supported without any ArcGIS or COM dependency.

---

## Prerequisites

- **VS Code 1.99+** with **GitHub Copilot** (Agent mode)
- **Python 3.12+** with `olefile` installed (`pip install olefile`)
- **QGIS 3.44 LTR** on the target machine for running the generated plugins

Install the parser dependency:

```bash
pip install olefile
```

Or use the pre-configured virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r research/requirements.txt
```

---

## Quick Start

### Option 1 — GitHub Copilot Chat (recommended)

Open Copilot Chat in Agent mode and type:

```
@arcgis-migration migrate examples/pyt/field_calculator_example/FieldCalculatorTools.pyt
```

Or reference the structured prompt template:

```
/migrate_tool examples/tbx_binary/pointtools/PointTools.tbx
```

### Option 2 — Command palette prompt

1. Open the source ArcGIS file in VS Code
2. Open Copilot Chat (`Ctrl+Alt+I`)
3. Switch to **Agent mode** and select `arcgis-migration`
4. Type: `Migrate the open file`

### Option 3 — CLI (research scripts)

```bash
cd <your-workspace>
.venv\Scripts\activate
python research/tbx_to_qgis.py "examples/tbx_binary/pointtools/PointTools.tbx"
```

Output is written to `qgis-tools/<tool_name>_plugin/`.

---

## Example Files

The `examples/` directory contains real-world ArcGIS tools ready to migrate:

| Directory | File | What it tests |
|---|---|---|
| `examples/py/nrcs_create_watershed/` | `Create_Watershed.py` | Spatial Analyst hydrology, Advanced license |
| `examples/py/nrcs_avg_slope/` | `Calculate_Average_Slope.py` | Standard geoprocessing |
| `examples/atbx/nrcs_engineering_tools/` | `NRCS Engineering Tools.atbx` | Multi-tool ArcGIS Pro toolbox |
| `examples/atbx/fluvial_geomorph/` | `FluvialGeomorph.atbx` | Hydro-geomorphology toolbox |
| `examples/pyt/field_calculator_example/` | `FieldCalculatorTools.pyt` | Python 2.7 patterns, vectorisation |
| `examples/tbx_binary/pointtools/` | `PointTools.tbx` | Binary ArcMap OLE parsing |

See [examples/README.md](examples/README.md) for full details and confidence ranges.

---

## How It Works

The agent runs a 7-step pipeline defined in `.vscode/migrate_tool.prompt.md`:

1. **Format detection** — checks first 4 bytes (binary OLE) or file structure (ZIP, XML, Python)
2. **Parsing** — extracts parameters, execute logic, and tool metadata
3. **Python 2.7 scan** — detects and rewrites legacy syntax before generating any output
4. **License crosswalk** — maps every `arcpy.*` call to an open-source equivalent
5. **Code generation** — emits a full QGIS Processing Plugin scaffold
6. **Confidence scoring** — scores each migrated block across 5 components (API parity, parameter fidelity, output compatibility, manual effort, testing complexity)
7. **Report generation** — writes `migration_report.md` with histogram, risk assessment, and next steps

---

## Output Structure

Each migration produces a plugin directory in `qgis-tools/`:

```
qgis-tools/<tool_name>_plugin/
├── metadata.txt                  # hasProcessingProvider=yes; qgisMinimumVersion=3.44
├── __init__.py                   # classFactory() boilerplate
├── main_plugin.py                # self.initProcessing()
├── requirements.txt              # pinned OSS dependencies
├── migration_report.md           # per-block confidence scores + risk summary
├── tests/
│   └── test_<tool_name>.py       # pytest stubs with sample data
└── processing_provider/
    ├── __init__.py
    ├── provider.py               # QgsProcessingProvider subclass
    └── <tool_name>_algorithm.py  # QgsProcessingAlgorithm subclass
```

---

## Repository Structure

```
QgisPortAgent/
├── .github/
│   └── agents/
│       └── arcgis-migration.agent.md    # Custom Copilot agent definition
├── .vscode/
│   ├── arcgis_migration.instructions.md # Ambient migration rules (Phases 0–6)
│   └── migrate_tool.prompt.md           # /migrate_tool prompt template
├── examples/                            # Sample ArcGIS source files for testing
│   ├── py/                              # Standalone .py scripts
│   ├── atbx/                            # Modern ArcGIS Pro toolboxes
│   ├── pyt/                             # Python Toolboxes
│   └── tbx_binary/                      # Binary ArcMap OLE toolboxes
├── qgis-tools/                          # Migration output (generated plugins land here)
├── research/
│   ├── tbx_parser.py                    # Standalone binary .tbx OLE parser
│   ├── tbx_to_qgis.py                   # Plugin generator
│   ├── requirements.txt                 # Parser dependencies (olefile)
│   └── corpus/                          # Binary .tbx test corpus
├── test/                                # Integration test data
└── README.md
```

---

## Installing a Migrated Plugin

1. Locate the generated directory under `qgis-tools/<tool_name>_plugin/`
2. Copy it to your QGIS plugins folder:

   **Windows**: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`  
   **Linux/macOS**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

3. In QGIS: **Plugins → Manage and Install Plugins → Installed** → enable the plugin
4. The tool appears in **Processing Toolbox** under the provider name

### Development workflow — live symlink (Windows)

To edit plugin code without re-copying, create a directory junction:

```bat
mklink /J "%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\<plugin_name>" "<your-workspace>\qgis-tools\<plugin_name>"
```

Then install **Plugin Reloader** from the QGIS Plugin Repository and press **F5**
after each code change.

---

## Customising the Agent

### Adjusting confidence thresholds

Edit `.vscode/arcgis_migration.instructions.md` → Phase 6.2 (Threshold → Action Table).

### Adding new GP type mappings

Edit `research/tbx_parser.py` → `GP_TYPE_MAP` dictionary (currently 143 entries).

### Extending the crosswalk tables

Edit `.vscode/arcgis_migration.instructions.md` → Phase 3 (Licensing & Extension Crosswalk Tables).

### Changing the target QGIS version

Search-and-replace `3.44` across `.vscode/arcgis_migration.instructions.md`,
`.vscode/migrate_tool.prompt.md`, and `.github/agents/arcgis-migration.agent.md`.

---

## Contributing

1. Fork the repository
2. Add your example ArcGIS source file to the appropriate `examples/` subdirectory
3. Add a `README.md` describing what migration scenarios it exercises
4. Run the migration agent and verify the output in `qgis-tools/`
5. Open a pull request

---

## License

MIT — see [LICENSE](LICENSE) for details.
