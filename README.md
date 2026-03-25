# QgisPortAgent

A VS Code GitHub Copilot agent ecosystem for **QGIS 3.44 LTR** development — migrate ArcGIS tools autonomously **or** create new QGIS plugins from concept to production, all without leaving your editor.

---

## Agents in This Repository

| Agent | Purpose | Use When |
|---|---|---|
| **`@migrate-arc`** | Migrate ArcGIS tools to QGIS Processing algorithms | You have existing ArcGIS toolboxes (`.atbx`, `.tbx`, `.pyt`, `.py`) to port |
| **`@new-plugin.md`** | Create new QGIS plugins from scratch | You want to build custom QGIS functionality (analysis tools, UI extensions, data connectors) |

Both agents produce production-ready QGIS plugins with full test suites, documentation, and packaging scripts.

---

## 🔄 Migrating ArcGIS Tools

### What it does

Point the `@migrate-arc` agent at any ArcGIS tool file and it produces a ready-to-install QGIS Processing Plugin with:

- Full `QgsProcessingAlgorithm` scaffold (`initAlgorithm`, `processAlgorithm`, lifecycle hooks)
- Per-block confidence scores using a 5-component weighted model
- Vectorised data access (geopandas + pyogrio — no row-wise cursor transliterations)
- Open-source replacements for every licensed ArcGIS extension
- Migration report with risk assessment and estimated review effort

---

### Supported Source Formats

| Format | Extension | Parser | Notes |
|---|---|---|---|
| ArcGIS Pro Modern Toolbox | `.atbx` | ZIP + JSON | Full parameter + execute logic |
| ArcMap Binary Toolbox | `.tbx` (OLE) | `research/tbx_parser.py` | No ArcGIS required; 143-entry GP type map |
| ArcGIS Desktop XML Toolbox | `.tbx` (XML) | ElementTree | ModelBuilder DAGs |
| Python Toolbox | `.pyt` | `ast.parse()` | Full parameter + execute logic |
| Standalone ArcPy Script | `.py` | AST + regex | Full execute logic |

All five formats are supported without any ArcGIS or COM dependency.

---

### Prerequisites

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

### Quick Start — Migration

#### Option 1 — GitHub Copilot Chat (recommended)

Open Copilot Chat in Agent mode and type:

```
@migrate-arc migrate examples/pyt/field_calculator_example/FieldCalculatorTools.pyt
```

Or reference the structured prompt template:

```
/migrate_tool examples/tbx_binary/pointtools/PointTools.tbx
```

#### Option 2 — Command palette prompt

1. Open the source ArcGIS file in VS Code
2. Open Copilot Chat (`Ctrl+Alt+I`)
3. Switch to **Agent mode** and select `migrate-arc`
4. Type: `Migrate the open file`

#### Option 3 — CLI (research scripts)

```bash
cd <your-workspace>
.venv\Scripts\activate
python research/tbx_to_qgis.py "examples/tbx_binary/pointtools/PointTools.tbx"
```

Output is written to `qgis-tools/<tool_name>_plugin/`.

---

### Example Files

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

### How Migration Works

The agent runs a 7-step pipeline defined in `.vscode/migrate_tool.prompt.md`:

1. **Format detection** — checks first 4 bytes (binary OLE) or file structure (ZIP, XML, Python)
2. **Parsing** — extracts parameters, execute logic, and tool metadata
3. **Python 2.7 scan** — detects and rewrites legacy syntax before generating any output
4. **License crosswalk** — maps every `arcpy.*` call to an open-source equivalent
5. **Code generation** — emits a full QGIS Processing Plugin scaffold
6. **Confidence scoring** — scores each migrated block across 5 components (API parity, parameter fidelity, output compatibility, manual effort, testing complexity)
7. **Report generation** — writes `migration_report.md` with histogram, risk assessment, and next steps

---

## 🆕 Creating New QGIS Plugins from Scratch

### What it does

The `@new-plugin.md` agent guides you from concept to production-ready QGIS 3.44 LTR plugin through an interactive 8-step workflow:

- **Concept elicitation** through structured conversation
- **Automatic archetype classification** (Processing Provider, Interactive Tool, Data Connector, UI Extension, etc.)
- **Complete plugin scaffolding** with PyQGIS best practices baked in
- **Full implementation** of core functionality, UI, and data access patterns
- **Comprehensive test suite** (pytest + fixtures)
- **User and API documentation** (Markdown + docstrings)
- **Distribution packaging** with metadata validation and zip creation

