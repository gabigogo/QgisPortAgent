---
description: "Guide a user through creating a QGIS 3.44 plugin from concept to production"
---

# Create QGIS 3.44 Plugin from Concept

Guide the user through the complete development lifecycle of a **production-ready QGIS 3.44.0
LTR plugin**. Follow each step in sequence. Do not skip steps without explicit user confirmation.

---

## Step 0 — Concept Discovery & Requirements

Before generating any code, understand the user's vision through structured conversation.

### Questions to Ask

Present these questions conversationally, adapting based on each response:

1. **Purpose & Problem**
   - "What problem will this plugin solve?"
   - "What workflow or analysis does it support?"

2. **Target Users**
   - "Who will use this plugin?" (GIS analysts, field workers, developers, students)
   - "What is their typical technical skill level?"

3. **Data & Operations**
   - "What types of data will it work with?" (vector, raster, tables, web services)
   - "What spatial operations are needed?" (analysis, visualization, data import/export)
    - "Will any distance-based outputs be used? If yes, what is the computational base unit (meters) and what display units are required (miles/km/feet)?"
    - "If yes, apply the shared geoprocessing guardrails from:
        - .vscode/geoprocessing_guardrails.instructions.md (authoritative)
        - .github/geoprocessing-guardrails.md (mirror)."

4. **User Interface**
   - "How should users interact with the plugin?" (dialog box, toolbar button, Processing toolbox, map tool)
   - "Do you need custom map interaction?" (click to select, draw shapes, measure)

5. **External Integration**
   - "Does it connect to external services?" (REST APIs, databases, cloud storage)
   - "Are there authentication requirements?"

6. **Performance & Scale**
   - "What dataset sizes do you expect?" (hundreds, thousands, millions of features)
   - "Are there any real-time processing requirements?"

7. **Deployment**
   - "How will it be distributed?" (internal team, public QGIS Plugin Repository, GitHub release)

### Output: Requirements Summary

Present a structured summary and wait for user confirmation before proceeding:

```markdown
## Plugin Concept Summary

**Name:** [Suggested plugin name]
**Purpose:** [One-sentence description]
**Archetype:** [Processing Provider / Interactive Tool / Data Connector / UI Extension / Hybrid]

**Key Features:**
- Feature 1
- Feature 2
- Feature 3

**Data Types:** Vector / Raster / Both
**UI Components:** [Dialog / Toolbar / Map Tool / Processing Toolbox]
**External Dependencies:** [APIs, databases, or services — or "None"]

**Technical Stack:**
- Python 3.12+
- PyQGIS 3.44 API
- [Additional libraries: geopandas, rasterio, etc.]

**Performance Requirements:**
- Dataset size: [Small / Medium / Large]
- Processing mode: [Interactive / Batch / Background]

**Distribution:** [Internal / Public Repository / Both]
```

---

## Step 1 — Architecture Design

Based on confirmed requirements, design the plugin architecture.

### 1.1 Archetype Classification

State the chosen archetype and rationale:

> "Based on your requirements, this will be a **[Archetype]** plugin because [rationale].
> The core components will be: [list components]."

### 1.2 Directory Structure

Present the proposed directory layout and explain each component's purpose:

```
<plugin_name>/
├── metadata.txt
├── __init__.py
├── <plugin_name>_plugin.py
├── [archetype-specific subdirectories]
├── resources/
├── tests/
├── docs/
└── requirements.txt
```

### 1.3 Component Interaction Diagram

For plugins with multiple components, show the data/control flow:

```
[User Action] → [UI Component] → [Core Logic] → [QGIS API] → [Output]
```

### 1.4 Dependency Planning

List all external dependencies with version constraints and a brief justification for each.

> Wait for user approval before generating any code.

---

## Step 2 — Generate Plugin Scaffold

Create the complete directory structure and all boilerplate files.

### 2.1 Core Files (all plugins)

Generate:

1. **`metadata.txt`** — QGIS-standard plugin metadata
2. **`__init__.py`** — Entry point with `classFactory()`
3. **`<plugin_name>_plugin.py`** — Main class implementing the QGIS plugin lifecycle
4. **`requirements.txt`** — All Python dependencies with version constraints

`metadata.txt` MUST include Qt6 compatibility when targeting modern QGIS builds:

```ini
supportsQt6=True
```

### 2.2 Archetype-Specific Components

