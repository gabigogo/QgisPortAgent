# QgisPortAgent

A VS Code GitHub Copilot agent ecosystem for **QGIS 3.44 LTR** — start with an intuitive walkthrough, control QGIS remotely via MCP, migrate ArcGIS tools autonomously, **or** create new QGIS plugins from concept to production, all without leaving your editor.

---

## Getting Started

### Prerequisites

| Requirement | Version | Download | Notes |
|---|---|---|---|
| **QGIS** | 3.44 LTR | [qgis.org/download](https://qgis.org/download/) | OSGeo4W or Standalone both work |
| **VS Code** | 1.101+ | [code.visualstudio.com](https://code.visualstudio.com/) | 1.101 minimum for MCP support |
| **GitHub Copilot** | Latest | [Copilot extension](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot) | Requires active subscription |
| **Python** | 3.12+ | Bundled with QGIS | No separate install needed |

### Setup (one command)

Windows PowerShell:

```powershell
git clone https://github.com/atkinsrealis/QgisPortAgent.git
cd QgisPortAgent
.\setup.ps1
```

Windows Command Prompt:

```cmd
git clone https://github.com/atkinsrealis/QgisPortAgent.git
cd QgisPortAgent
setup.cmd
```

Linux/macOS shell:

```bash
git clone https://github.com/atkinsrealis/QgisPortAgent.git
cd QgisPortAgent
bash ./setup.sh
```

`setup.ps1`, `setup.cmd`, and `setup.sh` will:

1. Auto-detect your QGIS Python interpreter and update VS Code settings
2. Install [`uv`](https://docs.astral.sh/uv/) (Python package runner) if missing
3. Optionally download the [GitHub MCP Server](https://github.com/github/github-mcp-server) binary for manual workspace registration
4. Link source plugins into your QGIS profile via the platform-specific `scripts/setup_plugins` helper

### Cross-platform plugin linking scripts

Windows (junction links):

```powershell
.\scripts\setup_plugins.ps1 -Category source
```

Linux/macOS (symlinks):

```bash
bash scripts/setup_plugins.sh --category source
```

To link generated plugins too:

```powershell
.\scripts\setup_plugins.ps1 -Category all -IncludeLegacyGenerated
```

```bash
bash scripts/setup_plugins.sh --category all --include-legacy-generated
```

### Enable Plugins in QGIS

1. Open **QGIS**
2. Go to **Plugins → Manage and Install Plugins**
3. Check: **QGIS MCP**, **stream_segmenter**, **dem_bathy_review**
4. Click **QGIS MCP** in the Plugins menu → **Start Server**

### Start the Workspace MCP Server in VS Code

1. If `uv` was just installed while VS Code was already open, run **Developer: Reload Window** first.
2. Open the Command Palette (`Ctrl+Shift+P`) and run **MCP: List Servers**.
3. Find the `qgis` workspace server from `.vscode/mcp.json`.
4. If prompted, confirm that you trust the server.
5. If the server is disabled, enable it.
6. If the server is stopped, start it.

### Switch to Agent Mode in VS Code

1. Open Copilot Chat (`Ctrl+Alt+I`)
2. Click the mode selector dropdown (bottom of chat input)
3. Select **Agent**
4. Type `@` to see available agents

### First Test

```text
@qgis-mcp Ping the QGIS server
```

You should see `{"pong": true}`. If the agent appears to stall, run **MCP: List Servers** and confirm the `qgis` server is trusted and running.

Prefer a guided walkthrough first?

```text
@qgis-faq Walk me through QgisPortAgent and help me choose the right agent.
```

The onboarding agent checks setup, gets you a quick win, and routes you to `@qgis-mcp`, `@new-plugin`, or `@migrate-arc`.

---

## Agents in This Repository

| Agent | Purpose | Use When |
|---|---|---|
| **`@qgis-faq`** | Novice-friendly FAQ onboarding across all QgisPortAgent agents | You are new to the repo, want a first-success walkthrough, or need help choosing the right agent |
| **`@qgis-mcp`** | Control QGIS remotely via MCP | You want to load layers, run processing, apply styles, create maps, or run plugin workflows from Copilot |
| **`@migrate-arc`** | Migrate ArcGIS tools to QGIS Processing algorithms | You have existing ArcGIS toolboxes (`.atbx`, `.tbx`, `.pyt`, `.py`) to port |
| **`@new-plugin`** | Create new QGIS plugins from scratch | You want to build custom QGIS functionality (analysis tools, UI extensions, data connectors) |

### Recommended First Run (Intuitive Walkthrough)

If you are new to this workspace, start here:

```text
@qgis-faq I want a quick walkthrough of how to use these agents to build QGIS tools and maps.
```

Typical walkthrough path:

1. Validate setup (run one setup script, start the QGIS MCP plugin, trust and start the `qgis` workspace MCP server)
2. Achieve first success (`@qgis-mcp Ping the QGIS server`)
3. Route to the correct specialist agent based on intent (`@qgis-mcp` for map control, `@new-plugin` for net-new plugin development, `@migrate-arc` for ArcGIS tool migration)
4. Continue with an exact next prompt and checkpoints

### Brief-First Plugin Workflows

Start here for a beginner-friendly, fill-in-the-blanks workflow:

- [examples/briefs/README.md](examples/briefs/README.md)

Canonical templates:

- New plugin brief template: [examples/briefs/templates/template-new-plugin.yml](examples/briefs/templates/template-new-plugin.yml)
- ArcGIS migration brief template: [examples/briefs/templates/template-migrate-arc.yml](examples/briefs/templates/template-migrate-arc.yml)

Worked brief examples:

- [examples/briefs/worked-examples/stream_segmenter_brief.yaml](examples/briefs/worked-examples/stream_segmenter_brief.yaml)
- [examples/briefs/worked-examples/dem_comparison_brief.yaml](examples/briefs/worked-examples/dem_comparison_brief.yaml)

Compatibility note: root-level brief/template files are temporarily retained as deprecated copies for one release cycle.

---

## Requirements for Copilot Agent Workflow
---


To use the agents in this repository effectively, users should have the following installed and configured:

- **QGIS 3.44**
- **VS Code 1.112**
- **GitHub Copilot extension**
- **GitHub Copilot account** with active access

### VS Code Recommended Extensions

When you open this workspace in VS Code, you will automatically be prompted to install all recommended extensions.
They are defined in `.vscode/extensions.json`. The key ones are listed below.

| Extension | Purpose | Required? |
| --- | --- | --- |
| GitHub Copilot | AI engine that drives all agents | **Required** |
| GitHub Copilot Chat | Agent mode (`@qgis-faq`, `@qgis-mcp`, `@migrate-arc`, `@new-plugin`) | **Required** |
| Python | Syntax, linting, virtual-env picker | **Required** |
| Pylance | Fast type-checking and IntelliSense | **Required** |
| YAML | Validates brief templates in `examples/briefs/templates/*.yml` | Recommended |
| markdownlint | Catches formatting issues in docs | Recommended |
| Markdown All in One | TOC, preview shortcuts, keybindings | Optional |
| Mermaid Markdown support | Renders Mermaid diagrams in preview | Optional |

### Additional Requirements for `@qgis-mcp`

| Tool | Purpose | Install |
|---|---|---|
| **`uv`** | Python package runner — launches the MCP server | Auto-installed by `setup.ps1`, `setup.cmd`, or `setup.sh`, or [install manually](https://docs.astral.sh/uv/) |
| **`github-mcp-server`** | Optional manual workspace server for repo/issue/PR tools. Copilot CLI already includes a built-in GitHub MCP server. | Auto-downloaded by `setup.ps1`, `setup.cmd`, or `setup.sh` if you want the manual workspace binary path |

---

## Controlling QGIS Remotely via MCP

### What it does

The `@qgis-mcp` agent lets you control a running QGIS instance directly from Copilot Chat — load projects, manage layers, apply styles, run processing algorithms, and export maps.

### Architecture

```text
VS Code (Copilot Agent Mode)
  └─ .vscode/mcp.json
  └─ spawns QGIS MCP server (uv run qgis_mcp_server.py)
    └─ TCP socket → localhost:9876
      └─ QGIS plugin (qgis_mcp) listens → executes PyQGIS
```

The default `qgis` MCP flow is fully local. VS Code launches the workspace MCP server over **stdio**, and the MCP server connects to the QGIS plugin over `localhost:9876`.

### Quick Start — MCP

Before the first prompt, open **MCP: List Servers** in VS Code and confirm the `qgis` server is trusted and running.

```text
@qgis-mcp Ping the QGIS server
@qgis-mcp Load project D:/projects/MyProject.qgz
@qgis-mcp Show me the fields of the parcels layer
@qgis-mcp Apply a 5-class quantile style on elevation using the Spectral ramp
@qgis-mcp Run stream_segmenter:batch_stream_segmenter on the streams layer
```

### Available MCP Tools (23)

| Category | Tool | Description |
|---|---|---|
| **Connection** | `ping` | Check connectivity |
| | `get_qgis_info` | QGIS version, profile, plugin count |
| **Project** | `load_project` | Load a .qgz / .qgs file |
| | `create_new_project` | Create and save a new project |
| | `get_project_info` | Project filename, CRS, layers |
| | `save_project` | Save current project |
| **Layers** | `add_vector_layer` | Add shapefile / GeoPackage / GeoJSON |
| | `add_raster_layer` | Add GeoTIFF / other raster |
| | `get_layers` | List all layers with metadata |
| | `remove_layer` | Remove a layer by ID |
| | `get_layer_features` | Get attributes + geometry (WKT) |
| | `get_layer_fields` | Field schema + sample values |
| **Styling** | `set_layer_style` | Apply QML or graduated renderer |
| | `set_layer_labels` | Configure labeling |
| **Canvas** | `zoom_to_layer` | Zoom to layer extent |
| | `set_map_extent` | Set extent by coords or layer |
| | `add_layer_to_group` | Move layer into tree group |
| | `set_layer_visibility` | Toggle layer on/off |
| **Processing** | `execute_processing` | Run any Processing algorithm |
| | `get_processing_algorithms` | List algorithms + parameters |
| **Export** | `render_map` | Render canvas to image |
| | `export_print_layout` | Export to PDF/PNG via layout |
| **Advanced** | `execute_code` | Run arbitrary PyQGIS code |

### Workflow Prompts

The MCP server includes reusable prompt templates:

| Prompt | Description |
|---|---|
| `load_project` | Load a project, list layers, zoom to extent |
| `dem_comparison` | Run DEM bathymetry review on paired DEMs |
| `segment_streams` | Run stream segmenter batch pipeline |
| `apply_graduated_style` | Apply graduated symbology to a numeric field |

### GitHub MCP Server

If you are using Copilot CLI, the GitHub MCP server is already built in with read-only tools enabled by default. You do not need this repo to install it.

Verify that the built-in server is available from an active Copilot CLI session:

```text
/mcp show github-mcp-server
```

If you want to customize the built-in server for a session, start Copilot CLI with the upstream flags described in the GitHub MCP docs:

```bash
copilot --add-github-mcp-toolset discussions
copilot --add-github-mcp-toolset stargazers
copilot --enable-all-github-mcp-tools
```

If you want to create a custom GitHub MCP configuration in Copilot CLI, the upstream guide recommends interactive setup from an active Copilot CLI session:

```text
/mcp add
```

That flow writes Copilot CLI MCP configuration to `~/.copilot/mcp-config.json`, not to this workspace's `.vscode/mcp.json`.

Example Copilot CLI configuration using the hosted GitHub MCP server:

```json
{
  "mcpServers": {
    "github-mcp-server": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"
      }
    }
  }
}
```

Server naming note: name the server `github-mcp-server` to replace the built-in server, or use a different name such as `github` to run a second configuration alongside it.

### Optional Workspace-Managed GitHub MCP Binary

This repo can still download the standalone `github-mcp-server` binary if you want to register GitHub MCP directly in the workspace instead of relying on Copilot CLI's built-in server.

To use the manual workspace path:

1. Run your platform setup script and answer **Y** when prompted to download the binary
2. Create a [fine-grained PAT](https://github.com/settings/personal-access-tokens/new) with the scopes you need
3. Open `.vscode/mcp.json` and add a `github` server entry, or use **MCP: Add Server**
4. Start the new server from **MCP: List Servers** and provide the PAT when prompted

Example combined `.vscode/mcp.json` with both `qgis` and `github`:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "github_token",
      "description": "GitHub Personal Access Token",
      "password": true
    }
  ],
  "servers": {
    "qgis": {
      "command": "uv",
      "args": [
        "--directory",
        "${workspaceFolder}/qgis_mcp/src",
        "run",
        "qgis_mcp_server.py"
      ]
    },
    "github": {
      "command": "${workspaceFolder}/.mcp/github-mcp-server.exe",
      "args": ["stdio"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${input:github_token}"
      }
    }
  }
}
```

---

## Migrating ArcGIS Tools

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
pip install -r research/requirements.txt
python -m venv .venv
.venv\Scripts\activate          # Windows
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

Output is written to `plugins/generated/<tool_name>_plugin/` by default
(legacy `qgis-tools/` output is still supported for compatibility).

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

The `@new-plugin` agent guides you from concept to production-ready QGIS 3.44 LTR plugin through an interactive 8-step workflow:

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
@new-plugin I want to create a plugin that downloads weather data from a public API and displays it as a heatmap layer in QGIS.
```
1. Discovery questions to understand your requirements

The agent will guide you through:
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
- UI requirements
- Plugin purpose and target users
- Data types and spatial operations
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

The agent automatically selects the optimal archetype based on your requirements:
### Plugin Archetypes


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

| **0** | **Concept Discovery** | Agent asks structured questions to understand requirements |
| Step | Phase | What Happens |
|---|---|---|
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

Generated plugins are created in `plugins/generated/` by default:

```
<your-workspace>/
├── plugins/
│   └── generated/
│       └── <plugin_name>/
│           ├── metadata.txt
│           ├── __init__.py
│           ├── <plugin_name>_plugin.py
│           ├── processing_provider/        # For Processing Provider archetypes
│           ├── map_tools/                  # For Interactive Tool archetypes
│           ├── ui/                         # For UI Extension archetypes
│           ├── data_sources/               # For Data Connector archetypes
│           ├── resources/
│           ├── tests/
│           ├── docs/
│           ├── scripts/
│           │   └── package_plugin.py
│           └── dist/
│               └── <plugin_name>.zip
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
mklink /J "%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\<plugin_name>" "<your-workspace>\plugins\generated\<plugin_name>"
```

Install **Plugin Reloader** from the QGIS Plugin Repository and press **F5** after each code change.

---

## Output Structure

### Migrated Plugins (from ArcGIS)

Each migration produces a plugin directory in `plugins/generated/`:

```
plugins/generated/<tool_name>_plugin/
├── metadata.txt                  # hasProcessingProvider=yes; qgisMinimumVersion=3.44
├── requirements.txt              # pinned OSS dependencies
├── __init__.py                   # classFactory() boilerplate
├── main_plugin.py                # self.initProcessing()
├── migration_report.md           # per-block confidence scores + risk summary
├── tests/
│   └── test_<tool_name>.py       # pytest stubs with sample data
└── processing_provider/
    ├── __init__.py
    ├── provider.py               # QgsProcessingProvider subclass
    └── <tool_name>_algorithm.py  # QgsProcessingAlgorithm subclass
```

### Created Plugins (from scratch)

Each new plugin is created in `plugins/generated/` with archetype-specific components:

```
plugins/generated/<plugin_name>/
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
│       ├── qgis-faq.agent.md               # Novice-friendly onboarding and FAQ routing
│       ├── migrate-arc.agent.md           # Migration agent definition
│       ├── new-plugin.agent.md            # Plugin builder agent definition
│       └── qgis-mcp.agent.md             # QGIS MCP remote-control agent
├── .mcp/
│   └── github-mcp-server*                # GitHub MCP Server binary (installed by setup script)
├── .vscode/
│   ├── qgis_getting_started.instructions.md # Guided onboarding rules and checkpoints
│   ├── qgis_getting_started.prompt.md       # /getting-started walkthrough prompt template
│   ├── arcgis_migration.instructions.md   # Ambient migration rules (Phases 0–6)
│   ├── migrate_tool.prompt.md             # /migrate_tool prompt template
│   ├── qgis_plugin_builder.instructions.md # Ambient plugin builder rules (Phases 0–8)
│   ├── create_plugin.prompt.md            # /create_plugin prompt template
│   ├── qgis_mcp.instructions.md           # Ambient MCP rules (architecture, tools)
│   ├── mcp.json                           # MCP server registrations
│   ├── settings.json                      # Python interpreter + editor settings
│   └── extensions.json                    # Recommended VS Code extensions
├── dem_bathy_review/                      # DEM bathymetry review plugin
├── examples/                              # Sample ArcGIS source files for testing
│   ├── py/                                # Standalone .py scripts
│   ├── atbx/                              # Modern ArcGIS Pro toolboxes
│   ├── pyt/                               # Python Toolboxes
│   └── tbx_binary/                        # Binary ArcMap OLE toolboxes
├── qgis_mcp/                              # QGIS MCP plugin + server
│   ├── qgis_mcp_plugin.py                 # QGIS plugin (socket server, dock widget)
│   ├── src/
│   │   ├── qgis_mcp_server.py             # FastMCP server (23 tools, 4 prompts, 2 resources)
│   │   └── qgis_socket_client.py          # TCP client (length-prefixed framing)
│   ├── tests/                             # Protocol tests
│   └── docs/                              # User guide
├── plugins/
│   ├── source/                            # Optional canonical home for maintained plugins
│   └── generated/                         # Generated migration/plugin outputs
├── qgis-tools/                            # Legacy generated output path (compatibility)
├── research/                              # .tbx parser, CLI generator
├── scripts/                               # Utility scripts + plugin link automation
├── stream_segmenter/                      # Stream segmenter plugin
├── test/                                  # Integration test data
├── .env.example                           # Environment variable template
├── setup.ps1                              # One-command workspace bootstrap (PowerShell)
├── setup.cmd                              # One-command workspace bootstrap (Command Prompt)
├── setup.sh                               # One-command workspace bootstrap (Linux/macOS shell)
└── README.md
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` on port 9876 | QGIS MCP plugin not started | In QGIS: **Plugins → QGIS MCP → Start Server** |
| `uv: command not found` | `uv` not installed | Run your platform setup script (`setup.ps1`, `setup.cmd`, or `setup.sh`) or install via [docs.astral.sh/uv](https://docs.astral.sh/uv/) |
| Agent stalls or never connects | VS Code `qgis` MCP server was not trusted, enabled, or started | Run **MCP: List Servers**, trust `qgis`, then enable/start it |
| Agent says "no tools available" | VS Code < 1.101 | Upgrade VS Code (1.101+ required for MCP) |
| `QGIS_MCP_PORT` ignored | Plugin reads env at start time | Restart QGIS after changing `.env` |
| GitHub MCP returns 401 | Invalid or expired PAT | Re-create [fine-grained PAT](https://github.com/settings/personal-access-tokens/new) with correct scopes |
| `uv` was installed but MCP still fails to start | VS Code has stale PATH state | Run **Developer: Reload Window** and start `qgis` again from **MCP: List Servers** |
| Plugin not listed in QGIS | Symlink missing or broken | Re-run `scripts/setup_plugins.ps1` (Windows) or `scripts/setup_plugins.sh` (Linux/macOS) |
| `SRE module mismatch` on launch | Google Cloud SDK pollutes `PYTHONPATH` | Clear `PYTHONPATH` and `PYTHONHOME` before launching QGIS |

---

## Customising the Agents

### FAQ Agent (`@qgis-faq`)

#### Adjusting the walkthrough flow

Edit `.vscode/qgis_getting_started.prompt.md` to change the sequence of onboarding steps, branch options, and handoff formatting.

#### Tuning onboarding rules and checkpoints

Edit `.vscode/qgis_getting_started.instructions.md` to update readiness checks, troubleshooting priorities, and guardrails.

#### Changing routing behavior

Edit `.github/agents/qgis-faq.agent.md` to adjust intent routing between `@qgis-mcp`, `@new-plugin`, and `@migrate-arc`.

### MCP Agent (`@qgis-mcp`)

#### Changing the socket port

Set `QGIS_MCP_PORT` in your `.env` file. The QGIS plugin reads this on startup, and `.vscode/mcp.json` passes it to the MCP server.

#### Optional local authentication

The QGIS MCP socket now defaults to **no auth** for local-only sessions.

To require authentication:

1. Enable **Require auth token** in the QGIS MCP dock widget (or set `QGIS_MCP_REQUIRE_AUTH=1` before launching QGIS).
2. Start the server and copy the displayed token.
3. Set `QGIS_MCP_TOKEN` in the MCP server environment before starting VS Code MCP.

If auth is disabled in QGIS MCP, `QGIS_MCP_TOKEN` is ignored.

#### Adding new MCP tools

1. Add a handler method in [qgis_mcp/qgis_mcp_plugin.py](qgis_mcp/qgis_mcp_plugin.py) (register in `_handle_command`)
2. Add a `@mcp.tool()` function in [qgis_mcp/src/qgis_mcp_server.py](qgis_mcp/src/qgis_mcp_server.py)
3. Document the tool in [.vscode/qgis_mcp.instructions.md](.vscode/qgis_mcp.instructions.md) and [.github/agents/qgis-mcp.agent.md](.github/agents/qgis-mcp.agent.md)

#### Adding workflow prompts

Add `@mcp.prompt()` functions in [qgis_mcp/src/qgis_mcp_server.py](qgis_mcp/src/qgis_mcp_server.py). These appear as reusable templates in Copilot.

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

### Plugin Builder Agent (`@new-plugin`)

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