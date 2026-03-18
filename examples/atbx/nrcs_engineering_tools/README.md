# examples/atbx/nrcs_engineering_tools/

**Source**: [USDA-NRCS/NRCS-Engineering-Tools---ArcGIS-Pro](https://github.com/USDA-NRCS/NRCS-Engineering-Tools---ArcGIS-Pro)  
**File**: `NRCS Engineering Tools.atbx`  
**Format**: Modern ArcGIS Pro Toolbox (ZIP/JSON)  
**Size**: ~105 KB  
**License**: Varies by tool (Basic → Advanced)

---

## What this toolbox contains

A multi-tool ArcGIS Pro toolbox covering NRCS engineering workflows:
land levelling, pond/reservoir design, terrace layout, contour farming analysis,
and grassed waterway dimensioning.

## Migration scenarios exercised

| Scenario | QgisPortAgent behaviour |
|---|---|
| `.atbx` ZIP/JSON parsing (Phase 1.1) | Unzip + parse `*.tool/` JSON metadata |
| Multiple tools in one toolbox | One `QgsProcessingAlgorithm` class per tool, registered in a shared `QgsProcessingProvider` |
| Mixed license tiers | Per-tool confidence scoring based on ArcGIS license level |
| Feature geometry operations | `native:clip`, `native:buffer`, `native:dissolve` etc. |
| Field mapping parameters | `QgsProcessingParameterField` |

## Expected confidence range

`0.75–0.92` depending on individual tool complexity.

## Quick start

```
/migrate_tool "examples/atbx/nrcs_engineering_tools/NRCS Engineering Tools.atbx"
```
