# examples/

Sample ArcGIS source files for testing QgisPortAgent migrations.
Each subdirectory contains one real-world or synthetic ArcGIS tool file plus
a short README explaining what migration scenario it exercises.

---

## Brief-First Onboarding

Before creating or migrating plugins, start with the brief templates:

- Briefs hub: [briefs/README.md](briefs/README.md)
- New plugin template: [briefs/templates/template-new-plugin.yml](briefs/templates/template-new-plugin.yml)
- ArcGIS migration template: [briefs/templates/template-migrate-arc.yml](briefs/templates/template-migrate-arc.yml)
- Worked examples: [briefs/worked-examples/stream_segmenter_brief.yaml](briefs/worked-examples/stream_segmenter_brief.yaml), [briefs/worked-examples/dem_comparison_brief.yaml](briefs/worked-examples/dem_comparison_brief.yaml)

---

## Example Inventory

| Path | Format | Source | License Tier | Key Scenarios |
|---|---|---|---|---|
| `py/nrcs_create_watershed/` | Standalone `.py` | USDA-NRCS | Advanced (Spatial Analyst) | `arcpy.sa.*`, hardcoded paths, Basic→Advanced crosswalk |
| `py/nrcs_avg_slope/` | Standalone `.py` | USDA-NRCS | Basic–Standard | Simple geoprocessing, `arcpy.management.*` |
| `atbx/nrcs_engineering_tools/` | `.atbx` (Modern Pro Toolbox) | USDA-NRCS | Varies | Multi-tool `.atbx` ZIP/JSON parsing |
| `atbx/fluvial_geomorph/` | `.atbx` (Modern Pro Toolbox) | FluvialGeomorph | Standard–Advanced | Hydrology, reach analysis, multi-tool |
| `pyt/field_calculator_example/` | `.pyt` (Python Toolbox) | Synthetic | Basic | Python 2.7 patterns, row-wise cursors → vectorisation |
| `tbx_binary/pointtools/` | `.tbx` (Binary ArcMap OLE) | Dan-Patterson | Basic–Standard | Binary OLE parsing via `research/tbx_parser.py` |

---

## How to Use

### Migrate a single file using the prompt

```
/migrate_tool examples/py/nrcs_create_watershed/Create_Watershed.py
```

### Migrate using GitHub Copilot Chat

Open any example file, then type in the chat:

> Migrate `examples/pyt/field_calculator_example/FieldCalculatorTools.pyt` to QGIS.

The agent automatically:
1. Detects the source format
2. Parses parameters and execute logic
3. Generates a QGIS Processing Plugin into `plugins/generated/<tool_name>_plugin/`
4. Produces a `migration_report.md` with per-block confidence scores

---

## Format Coverage

| Format | Phase | Parser |
|---|---|---|
| `.atbx` (ZIP/JSON, ArcGIS Pro) | 1.1 | `zipfile` + JSON |
| `.tbx` (Binary OLE, ArcMap) | 1.2 | `research/tbx_parser.py` |
| `.tbx` (XML, ArcGIS Desktop 9.x) | 1.3 | ElementTree |
| `.pyt` (Python Toolbox) | 1.4 | `ast.parse()` |
| `.py` (Standalone ArcPy script) | 1.5 | AST + regex |
