# examples/atbx/fluvial_geomorph/

**Source**: [FluvialGeomorph/FluvialGeomorph-toolbox](https://github.com/FluvialGeomorph/FluvialGeomorph-toolbox)  
**File**: `FluvialGeomorph.atbx`  
**Format**: Modern ArcGIS Pro Toolbox (ZIP/JSON)  
**Size**: ~216 KB  
**License**: Standard–Advanced

---

## What this toolbox contains

A comprehensive fluvial geomorphology analysis toolbox for reach-scale channel
geometry assessment, bankfull estimation, cross-section extraction, longitudinal
profile analysis, and hydraulic geometry relationships.

## Migration scenarios exercised

| Scenario | QgisPortAgent behaviour |
|---|---|
| `.atbx` ZIP/JSON parsing (Phase 1.1) | Unzip + parse `*.tool/` JSON metadata |
| LiDAR / DEM processing | rasterio + WhiteboxTools crosswalk |
| Cross-section geometry extraction | `native:transect` / geopandas geometry ops |
| Linear referencing | `native:linelocatepoint` + geopandas |
| R/Python hybrid tools (if present) | `QgsProcessingParameterString` subprocess bridge |
| Complex parameter dependency chains | `checkParameterValues()` lifecycle hook |

## Expected confidence range

`0.70–0.88` — Hydro-geomorphology tools have good OSS coverage; some advanced
geometry operations require careful validation.

## Quick start

```
/migrate_tool examples/atbx/fluvial_geomorph/FluvialGeomorph.atbx
```