| Archetype | Files to Generate |
|---|---|
| **Processing Provider** | `processing_provider/provider.py`, `processing_provider/algorithms/` |
| **Interactive Tool** | `map_tools/custom_map_tool.py`, `ui/dialogs.py` |
| **Data Connector** | `data_sources/api_client.py`, `data_sources/database_connector.py`, `cache/cache_manager.py` |
| **UI Extension** | `ui/main_dialog.py`, `ui/forms/*.ui` |
| **Hybrid** | Combination of the above |

### 2.3 Resources

Generate:
- `resources/icon.svg` — Plugin icon (SVG, 256×256 px)
- `resources/resources.qrc` — Qt resource compilation file

### 2.4 Test Scaffold

Generate:
- `tests/conftest.py` — Shared fixtures and pytest configuration
- `tests/test_<component>.py` — Unit test file templates for each component

### Output Format

Present each file with its path clearly labelled:

```python
# <plugin_name>/__init__.py
# --- complete file contents ---
```

Explain the purpose of each key section and any non-obvious PyQGIS patterns used.

---

## Step 3 — Implement Core Functionality

Generate the main plugin logic based on confirmed requirements.

### 3.1 Processing Algorithms (if applicable)

For each algorithm:

1. **Specification** — Name, purpose, inputs, outputs, processing logic description
2. **Implementation** — Complete `QgsProcessingAlgorithm` subclass with:
   - `initAlgorithm()` defining all parameters
   - `processAlgorithm()` with core logic
   - Cancellation checks via `feedback.isCanceled()`
   - Progress reporting via `feedback.setProgress()`
    - Distance safety checks: normalize computational lengths to meters; if `QgsDistanceArea.willUseEllipsoid()` is false, convert CRS-native values to meters before threshold math
3. **Optimisation** — Vectorized operations where possible; spatial indexing for large datasets

### 3.2 UI Components (if applicable)

1. **Layout** — Qt Designer `.ui` file or inline PyQt5 code
2. **Widgets** — Combo boxes, line edits, file pickers, layer selectors
3. **Signal/slot connections** — Button handlers, input validation, dynamic updates

### 3.3 Map Tools (if applicable)

1. **`QgsMapTool` subclass** — Canvas event handlers (click, move, release)
2. **Visual feedback** — Rubber bands, vertex markers
3. **Feature identification** — Spatial query logic

### 3.4 Data Connectors (if applicable)

1. **API client** — Authentication, request/response parsing, retry logic
2. **Caching layer** — Local cache management and expiration policies

---

## Step 4 — Add Error Handling & Validation

Harden all generated code against real-world usage.

### 4.1 Input Validation

```python
if not layer or not layer.isValid():
    raise QgsProcessingException("Invalid input layer")

if buffer_distance <= 0:
    raise QgsProcessingException("Buffer distance must be positive")
```

### 4.2 Exception Handling

Wrap all risky operations and surface errors to the user:

```python
try:
    result = external_api_call()
except requests.RequestException as e:
    feedback.reportError(f"API request failed: {str(e)}")
    return {}
```

### 4.3 User Feedback

Provide clear success, warning, and error messages at appropriate severity levels:

```python
self.iface.messageBar().pushMessage(
    "Success", "Processing complete", level=Qgis.Success, duration=3
)
```

---

## Step 5 — Generate Tests

Create a comprehensive pytest test suite.

### 5.1 Unit Tests

For each function/algorithm, include at minimum:
- A test with valid input verifying correct output
- A test with invalid input verifying graceful failure
- For distance-based algorithms, include CRS/unit conversion regression tests (projected meters, US survey feet, geographic CRS)

```python
def test_algorithm_with_valid_input(sample_layer):
    """Algorithm processes valid input and returns expected output."""
    ...

def test_algorithm_raises_on_invalid_layer():
    """Algorithm raises QgsProcessingException for an invalid layer."""
    ...
```

### 5.2 Integration Tests

```python
def test_plugin_loads():
    """Plugin loads into QGIS without errors."""
    ...

def test_processing_provider_available():
    """Processing algorithms are registered in the QGIS registry."""
    ...
```

### 5.3 Test Fixtures

Provide reusable sample data fixtures in `tests/conftest.py`:

```python
@pytest.fixture
def sample_vector_layer():
    """In-memory point layer with representative test features."""
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
    # Add test features...
    return layer
```

---

## Step 6 — Documentation

Generate user-facing and developer-facing documentation.

### 6.1 User Guide (`docs/user_guide.md`)

```markdown
# [Plugin Name] User Guide

## Installation
[Step-by-step installation instructions]

## Quick Start
[Basic usage example]

## Features
[Detailed feature descriptions]

## Troubleshooting
[Common issues and solutions]
```