---

### Quick Start — Plugin Creation

#### Option 1 — Natural Language Description (recommended)

Open Copilot Chat in Agent mode and describe your plugin idea:

```
@qgis-plugin-builder I want to create a plugin that downloads weather data from a public API and displays it as a heatmap layer in QGIS.
```

The agent will guide you through:
1. Discovery questions to understand your requirements
2. Architecture design and archetype selection
3. Complete code generation for all components
4. Testing and documentation setup
5. Packaging for distribution

#### Option 2 — Use the Prompt Template

Reference the structured prompt:

```
/create_plugin
```

Then answer the discovery questions about:
- Plugin purpose and target users
- Data types and spatial operations
- UI requirements
- External integrations
- Performance needs
- Deployment strategy

#### Example Invocation

**User:**
> Create a plugin that calculates viewshed analysis from multiple observer points and exports results as a heatmap.

**Agent Response:**

The agent will:
1. ✅ Ask discovery questions (data types, UI preferences, performance needs)
2. ✅ Classify as **Hybrid** archetype (Processing Provider + Visualization)
3. ✅ Generate complete plugin structure in `<plugin_name>/`
4. ✅ Implement viewshed algorithm using QGIS native processing
5. ✅ Implement heatmap renderer for results visualization
6. ✅ Create pytest test suite with fixtures
7. ✅ Write `user_guide.md`, `README.md`, and API docstrings
8. ✅ Package plugin as `dist/<plugin_name>.zip`

---

### Plugin Archetypes

The agent automatically selects the optimal archetype based on your requirements:

| Archetype | Use When | Key Components | Examples |
|---|---|---|---|
| **Processing Provider** | Batch geoprocessing or analysis workflows | `QgsProcessingAlgorithm`, Processing Toolbox integration | Zonal statistics, batch geocoding, spatial joins |
| **Interactive Tool** | Custom map interaction (click, draw, measure) | `QgsMapTool`, canvas events, rubber bands | Custom digitizing, spatial queries, measurement tools |
| **Data Connector** | Import/export from external data sources | REST clients, database adapters, file parsers | Weather data loader, CityGML importer, PostGIS sync |
| **UI Extension** | Add dialogs, panels, or menus to QGIS | `QDialog`, `QDockWidget`, toolbar actions | Layer manager, metadata editor, project templates |
| **Automation/Workflow** | Task automation, batch processing | `QgsTask`, batch runners, project manipulation | Automated map series, bulk export, quality checks |
| **Visualization** | Custom renderers, symbology, dynamic styling | `QgsFeatureRenderer`, expression functions | Heatmaps, flow maps, time-series visualization |
| **Hybrid** | Multiple capabilities combined | Coordinated components via main plugin class | Analysis tool + custom renderer + data connector |

---

### The 8-Step Workflow

| Step | Phase | What Happens |
|---|---|---|
| **0** | **Concept Discovery** | Agent asks structured questions to understand requirements |
| **1** | **Architecture Design** | Archetype classification, directory structure, dependency planning |
| **2** | **Plugin Scaffold** | Complete directory tree, `metadata.txt`, `__init__.py`, resources |
| **3** | **Core Implementation** | Processing algorithms, UI components, map tools, data connectors |
| **4** | **Error Handling** | Input validation, exception handling, user feedback |
| **5** | **Testing** | pytest suite with unit and integration tests, ≥80% coverage target |
| **6** | **Documentation** | User guide, API docstrings, README, installation instructions |
| **7** | **Packaging** | `metadata.txt` validation, zip creation, pre-release checklist |
| **8** | **Handoff** | Deliverables summary, testing workflow, next steps |

---

### Where Plugins Are Created

Generated plugins are created as standalone directories in your workspace:

```
<your-workspace>/
├── <plugin_name>/
│   ├── metadata.txt
│   ├── __init__.py
│   ├── <plugin_name>_plugin.py
│   ├── processing_provider/        # For Processing Provider archetypes
│   ├── map_tools/                  # For Interactive Tool archetypes
│   ├── ui/                         # For UI Extension archetypes
│   ├── data_sources/               # For Data Connector archetypes
│   ├── resources/
│   ├── tests/
│   ├── docs/
│   ├── scripts/
│   │   └── package_plugin.py
│   └── dist/
│       └── <plugin_name>.zip
```

