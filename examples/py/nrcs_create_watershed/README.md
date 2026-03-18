# examples/py/nrcs_create_watershed/

**Source**: [USDA-NRCS/SUPPORT](https://github.com/USDA-NRCS/SUPPORT)  
**File**: `Create_Watershed.py`  
**ArcGIS License**: Advanced (requires Spatial Analyst Extension)  
**Size**: ~15 KB

---

## What this script does

Creates a watershed delineation from a digital elevation model (DEM) and a
pour-point feature class.  Uses the ArcGIS Spatial Analyst hydrology toolset:
`Fill → FlowDirection → FlowAccumulation → SnapPourPoint → Watershed`.

## Migration scenarios exercised

| Scenario | QgisPortAgent behaviour |
|---|---|
| `arcpy.sa.*` (Spatial Analyst) | Crosswalks to WhiteboxTools hydrology (`whitebox:FillDepressions`, `whitebox:D8Pointer`, `whitebox:D8FlowAccumulation`, `whitebox:SnapPourPoints`) |
| `arcpy.CheckExtension("Spatial")` | Removed; WhiteboxTools is free and open-source |
| Hardcoded workspace paths | Elevated to `QgsProcessingParameterFolderDestination` |
| Raster intermediate datasets | Replaced with `QgsProcessing.TEMPORARY_OUTPUT` |
| `arcpy.env.workspace` | Moved to explicit parameter |

## Expected confidence range

`0.80–0.90` — Hydrology toolset is well-supported in WhiteboxTools; some parameter
mapping requires manual validation (snap distance units, flow accumulation threshold).

## Quick start

```
/migrate_tool examples/py/nrcs_create_watershed/Create_Watershed.py
```