### 6.2 API Docstrings

Add Google-style docstrings to all public methods (see Phase 5.1 in the instructions for template).

### 6.3 README.md

```markdown
# [Plugin Name]

[Brief description and purpose]

## Features
- Feature 1
- Feature 2

## Installation
[Instructions]

## Usage
[Quick example]

## Development
[Setup instructions for contributors]

## License
[License information]
```

---

## Step 7 — Packaging & Distribution

Prepare the plugin for deployment.

### 7.1 Validate metadata.txt

Confirm all required fields are populated:

- [ ] `name`
- [ ] `qgisMinimumVersion`
- [ ] `supportsQt6=True` (required for Qt6-based QGIS)
- [ ] `description`
- [ ] `version`
- [ ] `author`
- [ ] `email`
- [ ] `about`
- [ ] `tracker`
- [ ] `repository`

### 7.2 Run Packaging Script

Execute `scripts/package_plugin.py` to produce `dist/<plugin_name>.zip`.

### 7.3 Pre-Release Checklist

- [ ] Plugin loads without errors in QGIS 3.44
- [ ] All features tested manually
- [ ] Unit tests pass (`pytest tests/ -v`)
- [ ] Coverage ≥ 80% (`pytest --cov=<plugin_name> tests/`)
- [ ] No hardcoded paths or credentials
- [ ] Documentation complete
- [ ] `LICENSE` file present
- [ ] Icon provided (SVG, 256×256 px)
- [ ] Code passes `flake8` and `black`

### 7.4 Distribution Options

| Path | Steps |
|---|---|
| **Manual** | Copy zip to QGIS plugins directory; enable in Plugin Manager |
| **GitHub Release** | Create repo, tag release, attach zip as release asset |
| **QGIS Plugin Repository** | Submit to plugins.qgis.org, await review, users install via Plugin Manager |

---

## Step 8 — Handoff & Next Steps

Provide a concise summary of all deliverables and recommended next steps.

### 8.1 Deliverables Summary

```
✅ Plugin scaffold:     <plugin_name>/
✅ Source code:         [N files generated]
✅ Tests:               [N test files]
✅ Documentation:       docs/user_guide.md, README.md
✅ Distribution:        dist/<plugin_name>.zip
```

### 8.2 Recommended Testing Workflow

```markdown
1. Copy plugin directory to your QGIS plugins folder
2. Restart QGIS and enable the plugin in Plugin Manager
3. Test each feature manually with sample data
4. Run automated tests: pytest tests/ -v --cov=<plugin_name>
5. Test on Windows and Linux if cross-platform support is needed
```

### 8.3 Suggested Next Steps

**Immediate**
- [ ] Install and test plugin locally
- [ ] Review generated code and customise as needed

**Short-term**
- [ ] Gather early-user feedback
- [ ] Fix bugs discovered in testing
- [ ] Expand test coverage to edge cases

**Long-term**
- [ ] Implement additional features
- [ ] Submit to QGIS Plugin Repository
- [ ] Set up CI/CD with [qgis-plugin-ci](https://github.com/opengisch/qgis-plugin-ci)

### 8.4 Support Resources

| Resource | URL |
|---|---|
| QGIS Python API 3.44 | <https://qgis.org/pyqgis/3.44> |
| PyQGIS Cookbook | <https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/> |
| QGIS Stack Exchange | <https://gis.stackexchange.com/questions/tagged/qgis> |
| QGIS Developers List | <https://lists.osgeo.org/mailman/listinfo/qgis-developer> |

---

## Execution Guidelines

1. **Always start with Step 0** unless the user provides a complete requirements document.
2. **Wait for confirmation** at each major decision point (archetype, structure, feature set).
3. **Generate complete, runnable code** — no pseudocode or unexplained placeholders.
4. **Follow PyQGIS best practices** as defined in `qgis_plugin_builder.instructions.md`.
5. **Explain decisions** — tell the user why a specific approach was chosen.
6. **Adapt to feedback** — if the user requests changes, regenerate only the affected components.
7. **Maintain consistency** — all generated files must work together as a coherent whole.

---

## Quick Start

A user initiates plugin creation with a natural language description of their idea:

> "I want to create a QGIS plugin that downloads weather data from a public API
> and displays it as a heatmap layer."

The agent starts at **Step 0** (Concept Discovery) and guides the user through all eight steps
to a fully packaged, tested, and documented QGIS plugin.