Each plugin is self-contained and ready to install in QGIS.

---

### Installing a Created Plugin

After the agent generates your plugin:

1. **Locate the plugin directory** in your workspace
2. **Copy it to your QGIS plugins folder:**

   **Windows**: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`  
   **Linux/macOS**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

3. **Restart QGIS** and enable the plugin: **Plugins → Manage and Install Plugins → Installed**

#### Development Workflow — Live Symlink (Windows)

For active development, create a directory junction so code changes are immediately reflected:

```bat
mklink /J "%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\<plugin_name>" "<your-workspace>\<plugin_name>"
```

Install **Plugin Reloader** from the QGIS Plugin Repository and press **F5** after each code change.

---

## Output Structure

### Migrated Plugins (from ArcGIS)

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

### Created Plugins (from scratch)

Each new plugin is created as a standalone directory with archetype-specific components:

```
<plugin_name>/
├── metadata.txt
├── __init__.py
├── <plugin_name>_plugin.py
├── [archetype-specific subdirectories]
├── resources/
├── tests/
├── docs/
├── scripts/
└── dist/
```

---

## Repository Structure

```
QgisPortAgent/
├── .github/
│   └── agents/
│       ├── migrate-arc.agent.md       # Migration agent definition
│       └── new-qgis-plugin.agent.md    # Plugin builder agent definition
├── .vscode/
│   ├── arcgis_migration.instructions.md    # Ambient migration rules (Phases 0–6)
│   ├── migrate_tool.prompt.md              # /migrate_tool prompt template
│   ├── qgis_plugin_builder.instructions.md # Ambient plugin builder rules (Phases 0–8)
│   └── create_plugin.prompt.md             # /create_plugin prompt template
├── examples/                               # Sample ArcGIS source files for testing
│   ├── py/                                 # Standalone .py scripts
│   ├── atbx/                               # Modern ArcGIS Pro toolboxes
│   ├── pyt/                                # Python Toolboxes
│   └── tbx_binary/                         # Binary ArcMap OLE toolboxes
├── qgis-tools/                             # Migration output (generated plugins land here)
├── research/
│   ├── tbx_parser.py                       # Standalone binary .tbx OLE parser
│   ├── tbx_to_qgis.py                      # Plugin generator
│   ├── requirements.txt                    # Parser dependencies (olefile)
│   └── corpus/                             # Binary .tbx test corpus
├── test/                                   # Integration test data
└── README.md
```

---

## Customising the Agents

### Migration Agent (`@migrate-arc`)

#### Adjusting confidence thresholds

Edit `.vscode/arcgis_migration.instructions.md` → Phase 6.2 (Threshold → Action Table).

#### Adding new GP type mappings

Edit `research/tbx_parser.py` → `GP_TYPE_MAP` dictionary (currently 143 entries).

#### Extending the crosswalk tables

Edit `.vscode/arcgis_migration.instructions.md` → Phase 3 (Licensing & Extension Crosswalk Tables).

#### Changing the target QGIS version

Search-and-replace `3.44` across `.vscode/arcgis_migration.instructions.md`,
`.vscode/migrate_tool.prompt.md`, and `.github/agents/migrate-arc.agent.md`.

---

### Plugin Builder Agent (`@new-plugin.md`)

#### Customizing code generation templates

Edit `.vscode/qgis_plugin_builder.instructions.md` → Phase 2 (PyQGIS Core Patterns).

#### Adding new plugin archetypes

Edit `.vscode/qgis_plugin_builder.instructions.md` → Phase 0.2 (Plugin Archetype Classification).

#### Adjusting documentation style

Edit `.vscode/qgis_plugin_builder.instructions.md` → Phase 5 (Documentation Standards).

#### Changing the target QGIS version

Search-and-replace `3.44` across `.vscode/qgis_plugin_builder.instructions.md`,
`.vscode/create_plugin.prompt.md`, and `.github/agents/new-plugin.agent.md`.

---

## Contributing

1. Fork the repository
2. For migration testing: Add your example ArcGIS source file to the appropriate `examples/` subdirectory
3. For plugin builder testing: Create a sample plugin using the agent and document the use case
4. Add a `README.md` describing what scenarios your contribution exercises
5. Run the relevant agent and verify the output
6. Open a pull request

---

## License

MIT — see [LICENSE](LICENSE) for details.